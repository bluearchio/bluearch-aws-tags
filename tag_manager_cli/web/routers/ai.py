"""AI chat endpoints with SSE streaming."""

import asyncio
import json
import queue
import re
import threading
import time
import uuid
from collections import OrderedDict
from typing import AsyncGenerator, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from ..dependencies import get_current_user, LocalUser
from ..core_storage import (
    create_storage_payload,
    delete_storage_payload,
    get_storage_payload,
    list_storage_payloads,
    update_storage_payload,
)
from ...utils.core_client import CoreRuntimeError
from ..schemas.ai import (
    ChatRequest,
    ChatResponse,
    ConversationSummary,
    ModelInfo,
    ModelsResponse,
    QuestionRequest,
)

router = APIRouter(prefix="/api/v1/ai", tags=["ai"])

# In-memory session store (max 20, FIFO eviction)
_sessions: OrderedDict = OrderedDict()
_MAX_SESSIONS = 20

MODELS = {
    "haiku": {
        "description": "Fast and cost-effective",
    },
    "sonnet": {
        "description": "Balanced performance and quality",
    },
    "opus": {
        "description": "Highest quality for complex tasks",
    },
}

# Write tools that should not be cached
_WRITE_TOOLS = {"create_cloudwatch_alarm", "set_account_scope"}


def _classify_query_complexity(question: str) -> str:
    """Classify query complexity to auto-select the appropriate model.

    Returns 'haiku' for simple queries, 'sonnet' for complex ones.
    """
    q = question.lower().strip()

    complex_patterns = [
        r'\bcompar',      # compare, comparing
        r'\banalyz',      # analyze, analyzing
        r'\btrend',
        r'\banomaly',
        r'\banomalies',
        r'\boptimiz',     # optimize, optimization
        r'\bwhy\b',
        r'\bacross accounts\b',
        r'\bcross.account',
        r'\bmulti.region',
        r'\ball accounts\b',
        r'\bcorrelat',
        r'\bforecast',
        r'\brecommend',
        r'\bstrateg',
        r'\broot cause',
        r'\bexplain why',
        r'\bbreak.*down',
        r'\bdiagnost',
    ]

    for pattern in complex_patterns:
        if re.search(pattern, q):
            return "sonnet"

    # Long questions are usually complex
    if len(q) > 200:
        return "sonnet"

    return "haiku"


def _extract_suggestions(text: str) -> List[str]:
    """Extract follow-up suggestions from AI response text."""
    suggestions = []
    lines = text.split('\n')
    in_suggestions = False

    for line in lines:
        lower_line = line.lower()
        if ('related questions' in lower_line or
                'you might find useful' in lower_line or
                'would you like me to' in lower_line or
                'would you like to' in lower_line):
            in_suggestions = True
            continue

        if in_suggestions:
            if line.strip() == '---' or line.strip() == '':
                if suggestions:
                    break
                continue

            stripped = line.strip()
            suggestion = None

            if stripped.startswith('- ') or stripped.startswith('* '):
                suggestion = stripped[2:].strip()
            elif re.match(r'^[1-3][.\s]', stripped):
                suggestion = re.sub(r'^[1-3][.\s]+', '', stripped).strip()

            if suggestion:
                suggestion = suggestion.strip('"').strip("'")
                suggestion = re.sub(r'\s*\([^)]+\)\s*$', '', suggestion)
                if suggestion and len(suggestions) < 3:
                    suggestions.append(suggestion)

    return suggestions


def _get_or_create_session(session_id: Optional[str], model: str):
    """Get an existing assistant session or create a new one."""
    global _sessions

    if session_id and session_id in _sessions:
        return session_id, _sessions[session_id]

    # Create new session
    from ...integrations.aws_assistant import BedrockAWSAssistant

    # Handle "auto" model selection - resolve to actual model alias
    if model == "auto":
        model_alias = "haiku"  # Default; will be overridden per-question
    else:
        model_alias = model if model in MODELS else "haiku"
    assistant = BedrockAWSAssistant(model_id=model_alias)
    new_id = session_id or str(uuid.uuid4())

    # FIFO eviction
    if len(_sessions) >= _MAX_SESSIONS:
        _sessions.popitem(last=False)

    _sessions[new_id] = assistant
    return new_id, assistant


class ToolCallCapture:
    """Captures tool calls from the assistant formatter and queues them."""

    def __init__(self, original_formatter, event_queue: queue.Queue):
        self._original = original_formatter
        self._queue = event_queue
        self._tool_start_times: dict = {}

    def print_tool_call(self, tool_name: str, tool_input: dict):
        """Intercept tool calls and emit to queue."""
        started_at = time.time()
        self._tool_start_times[tool_name] = started_at
        self._queue.put(("tool_call", {
            "name": tool_name,
            "input": tool_input,
            "started_at": started_at,
        }))
        if hasattr(self._original, "print_tool_call"):
            self._original.print_tool_call(tool_name, tool_input)

    def print_tool_result_summary(self, tool_name: str, success: bool, summary: str = ""):
        """Intercept tool results and emit to queue."""
        started_at = self._tool_start_times.pop(tool_name, None)
        duration_ms = int((time.time() - started_at) * 1000) if started_at else None
        self._queue.put(
            ("tool_result", {
                "name": tool_name,
                "success": success,
                "summary": summary,
                "duration_ms": duration_ms,
            })
        )
        if hasattr(self._original, "print_tool_result_summary"):
            self._original.print_tool_result_summary(tool_name, success, summary)

    def __getattr__(self, name):
        """Delegate all other calls to original formatter."""
        return getattr(self._original, name)


def _save_conversation(session_id: str, question: str, response_text: str,
                       model: str, input_tokens: int, output_tokens: int,
                       tool_calls_data: list):
    """Save conversation through bluearch-core storage."""
    try:
        from datetime import datetime

        try:
            conv = get_storage_payload("tag-manager", "chat-conversations", session_id)
        except CoreRuntimeError:
            conv = {}

        title = conv.get("title") or question[:60].strip()
        if not conv.get("title") and len(question) > 60:
            title += "..."
        now = datetime.utcnow().isoformat()
        conv_payload = {
            **conv,
            "id": session_id,
            "title": title,
            "model": model,
            "message_count": (conv.get("message_count") or 0) + 2,
            "total_input_tokens": (conv.get("total_input_tokens") or 0) + input_tokens,
            "total_output_tokens": (conv.get("total_output_tokens") or 0) + output_tokens,
            "updated_at": now,
        }
        if not conv_payload.get("created_at"):
            conv_payload["created_at"] = now
        update_storage_payload("tag-manager", "chat-conversations", session_id, conv_payload)
        create_storage_payload(
            "tag-manager",
            "chat-messages",
            {
                "id": str(uuid.uuid4()),
                "conversation_id": session_id,
                "role": "user",
                "content": question,
                "created_at": now,
            },
        )
        create_storage_payload(
            "tag-manager",
            "chat-messages",
            {
                "id": str(uuid.uuid4()),
                "conversation_id": session_id,
                "role": "assistant",
                "content": response_text,
                "tool_calls": json.dumps(tool_calls_data) if tool_calls_data else None,
                "tokens": json.dumps({"input": input_tokens, "output": output_tokens}),
                "created_at": datetime.utcnow().isoformat(),
            },
        )
    except Exception:
        pass  # Don't break chat on DB errors


async def _stream_sse(
    assistant, question: str, session_id: str, selected_model: str
) -> AsyncGenerator[str, None]:
    """Convert sync ask_stream() generator to SSE async generator via thread+queue."""
    q: queue.Queue = queue.Queue()
    done_sentinel = object()
    accumulated_text = []
    tool_calls_data = []

    def _run_stream():
        # Wrap formatter to capture tool calls
        original_formatter = assistant.formatter
        assistant.formatter = ToolCallCapture(original_formatter, q)

        try:
            for chunk in assistant.ask_stream(question):
                q.put(("text", chunk))
                accumulated_text.append(chunk)

            # Extract suggestions from complete response
            full_text = "".join(accumulated_text)
            suggestions = _extract_suggestions(full_text)
            if suggestions:
                q.put(("suggestions", suggestions))

            q.put(
                (
                    "done",
                    {
                        "session_id": session_id,
                        "conversation_id": session_id,
                        "selected_model": selected_model,
                        "input_tokens": assistant.total_input_tokens,
                        "output_tokens": assistant.total_output_tokens,
                    },
                )
            )

            # Save to database (non-blocking, best effort)
            _save_conversation(
                session_id, question, full_text, selected_model,
                assistant.total_input_tokens, assistant.total_output_tokens,
                tool_calls_data,
            )
        except Exception as exc:
            q.put(("error", str(exc)))
        finally:
            # Restore original formatter
            assistant.formatter = original_formatter
            q.put(done_sentinel)

    thread = threading.Thread(target=_run_stream, daemon=True)
    thread.start()

    while True:
        item = await asyncio.to_thread(q.get, timeout=300)
        if item is done_sentinel:
            break
        event_type, data = item
        # Collect tool call data for persistence
        if event_type == "tool_call":
            tool_calls_data.append({"name": data["name"], "type": "call"})
        elif event_type == "tool_result":
            tool_calls_data.append({
                "name": data["name"],
                "type": "result",
                "success": data.get("success"),
                "summary": data.get("summary", ""),
                "duration_ms": data.get("duration_ms"),
            })
        yield f"data: {json.dumps({'type': event_type, 'content': data})}\n\n"

    yield "data: [DONE]\n\n"


@router.post("/chat")
async def chat_stream(body: ChatRequest, _user: LocalUser = Depends(get_current_user)):
    """Chat with AI assistant via SSE streaming."""
    # Resolve model: "auto" uses classifier, otherwise use specified model
    selected_model = body.model
    if body.model == "auto":
        selected_model = _classify_query_complexity(body.question)

    try:
        session_id, assistant = _get_or_create_session(body.session_id, selected_model)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to initialize AI assistant: {exc}",
        )

    return StreamingResponse(
        _stream_sse(assistant, body.question, session_id, selected_model),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/question", response_model=ChatResponse)
async def ask_question(body: QuestionRequest, _user: LocalUser = Depends(get_current_user)):
    """Ask a single question (non-streaming)."""

    def _ask_sync():
        from ...integrations.aws_assistant import BedrockAWSAssistant

        model_alias = body.model if body.model in MODELS else "haiku"
        assistant = BedrockAWSAssistant(model_id=model_alias)
        answer = assistant.ask(body.question)
        return answer, {
            "input_tokens": assistant.total_input_tokens,
            "output_tokens": assistant.total_output_tokens,
        }

    try:
        answer, tokens = await asyncio.to_thread(_ask_sync)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"AI assistant error: {exc}",
        )

    return ChatResponse(
        answer=answer,
        session_id=str(uuid.uuid4()),
        model=body.model,
        tokens=tokens,
    )


@router.get("/models", response_model=ModelsResponse)
async def list_models(_user: LocalUser = Depends(get_current_user)):
    """List available AI models."""
    models = [
        ModelInfo(alias=alias, model_id=alias, description=info["description"])
        for alias, info in MODELS.items()
    ]
    return ModelsResponse(models=models, default="auto")


# --- Conversation persistence endpoints ---

@router.get("/conversations")
async def list_conversations(current_user: LocalUser = Depends(get_current_user)):
    """List recent conversations."""
    def _query():
        convs = list_storage_payloads(
            "tag-manager",
            "chat-conversations",
            limit=50,
            order_by="updated_at",
            descending=True,
        )
        return [
            ConversationSummary(
                id=c["id"],
                title=c.get("title") or "Untitled conversation",
                model=c.get("model") or "auto",
                message_count=c.get("message_count") or 0,
                updated_at=c.get("updated_at") or c.get("created_at") or "",
            ).dict()
            for c in convs
            if c.get("id")
        ]

    try:
        result = await asyncio.to_thread(_query)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


    return result


@router.get("/conversations/{conversation_id}/messages")
async def get_conversation_messages(
    conversation_id: str,
    _user: LocalUser = Depends(get_current_user),
):
    """Get messages for a conversation."""
    def _query():
        msgs = list_storage_payloads(
            "tag-manager",
            "chat-messages",
            limit=10000,
            filters=[("conversation_id", conversation_id)],
            order_by="created_at",
            descending=False,
        )
        return [
            {
                "id": m.get("id"),
                "role": m.get("role"),
                "content": m.get("content"),
                "tool_calls": json.loads(m["tool_calls"]) if m.get("tool_calls") else None,
                "tokens": json.loads(m["tokens"]) if m.get("tokens") else None,
                "created_at": m.get("created_at") or "",
            }
            for m in msgs
        ]

    try:
        return await asyncio.to_thread(_query)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    _user: LocalUser = Depends(get_current_user),
):
    """Delete a conversation and its messages."""
    def _delete():
        msgs = list_storage_payloads(
            "tag-manager",
            "chat-messages",
            limit=10000,
            filters=[("conversation_id", conversation_id)],
        )
        for msg in msgs:
            if msg.get("id"):
                delete_storage_payload("tag-manager", "chat-messages", msg["id"])
        delete_storage_payload("tag-manager", "chat-conversations", conversation_id)
        return {"success": True}

    try:
        return await asyncio.to_thread(_delete)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
