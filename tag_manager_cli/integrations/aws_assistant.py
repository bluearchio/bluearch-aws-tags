"""AI-powered AWS assistant using Bedrock with custom AWS tools."""

import json
from typing import Dict, Any, List, Optional
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown

from ..utils.aws_auth import aws_auth
from .aws_tools import AWSTools, execute_tool
from .output_formatter import AIOutputFormatter


console = Console()


class BedrockAWSAssistant:
    """AI assistant that uses Bedrock Claude models to answer AWS questions."""

    def __init__(self, model_id: Optional[str] = None, region: str = "us-east-1"):
        """
        Initialize Bedrock AWS Assistant.

        Args:
            model_id: Bedrock inference profile ID. If None, uses latest Haiku (cheapest).
                Options:
                - None (auto-detects latest Haiku - recommended, cheapest)
                - "haiku" (latest Haiku version)
                - "sonnet" (latest Sonnet version)
                - "opus" (latest Opus version)
                - Specific model ID (e.g., us.anthropic.claude-3-5-sonnet-20241022-v2:0)
            region: AWS region for Bedrock (default: us-east-1)
        """
        self.region = region

        # Resolve model ID - support shortcuts and auto-detection
        if model_id is None or (isinstance(model_id, str) and model_id.lower() == "haiku"):
            from .model_resolver import get_latest_haiku
            self.model_id = get_latest_haiku(region)
        elif isinstance(model_id, str) and model_id.lower() == "sonnet":
            from .model_resolver import get_latest_sonnet
            self.model_id = get_latest_sonnet(region)
        elif isinstance(model_id, str) and model_id.lower() == "opus":
            from .model_resolver import get_latest_opus
            self.model_id = get_latest_opus(region)
        else:
            self.model_id = model_id

        self.bedrock_client = None
        self.conversation_history = []
        self.tools = AWSTools()
        self.formatter = AIOutputFormatter(console)

        # Custom system prompt (can be overridden for specialized wizards)
        self.custom_system_prompt = None

        # Suggestions toggle (ON by default)
        self.suggestions_enabled = True

        # Last suggested prompts for shortcuts (1, 2, 3)
        self.last_suggestions = []

        # Session statistics
        self.session_start_time = None
        self.questions_asked = 0
        self.tools_used = {}  # tool_name -> count
        self.total_input_tokens = 0
        self.total_output_tokens = 0

    def _get_bedrock_client(self):
        """Get or create Bedrock runtime client."""
        if not self.bedrock_client:
            self.bedrock_client = aws_auth.get_client('bedrock-runtime', region=self.region)
        return self.bedrock_client

    def _get_system_prompt(self) -> List[Dict[str, Any]]:
        """Get the system prompt (custom or default) with caching."""
        if self.custom_system_prompt:
            return [
                {"text": self.custom_system_prompt},
                {"cachePoint": {"type": "default"}}
            ]
        # Default system prompt
        base_prompt = [
            {
                "text": """You are an AWS infrastructure assistant. You have access to tools that query the user's AWS account using their existing SSO authentication.

When answering questions:
1. Use the available tools to get real-time information from their AWS account
2. Provide clear, concise answers with specific details
3. Format data in readable tables or lists when appropriate
4. If you need to make multiple tool calls to answer a question, do so
5. Always cite the tool results you're using

Available context:
- The user has AWS SSO authentication already configured
- You can query any region they have access to
- Resource discovery may not be complete - use live API calls when possible
- Cost data requires Cost Explorer API permissions

CROSS-ACCOUNT QUERIES - IMPORTANT:
The user may have multiple AWS accounts in their organization. For queries that could benefit from multi-account data (cost analysis, resource inventory, compliance checks), follow these rules:

1. WHEN TO ASK THE USER about account scope:
   - Cost analysis questions (e.g., "What are my top services?", "Show my costs")
   - Resource inventory questions (e.g., "List all EC2 instances", "Show my S3 buckets")
   - Compliance checks (e.g., "What resources are untagged?")

2. WHEN NOT TO ASK (just proceed):
   - User explicitly says "all accounts" or "across accounts"
   - User mentions a specific account name (use list_available_accounts to find the ID)
   - User says "current account only" or "this account"
   - Simple questions that don't need multi-account context

3. HOW TO ASK the user:
   First call list_available_accounts to see what's available, then present options like:
   "I can run this query for:
   1. Current account only (ACCOUNT_ID - ACCOUNT_NAME)
   2. Specific accounts (let me know which ones)
   3. All N enabled accounts

   Which would you prefer?"

4. SCOPE PERSISTENCE:
   - Use set_account_scope to remember the user's choice for the session
   - Once set, mention the current scope briefly on subsequent queries
   - Use get_current_account_scope to check what's currently set

5. AVAILABLE TOOLS for cross-account:
   - list_available_accounts: Get account IDs with names
   - set_account_scope: Set session-wide scope (current/all/specific)
   - get_current_account_scope: Check current scope setting
   - query_cur_costs: Supports account_ids parameter for filtering

For TAG COMPLIANCE questions, use these tools:
- get_tag_compliance_summary: Overall compliance stats (rate, counts, required tags)
- get_tag_compliance_by_service: Which services have the most untagged resources
- get_high_risk_untagged_resources: Non-compliant resources with risk levels
- find_untagged_resources: Simple list of resources missing specific tags

For CLOUDWATCH ALARMS:
- suggest_cloudwatch_alarms: Get alarm suggestions for a resource
- list_managed_alarms: List alarms created by tag-manager
- get_alarm_templates: View available alarm templates
- create_cloudwatch_alarm: CREATE alarms (requires user confirmation!)

When creating alarms: ALWAYS preview first (preview_only=true), show to user, get confirmation, then create.

CLI SELF-AWARENESS:
You can also help users with the tag-manager CLI itself:
- Use run_tag_manager_command to execute CLI operations (discover, tags scan, cost commands, etc.)
- Use get_cli_help for documentation, usage examples, and troubleshooting

When a user asks about CLI usage or commands:
1. Use get_cli_help to get relevant documentation
2. Explain the command and its options
3. Offer to run it for them: "Would you like me to run this command for you?"

Quick CLI reference:
- discover: Find AWS resources
- tags scan: Find untagged resources
- cost summary/services/ec2/s3/rds/lambda: Cost analysis
- setup validate: Check configuration
- ask chat: This interactive mode"""
            },
            {"cachePoint": {"type": "default"}}
        ]

        # Add follow-up suggestions if enabled
        if self.suggestions_enabled:
            base_prompt[0]["text"] += """

FOLLOW-UP SUGGESTIONS - IMPORTANT:
After answering each user question, ALWAYS suggest 2-3 related follow-up questions that would help them gain deeper insights. Format them as:

---
**Related questions you might find useful:**
- [Follow-up question 1]
- [Follow-up question 2]
- [Follow-up question 3]
---

Guidelines for suggestions:
1. Make them CONTEXTUAL to what was just discussed
2. Progress from current insight to deeper analysis
3. Cover different angles: cost, compliance, optimization, comparison

Example progression patterns:
- Cost query -> Suggest: trends, anomalies, optimization opportunities
- Resource list -> Suggest: cost analysis, compliance check, utilization metrics
- Compliance check -> Suggest: specific violations, remediation, historical trends
- Single account -> Suggest: cross-account comparison, account breakdown
- EC2 instances -> Suggest: cost breakdown, Reserved Instance coverage, utilization
- S3 buckets -> Suggest: storage class optimization, lifecycle policies, access patterns
- Untagged resources -> Suggest: cost impact, team accountability, compliance trends"""

        return base_prompt

    def _convert_tools_to_bedrock_format(self, use_cache: bool = True) -> List[Dict[str, Any]]:
        """Convert AWS tool schemas to Bedrock tool format with optional caching.

        Args:
            use_cache: Enable prompt caching for tool definitions (reduces costs by ~90%)
        """
        aws_tools = self.tools.get_tools_schema()
        bedrock_tools = []

        for tool in aws_tools:
            bedrock_tools.append({
                "toolSpec": {
                    "name": tool["name"],
                    "description": tool["description"],
                    "inputSchema": {
                        "json": tool["input_schema"]
                    }
                }
            })

        # Add cache point AFTER all tools (as a separate item in the array)
        # This caches all tool definitions, reducing input tokens by 90% on subsequent calls
        if use_cache:
            bedrock_tools.append({
                "cachePoint": {"type": "default"}
            })

        return bedrock_tools

    def ask(self, question: str, max_turns: int = 5) -> str:
        """
        Ask a question about your AWS account.

        Args:
            question: Natural language question about AWS
            max_turns: Maximum conversation turns (for tool use loops)

        Returns:
            Answer from the AI assistant
        """
        client = self._get_bedrock_client()

        # Add user message to conversation
        self.conversation_history.append({
            "role": "user",
            "content": [{"text": question}]
        })

        # Get system prompt (custom or default) with caching
        system_prompt = self._get_system_prompt()

        # Agentic loop: allow multiple tool use turns
        for turn in range(max_turns):
            try:
                # Build request parameters
                request_params = {
                    "modelId": self.model_id,
                    "messages": self.conversation_history,
                    "system": system_prompt,
                    "toolConfig": {
                        "tools": self._convert_tools_to_bedrock_format(use_cache=True)
                    }
                }

                # Add performance config only for supported models (Sonnet, Opus)
                # Haiku doesn't support latency optimization
                if "sonnet" in self.model_id.lower() or "opus" in self.model_id.lower():
                    request_params["performanceConfig"] = {"latency": "optimized"}

                # Call Bedrock Converse API
                response = client.converse(**request_params)

                # Extract response
                stop_reason = response['stopReason']
                assistant_message = response['output']['message']

                # Track token usage including cache metrics
                usage = response.get('usage', {})
                self.total_input_tokens += usage.get('inputTokens', 0)
                self.total_output_tokens += usage.get('outputTokens', 0)

                # Track cache performance (90% cost reduction on cached tokens)
                cache_read = usage.get('cacheReadInputTokens', 0)
                if cache_read > 0:
                    console.print(f"[dim]Cache hit: {cache_read} tokens (90% cost savings)[/dim]")

                # Validate and add assistant response to history
                # Filter out any malformed tool uses (missing input)
                validated_content = []
                for content in assistant_message['content']:
                    if 'toolUse' in content:
                        tool_use = content['toolUse']
                        # Only add tool use if it has valid input
                        if 'input' in tool_use and tool_use['input'] is not None:
                            validated_content.append(content)
                        else:
                            console.print(f"[yellow]Warning: Skipping tool {tool_use.get('name', 'unknown')} with missing input[/yellow]")
                    else:
                        validated_content.append(content)

                # Add validated assistant message to history
                self.conversation_history.append({
                    "role": "assistant",
                    "content": validated_content
                })

                # Check if we're done
                if stop_reason == 'end_turn':
                    # Extract text response
                    for content in assistant_message['content']:
                        if 'text' in content:
                            return content['text']
                    return "No response generated."

                # Handle tool use
                elif stop_reason == 'tool_use':
                    # Execute all requested tools
                    tool_results = []

                    for content in assistant_message['content']:
                        if 'toolUse' in content:
                            tool_use = content['toolUse']
                            tool_name = tool_use['name']
                            tool_input = tool_use['input']
                            tool_use_id = tool_use['toolUseId']

                            # Track tool usage
                            self.tools_used[tool_name] = self.tools_used.get(tool_name, 0) + 1

                            console.print(f"[dim]Calling tool: {tool_name}[/dim]")

                            # Check tool result cache for read-only tools
                            _write_tools = {"create_cloudwatch_alarm", "set_account_scope"}
                            cached_result = None
                            cache_key_str = None
                            if tool_name not in _write_tools:
                                try:
                                    from ..utils.local_cache import cache_manager
                                    cache_key_str = f"tool_cache:{tool_name}:{json.dumps(tool_input, sort_keys=True)}"
                                    cached_result = cache_manager.get(cache_key_str)
                                except Exception:
                                    pass

                            if cached_result is not None:
                                result = cached_result
                                console.print(f"[dim](cached)[/dim]")
                            else:
                                # Execute the tool
                                result = execute_tool(tool_name, tool_input)
                                # Cache the result with 60s TTL
                                if cache_key_str is not None:
                                    try:
                                        from ..utils.local_cache import cache_manager
                                        cache_manager.set(cache_key_str, result, ttl=60)
                                    except Exception:
                                        pass

                            # Add result to response (correct Bedrock format)
                            tool_results.append({
                                "toolResult": {
                                    "toolUseId": tool_use_id,
                                    "content": [{"json": result}]
                                }
                            })

                    # Add tool results to conversation (only if we have results)
                    if tool_results:
                        self.conversation_history.append({
                            "role": "user",
                            "content": tool_results
                        })
                        # Continue the loop for next turn
                        continue
                    else:
                        # No valid tool results - can't continue
                        console.print("[yellow]Warning: No valid tool calls executed[/yellow]")
                        return "I encountered an issue executing the required tools. Please try rephrasing your question."

                else:
                    return f"Unexpected stop reason: {stop_reason}"

            except Exception as e:
                import time
                from botocore.exceptions import ClientError

                error_msg = str(e)

                # Handle specific Bedrock exceptions with appropriate actions
                if isinstance(e, ClientError):
                    error_code = e.response.get('Error', {}).get('Code', '')

                    # Throttling - retry with exponential backoff
                    if error_code == 'ThrottlingException':
                        if turn < max_turns - 1:
                            wait_time = 2 ** turn  # Exponential backoff: 1s, 2s, 4s
                            console.print(f"[yellow]Rate limited. Retrying in {wait_time}s...[/yellow]")
                            time.sleep(wait_time)
                            continue
                        else:
                            console.print("[red]Rate limit exceeded. Please try again later.[/red]")
                            return "Request rate limit exceeded. Please wait a moment and try again."

                    # Model timeout - suggest simplifying question
                    elif error_code == 'ModelTimeoutException':
                        console.print("[red]Model inference timed out.[/red]")
                        console.print("[yellow]Tip: Try breaking your question into smaller parts.[/yellow]")
                        return "The model took too long to respond. Please try a simpler question."

                    # Service unavailable - retry once
                    elif error_code == 'ServiceUnavailableException':
                        if turn < max_turns - 1:
                            console.print("[yellow]Service temporarily unavailable. Retrying...[/yellow]")
                            time.sleep(2)
                            continue
                        else:
                            return "Bedrock service is temporarily unavailable. Please try again in a moment."

                    # Model not ready - explain waiting period
                    elif error_code == 'ModelNotReadyException':
                        console.print("[red]Model is not ready yet.[/red]")
                        console.print("[yellow]This usually happens right after enabling model access.[/yellow]")
                        console.print("[yellow]Wait 1-2 minutes and try again.[/yellow]")
                        return "Model is initializing. Please wait a moment and try again."

                # Check if it's a ResourceNotFoundException for model access
                if "ResourceNotFoundException" in error_msg and "use case details" in error_msg:
                    console.print("[red]Model access not enabled![/red]\n")
                    self._guide_user_to_enable_access()
                    return "Bedrock model access needs to be enabled. Please follow the instructions above."

                # Check if it's an AccessDeniedException
                elif "AccessDeniedException" in error_msg or "is not authorized" in error_msg:
                    console.print(f"[red]Permission denied![/red]\n")
                    console.print("[yellow]Your IAM role needs these permissions:[/yellow]")
                    console.print("  - bedrock:InvokeModel")
                    console.print("  - bedrock:InvokeModelWithResponseStream\n")
                    console.print("[yellow]Add these to your AWS SSO role and try again.[/yellow]")
                    return "IAM permissions required. Please update your role permissions."

                # Other errors
                console.print(f"[red]Error calling Bedrock: {e}[/red]")
                return f"Error: {str(e)}"

        return "Maximum conversation turns reached. Please refine your question."

    def ask_stream(self, question: str, max_turns: int = 5):
        """
        Ask a question with streaming response (better UX for long responses).

        Args:
            question: Natural language question about AWS
            max_turns: Maximum conversation turns (for tool use loops)

        Yields:
            Text chunks as they're generated by the model
        """
        client = self._get_bedrock_client()

        # Add user message to conversation
        self.conversation_history.append({
            "role": "user",
            "content": [{"text": question}]
        })

        # Get system prompt (custom or default) with caching
        system_prompt = self._get_system_prompt()

        # Agentic loop with streaming
        for turn in range(max_turns):
            try:
                # Build request parameters
                stream_params = {
                    "modelId": self.model_id,
                    "messages": self.conversation_history,
                    "system": system_prompt,
                    "toolConfig": {
                        "tools": self._convert_tools_to_bedrock_format(use_cache=True)
                    }
                }

                # Add performance config only for supported models (Sonnet, Opus)
                # Haiku doesn't support latency optimization
                if "sonnet" in self.model_id.lower() or "opus" in self.model_id.lower():
                    stream_params["performanceConfig"] = {"latency": "optimized"}

                # Call Bedrock Converse Stream API
                response = client.converse_stream(**stream_params)

                # Process streaming response
                stop_reason = None
                assistant_content = []
                current_text = ""
                current_tool_use = None
                current_tool_input_json = ""  # Accumulate tool input JSON string

                for event in response['stream']:
                    # Content block start
                    if 'contentBlockStart' in event:
                        block_start = event['contentBlockStart']
                        if 'toolUse' in block_start.get('start', {}):
                            tool_use_start = block_start['start']['toolUse']
                            # Tool call will be displayed once we have the input
                            # Initialize tool use tracking - don't pre-initialize input
                            current_tool_use = {
                                'toolUseId': tool_use_start['toolUseId'],
                                'name': tool_use_start['name']
                                # Input will be accumulated from string deltas
                            }
                            current_tool_input_json = ""  # Reset for new tool

                    # Content block delta (streaming text or tool input)
                    elif 'contentBlockDelta' in event:
                        delta = event['contentBlockDelta']['delta']
                        if 'text' in delta:
                            chunk = delta['text']
                            current_text += chunk
                            yield chunk
                        elif 'toolUse' in delta:
                            # Accumulate tool input (comes as string chunks in streaming)
                            if current_tool_use and 'input' in delta['toolUse']:
                                tool_input = delta['toolUse']['input']
                                # Input comes as string chunks - accumulate them
                                if isinstance(tool_input, str):
                                    current_tool_input_json += tool_input
                                elif isinstance(tool_input, dict):
                                    # Sometimes comes as complete dict
                                    current_tool_use['input'] = tool_input

                    # Content block stop
                    elif 'contentBlockStop' in event:
                        if current_text:
                            assistant_content.append({"text": current_text})
                            current_text = ""
                        elif current_tool_use:
                            # Parse accumulated tool input JSON if we have it
                            if current_tool_input_json and 'input' not in current_tool_use:
                                try:
                                    import json
                                    current_tool_use['input'] = json.loads(current_tool_input_json)
                                except json.JSONDecodeError as e:
                                    console.print(f"[yellow]Warning: Failed to parse tool input JSON: {e}[/yellow]")

                            # If no input was provided, default to empty dict (for tools with no required params)
                            if 'input' not in current_tool_use:
                                current_tool_use['input'] = {}

                            # Validate tool use has valid input before adding
                            if isinstance(current_tool_use.get('input'), dict):
                                # Display tool call with formatted input
                                self.formatter.print_tool_call(
                                    current_tool_use['name'],
                                    current_tool_use.get('input', {})
                                )
                                assistant_content.append({"toolUse": current_tool_use})
                            else:
                                self.formatter.print_warning(f"Tool {current_tool_use.get('name')} has invalid input type, skipping")
                            current_tool_use = None
                            current_tool_input_json = ""

                    # Metadata with usage
                    elif 'metadata' in event:
                        metadata = event['metadata']
                        usage = metadata.get('usage', {})
                        self.total_input_tokens += usage.get('inputTokens', 0)
                        self.total_output_tokens += usage.get('outputTokens', 0)

                        # Track cache hits
                        cache_read = usage.get('cacheReadInputTokens', 0)
                        if cache_read > 0:
                            console.print(f"\n[dim]Cache hit: {cache_read} tokens (90% savings)[/dim]")

                    # Message stop
                    elif 'messageStop' in event:
                        stop_reason = event['messageStop']['stopReason']

                # Build assistant message for history (only if there's valid content)
                if assistant_content:
                    assistant_message = {
                        "role": "assistant",
                        "content": assistant_content
                    }
                    self.conversation_history.append(assistant_message)
                else:
                    self.formatter.print_warning("No valid content in assistant response")

                # If we're done, exit
                if stop_reason == 'end_turn':
                    return

                # Handle tool use (non-streaming for tool execution)
                elif stop_reason == 'tool_use':
                    # Execute tools and add results
                    tool_results = []
                    for content in assistant_content:
                        if 'toolUse' in content:
                            tool_use = content['toolUse']
                            tool_name = tool_use['name']
                            tool_input = tool_use['input']
                            tool_use_id = tool_use['toolUseId']

                            # Track tool usage
                            self.tools_used[tool_name] = self.tools_used.get(tool_name, 0) + 1

                            # Check tool result cache for read-only tools
                            _write_tools = {"create_cloudwatch_alarm", "set_account_scope"}
                            cached_result = None
                            cache_key_str = None
                            if tool_name not in _write_tools:
                                try:
                                    from ..utils.local_cache import cache_manager
                                    cache_key_str = f"tool_cache:{tool_name}:{json.dumps(tool_input, sort_keys=True)}"
                                    cached_result = cache_manager.get(cache_key_str)
                                except Exception:
                                    pass

                            if cached_result is not None:
                                result = cached_result
                            else:
                                result = execute_tool(tool_name, tool_input)
                                if cache_key_str is not None:
                                    try:
                                        from ..utils.local_cache import cache_manager
                                        cache_manager.set(cache_key_str, result, ttl=60)
                                    except Exception:
                                        pass

                            tool_results.append({
                                "toolResult": {
                                    "toolUseId": tool_use_id,
                                    "content": [{"json": result}]
                                }
                            })

                    # Add tool results to conversation (only if we have results)
                    if tool_results:
                        self.conversation_history.append({
                            "role": "user",
                            "content": tool_results
                        })
                        # Continue loop for next turn
                        continue
                    else:
                        # No valid tool results - can't continue
                        self.formatter.print_warning("No valid tool calls executed")
                        return

            except Exception as e:
                import time
                from botocore.exceptions import ClientError

                error_msg = str(e)

                # Handle Bedrock exceptions with retries (same as non-streaming)
                if isinstance(e, ClientError):
                    error_code = e.response.get('Error', {}).get('Code', '')

                    if error_code == 'ValidationException':
                        # Validation error - likely malformed conversation history
                        console.print("\n[yellow]Validation error detected. Clearing conversation history...[/yellow]")
                        self.reset_conversation()
                        yield "\n\nI encountered an error with the conversation history. I've reset it. Please try your question again."
                        return

                    if error_code == 'ThrottlingException' and turn < max_turns - 1:
                        wait_time = 2 ** turn
                        console.print(f"\n[yellow]Rate limited. Retrying in {wait_time}s...[/yellow]")
                        time.sleep(wait_time)
                        continue

                    elif error_code == 'ModelTimeoutException':
                        yield "\n\n[ERROR] Model inference timed out. Please try a simpler question."
                        return

                    elif error_code == 'ServiceUnavailableException' and turn < max_turns - 1:
                        console.print("\n[yellow]Service temporarily unavailable. Retrying...[/yellow]")
                        time.sleep(2)
                        continue

                # Handle access errors
                if "ResourceNotFoundException" in error_msg and "use case details" in error_msg:
                    console.print("\n[red]Model access not enabled![/red]\n")
                    self._guide_user_to_enable_access()
                    return

                elif "AccessDeniedException" in error_msg:
                    console.print("\n[red]Permission denied! Add bedrock:InvokeModel to your IAM role.[/red]")
                    return

                # Other errors
                yield f"\n\n[ERROR] {error_msg}"
                return

        yield "\n\nMaximum conversation turns reached. Please refine your question."

    def _enable_model_access_programmatically(self, model_id: str) -> bool:
        """
        Attempt to programmatically enable model access.

        Args:
            model_id: The model ID to enable (e.g., 'anthropic.claude-3-5-sonnet-20241022-v2:0')

        Returns:
            True if successful, False otherwise
        """
        from botocore.exceptions import ClientError
        from rich.progress import Progress, SpinnerColumn, TextColumn
        from rich.panel import Panel

        try:
            bedrock = aws_auth.get_client('bedrock', region=self.region)

            # Extract base model ID (remove inference profile prefix if present)
            base_model_id = model_id.replace('us.', '').replace('eu.', '')

            console.print(f"[cyan]Enabling access for {base_model_id}...[/cyan]\n")

            # Use progress with spinner
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
                transient=False
            ) as progress:

                # Step 1: List available agreement offers
                task1 = progress.add_task("[cyan]Checking license agreements...", total=None)

                try:
                    offers_response = bedrock.list_foundation_model_agreement_offers(
                        modelId=base_model_id
                    )

                    offers = offers_response.get('modelAgreementOffers', [])
                    if offers:
                        offer_token = offers[0].get('offerToken')
                        if offer_token:
                            progress.update(task1, description="[green]License agreement found")
                            progress.stop_task(task1)

                            # Step 2: Create foundation model agreement
                            task2 = progress.add_task("[cyan]Accepting license agreement...", total=None)
                            bedrock.create_foundation_model_agreement(
                                modelId=base_model_id,
                                offerToken=offer_token
                            )
                            progress.update(task2, description="[green]License agreement accepted")
                            progress.stop_task(task2)
                        else:
                            progress.update(task1, description="[yellow]No offer token (skipping)")
                            progress.stop_task(task1)
                    else:
                        progress.update(task1, description="[yellow]Agreement already exists (skipping)")
                        progress.stop_task(task1)

                except ClientError as e:
                    error_code = e.response.get('Error', {}).get('Code', '')

                    # Agreement might already exist - that's okay, continue
                    if error_code in ['ConflictException', 'ResourceNotFoundException']:
                        progress.update(task1, description=f"[yellow]{error_code} (continuing)")
                        progress.stop_task(task1)
                    else:
                        raise

                # Step 3: Submit use case (required for Anthropic)
                task3 = progress.add_task("[cyan]Submitting use case details...", total=None)
                import json

                form_data = {
                    "companyName": "CLI User",
                    "companyWebsite": "www.example.com",
                    "intendedUsers": "0",  # 0 for internal use
                    "industryOption": "Technology",
                    "otherIndustryOption": "",
                    "useCases": "AWS infrastructure management and analysis CLI tool for querying resources, cost analysis, and compliance checking"
                }

                bedrock.put_use_case_for_model_access(
                    formData=json.dumps(form_data).encode('utf-8')
                )
                progress.update(task3, description="[green]Use case approved")
                progress.stop_task(task3)

            # Show success message
            console.print()
            success_panel = Panel(
                "[bold green]Success! Model access enabled[/bold green]\n\n"
                "[cyan]What you can do now:[/cyan]\n\n"
                "  [green]Ask questions:[/green]\n"
                "  • \"How many EC2 instances are running?\"\n"
                "  • \"Show me last month's AWS costs\"\n"
                "  • \"Which S3 buckets are untagged?\"\n\n"
                "  [green]Start interactive chat:[/green]\n"
                "  $ tag-manager ask chat\n\n"
                "  [green]See available models:[/green]\n"
                "  $ tag-manager ask models\n\n"
                "[dim]Model is ready to use immediately![/dim]",
                title="[bold green]Ready to Go![/bold green]",
                border_style="green",
                padding=(1, 2)
            )
            console.print(success_panel)
            console.print()

            return True

        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            error_msg = e.response.get('Error', {}).get('Message', str(e))

            if error_code == 'AccessDeniedException':
                console.print("[red]Permission denied.[/red]")
                console.print("[yellow]Your IAM role needs these permissions:[/yellow]")
                console.print("  - bedrock:ListFoundationModelAgreementOffers")
                console.print("  - bedrock:CreateFoundationModelAgreement")
                console.print("  - bedrock:PutUseCaseForModelAccess\n")
            else:
                console.print(f"[red]Error: {error_msg}[/red]\n")

            return False

        except Exception as e:
            console.print(f"[red]Unexpected error: {str(e)}[/red]\n")
            return False

    def _guide_user_to_enable_access(self):
        """Automatically check access and guide user to enable Bedrock."""
        from botocore.exceptions import ClientError
        from rich.table import Table
        from rich.prompt import Confirm
        from rich.panel import Panel
        from .model_info import get_model_info, format_price

        try:
            # Try to get available models
            bedrock = aws_auth.get_client('bedrock', region=self.region)
            response = bedrock.list_foundation_models(byProvider='Anthropic')

            models = response.get('modelSummaries', [])
            active_models = [m for m in models if m.get('modelLifecycle', {}).get('status') == 'ACTIVE']

            if active_models:
                console.print(f"[cyan]Found {len(active_models)} active Anthropic models in {self.region}[/cyan]")
                console.print("[yellow]But model access needs to be enabled for your account.[/yellow]\n")
            else:
                console.print(f"[yellow]Bedrock is available in {self.region}[/yellow]\n")

        except Exception as e:
            console.print(f"[yellow]Could not check model availability: {e}[/yellow]\n")

        # Show detailed model information panel
        model_info = get_model_info(self.model_id)

        # Calculate typical cost estimate
        typical_input_tokens = 500
        typical_output_tokens = 200
        typical_cost = (typical_input_tokens / 1_000_000) * model_info.input_price + \
                      (typical_output_tokens / 1_000_000) * model_info.output_price

        info_panel = Panel(
            f"[bold cyan]Model:[/bold cyan]     {model_info.name}\n"
            f"[bold cyan]Provider:[/bold cyan]  {model_info.provider}\n"
            f"[bold cyan]Region:[/bold cyan]    {self.region}\n\n"
            f"[bold yellow]Pricing:[/bold yellow]\n"
            f"  Input:   {format_price(model_info.input_price)} per million tokens\n"
            f"  Output:  {format_price(model_info.output_price)} per million tokens\n"
            f"  [dim]Typical question: ~{format_price(typical_cost)}[/dim]\n\n"
            f"[bold green]What will happen:[/bold green]\n"
            f"  [green]1.[/green] Accept Anthropic license agreement\n"
            f"  [green]2.[/green] Submit use case to AWS\n"
            f"  [green]3.[/green] Enable model in your account\n"
            f"  [green]4.[/green] Ready to use in ~5 seconds\n\n"
            "[dim]This is a one-time setup per AWS account[/dim]",
            title="[bold cyan]Enable AWS Bedrock Model Access[/bold cyan]",
            border_style="cyan",
            padding=(1, 2)
        )
        console.print(info_panel)
        console.print()

        # Offer automatic enablement
        console.print("[bold cyan]Option 1: Automatic Setup (Recommended)[/bold cyan]")
        console.print("I can enable model access automatically for you.\n")

        try:
            if Confirm.ask("Continue with automatic setup?", default=True):
                console.print()
                success = self._enable_model_access_programmatically(self.model_id)
                if success:
                    return
        except Exception:
            # If confirm fails (non-interactive), fall through to manual instructions
            pass

        # Show manual setup instructions
        console.print("\n[bold cyan]Option 2: Manual Setup[/bold cyan]\n")
        console.print("1. Go to AWS Console > Bedrock > Model access")
        console.print("   URL: https://console.aws.amazon.com/bedrock/home?region={}#/modelaccess\n".format(self.region))
        console.print("2. Click [bold]'Modify model access'[/bold] button\n")
        console.print("3. Enable: [bold]Anthropic Claude 3.5 Sonnet[/bold]\n")
        console.print("4. Fill out the use case form:")
        console.print("   [dim]Description: AWS infrastructure management and analysis CLI tool[/dim]\n")
        console.print("5. Wait 2-15 minutes for activation\n")
        console.print("[green]For detailed instructions, run:[/green]")
        console.print("  [bold]tag-manager ask setup-bedrock[/bold]\n")
        console.print("[green]To verify access after enabling:[/green]")
        console.print("  [bold]tag-manager ask check-access[/bold]\n")

    def reset_conversation(self):
        """Clear conversation history."""
        self.conversation_history = []
        console.print("[blue]Conversation history cleared.[/blue]")

    def interactive_mode(self):
        """Start interactive chat mode."""
        import time
        from .model_info import get_model_info, estimate_cost

        # Start session timer
        self.session_start_time = time.time()

        # Get model info for welcome panel
        model_info = get_model_info(self.model_id)
        typical_cost = estimate_cost(500, 200, self.model_id)

        # Enhanced welcome panel
        welcome_panel = Panel(
            f"[bold cyan]Model:[/bold cyan]    {model_info.name}\n"
            f"[bold cyan]Region:[/bold cyan]   {self.region}\n"
            f"[bold cyan]Cost:[/bold cyan]     ~${typical_cost:.4f} per question\n\n"
            f"[bold yellow]Read Tools (17):[/bold yellow]\n"
            f"  [dim]EC2 • S3 • Lambda • RDS • IAM • VPC • Compliance • Tags • Alarms[/dim]\n"
            f"  [bold green]CUR Costs[/bold green] [dim](detailed) • Cost Explorer (fallback) • AWS CLI[/dim]\n\n"
            f"[bold yellow]Write Tools (1):[/bold yellow] [dim]create_cloudwatch_alarm (requires confirmation)[/dim]\n\n"
            f"[bold green]Commands:[/bold green]\n"
            f"  [green]•[/green] 'exit' - End session\n"
            f"  [green]•[/green] 'reset' - Clear conversation history\n"
            f"  [green]•[/green] 'help' - Show example questions\n"
            f"  [green]•[/green] 'stats' - View session usage\n"
            f"  [green]•[/green] 'suggestions on/off' - Toggle follow-up suggestions\n"
            f"  [green]•[/green] 'prompts [category]' - Browse prompt library\n"
            f"  [green]•[/green] '1/2/3' - Select a suggested prompt\n\n"
            f"[dim]Tip: Follow-up suggestions are ON - type 1, 2, or 3 to quickly run them![/dim]",
            title="[bold cyan]AWS Assistant - Interactive Chat[/bold cyan]",
            border_style="cyan",
            padding=(1, 2)
        )
        console.print(welcome_panel)

        while True:
            try:
                # Get user input
                question = console.input("\n[bold green]You:[/bold green] ").strip()

                if not question:
                    continue

                # Handle commands
                if question.lower() in ['exit', 'quit', 'q']:
                    self._show_session_summary()
                    console.print("[yellow]Goodbye![/yellow]")
                    break

                if question.lower() == 'reset':
                    self.reset_conversation()
                    console.print("[blue]Conversation history cleared.[/blue]")
                    continue

                if question.lower() == 'help':
                    self._show_example_questions()
                    continue

                if question.lower() in ['stats', 'statistics']:
                    self._show_session_stats()
                    continue

                if question.lower() == 'suggestions on':
                    self.suggestions_enabled = True
                    console.print("[green]Prompt suggestions enabled.[/green]")
                    continue

                if question.lower() == 'suggestions off':
                    self.suggestions_enabled = False
                    console.print("[yellow]Prompt suggestions disabled.[/yellow]")
                    continue

                # Handle prompt shortcuts (1, 2, 3)
                if question in ['1', '2', '3']:
                    idx = int(question) - 1
                    if idx < len(self.last_suggestions):
                        question = self.last_suggestions[idx]
                        console.print(f"[dim]Running: {question}[/dim]")
                        # Fall through to process this as a question
                    else:
                        console.print("[yellow]No suggestion at that position. Ask a question first to get suggestions.[/yellow]")
                        continue

                # Handle prompts command
                if question.lower().startswith('prompts'):
                    self._show_prompts_library(question)
                    continue

                # Track question
                self.questions_asked += 1

                # Get response with streaming for better UX
                console.print("\n[bold cyan]Assistant:[/bold cyan] ")

                # Accumulate the streaming response while showing a subtle indicator
                accumulated_response = ""
                with console.status("[dim]Generating response...[/dim]", spinner="dots"):
                    for chunk in self.ask_stream(question):
                        accumulated_response += chunk

                # Format and print the complete response
                if accumulated_response.strip():
                    self.formatter.format_and_print(accumulated_response, streaming=False)
                    # Extract suggestions for shortcuts
                    self._extract_suggestions(accumulated_response)

                console.print()

            except KeyboardInterrupt:
                console.print("\n[yellow]Use 'exit' to quit.[/yellow]")
                continue
            except Exception as e:
                console.print(f"\n[red]Error: {e}[/red]")

    def _show_session_stats(self):
        """Show session statistics."""
        import time
        from rich.table import Table
        from .model_info import estimate_cost

        # Calculate session duration
        if self.session_start_time:
            duration = time.time() - self.session_start_time
            minutes = int(duration // 60)
            seconds = int(duration % 60)
            duration_str = f"{minutes}m {seconds}s"
        else:
            duration_str = "N/A"

        # Calculate estimated cost
        estimated_cost = estimate_cost(
            self.total_input_tokens,
            self.total_output_tokens,
            self.model_id
        )

        stats_panel = Panel(
            f"[bold green]Session Statistics[/bold green]\n\n"
            f"[cyan]Questions Asked:[/cyan]      {self.questions_asked}\n"
            f"[cyan]Total Tool Calls:[/cyan]     {sum(self.tools_used.values())}\n"
            f"[cyan]Session Duration:[/cyan]     {duration_str}\n\n"
            f"[yellow]Token Usage:[/yellow]\n"
            f"  Input:   {self.total_input_tokens:,}\n"
            f"  Output:  {self.total_output_tokens:,}\n"
            f"  Total:   {self.total_input_tokens + self.total_output_tokens:,}\n\n"
            f"[yellow]Estimated Cost:[/yellow]      ${estimated_cost:.4f}",
            title="[bold cyan]Session Stats[/bold cyan]",
            border_style="cyan",
            padding=(1, 2)
        )
        console.print(stats_panel)

        # Show tool breakdown if tools were used
        if self.tools_used:
            console.print()
            tool_table = Table(title="Tools Used")
            tool_table.add_column("Tool", style="cyan")
            tool_table.add_column("Count", style="green", justify="right")

            for tool_name, count in sorted(self.tools_used.items(), key=lambda x: x[1], reverse=True):
                tool_table.add_row(tool_name, str(count))

            console.print(tool_table)

    def _show_session_summary(self):
        """Show final session summary on exit."""
        import time
        from .model_info import estimate_cost

        if self.questions_asked == 0:
            return

        # Calculate session duration
        duration = time.time() - self.session_start_time if self.session_start_time else 0
        minutes = int(duration // 60)
        seconds = int(duration % 60)

        # Calculate estimated cost
        estimated_cost = estimate_cost(
            self.total_input_tokens,
            self.total_output_tokens,
            self.model_id
        )

        console.print()
        summary_panel = Panel(
            f"[bold cyan]Session Complete[/bold cyan]\n\n"
            f"Questions: {self.questions_asked}\n"
            f"Tools Used: {sum(self.tools_used.values())}\n"
            f"Duration: {minutes}m {seconds}s\n"
            f"Estimated Cost: ${estimated_cost:.4f}",
            border_style="cyan",
            padding=(0, 2)
        )
        console.print(summary_panel)

    def _show_example_questions(self):
        """Show example questions users can ask."""
        examples = """
## Example Questions

**Resource Discovery:**
- What EC2 instances are running?
- List all S3 buckets
- Show me Lambda functions in us-east-1
- What RDS databases do I have?

**Cost Analysis:**
- What were my costs last month?
- Show me costs by service for the last 30 days
- How much am I spending on EC2?

**Compliance & Tagging:**
- What's my tag compliance rate?
- Which services have the most untagged resources?
- Show me high-risk untagged resources
- Find EC2 instances missing the Environment tag

**CloudWatch Alarms:**
- What alarm templates are available for EC2?
- Suggest alarms for my RDS database
- List all alarms I've created
- Create a CPU alarm for instance i-1234567890 (will ask for confirmation)

**Security & IAM:**
- List all IAM users
- Which users have old access keys?

**Network:**
- Show me all VPCs
- What's in my default VPC?

**Account Summary:**
- Give me an overview of my AWS account
- How many resources do I have?

**Multi-Account Operations:**
- List all accounts in my organization
- How many accounts are enabled for cross-account access?
- Show me which OUs have been configured
        """
        console.print(Panel(Markdown(examples), border_style="blue"))

    def _extract_suggestions(self, response: str):
        """Extract follow-up suggestions from AI response for shortcuts."""
        import re

        self.last_suggestions = []

        # Look for the suggestions section
        # Pattern matches various formats after suggestion headers
        lines = response.split('\n')
        in_suggestions = False

        for line in lines:
            # Detect start of suggestions section (multiple patterns)
            lower_line = line.lower()
            if ('related questions' in lower_line or
                'you might find useful' in lower_line or
                'would you like me to' in lower_line or
                'would you like to' in lower_line):
                in_suggestions = True
                continue

            # Detect end of suggestions (empty line or new section)
            if in_suggestions:
                if line.strip() == '---' or line.strip() == '':
                    if self.last_suggestions:
                        break  # We have suggestions, stop
                    continue

                stripped = line.strip()
                suggestion = None

                # Extract from bullet points (-, *)
                if stripped.startswith('- ') or stripped.startswith('* '):
                    suggestion = stripped[2:].strip()
                # Extract from unicode bullets
                elif stripped.startswith('\u2022 '):  # bullet point
                    suggestion = stripped[2:].strip()
                # Extract from numbered lists (1, 2, 3 or 1., 2., 3.)
                elif re.match(r'^[1-3][.\s]', stripped):
                    suggestion = re.sub(r'^[1-3][.\s]+', '', stripped).strip()

                if suggestion:
                    # Remove quotes if present
                    suggestion = suggestion.strip('"').strip("'")
                    # Remove trailing annotations like "(optimization)"
                    suggestion = re.sub(r'\s*\([^)]+\)\s*$', '', suggestion)
                    # Clean up suggestion to be a question if it isn't
                    if suggestion and len(self.last_suggestions) < 3:
                        self.last_suggestions.append(suggestion)

        # If we found suggestions, show shortcuts hint
        if self.last_suggestions:
            console.print(f"[dim]Tip: Type 1, 2, or 3 to run a suggested prompt[/dim]")

    def _show_prompts_library(self, command: str):
        """Show prompts from the library by category."""
        from rich.table import Table

        parts = command.lower().split()
        category = parts[1] if len(parts) > 1 else None

        # Define prompt categories with examples
        prompts = {
            'cost': {
                'title': 'Cost Analysis & FinOps',
                'prompts': [
                    ("What are my top 5 most expensive services?", "Identify major cost drivers"),
                    ("Compare this month's costs to last month", "Month-over-month analysis"),
                    ("Show daily cost trends for the past week", "Daily spending patterns"),
                    ("Find EC2 instances with low CPU utilization", "Rightsizing opportunities"),
                    ("Show me unattached EBS volumes", "Waste identification"),
                    ("Which Lambda functions cost the most?", "Serverless cost analysis"),
                ]
            },
            'compliance': {
                'title': 'Tag Compliance',
                'prompts': [
                    ("What's my overall tag compliance rate?", "Compliance overview"),
                    ("Show me untagged EC2 instances", "Find violations"),
                    ("Which resources are missing the Environment tag?", "Check required tags"),
                    ("What's the cost impact of untagged resources?", "Quantify gaps"),
                    ("Show tag compliance by service", "Service breakdown"),
                ]
            },
            'infrastructure': {
                'title': 'Infrastructure Insights',
                'prompts': [
                    ("How many EC2 instances do I have by region?", "Regional distribution"),
                    ("List all RDS databases with their engines", "Database inventory"),
                    ("Show Lambda functions by runtime", "Runtime distribution"),
                    ("Which IAM users have old access keys?", "Security check"),
                    ("Show me all VPCs with their CIDR blocks", "Network inventory"),
                ]
            },
            'accounts': {
                'title': 'Cross-Account Analysis',
                'prompts': [
                    ("Show costs broken down by account", "Account-level spending"),
                    ("Which account is spending the most?", "Cost attribution"),
                    ("Show EC2 instances across all accounts", "Org-wide inventory"),
                    ("Which accounts have the most untagged resources?", "Compliance by account"),
                ]
            },
            'alarms': {
                'title': 'CloudWatch Alarms',
                'prompts': [
                    ("What alarm templates are available for EC2?", "Discover options"),
                    ("Suggest alarms for my RDS database", "Get recommendations"),
                    ("List all alarms I've created", "Alarm inventory"),
                ]
            }
        }

        if category and category in prompts:
            # Show specific category
            cat = prompts[category]
            table = Table(title=f"[bold cyan]{cat['title']}[/bold cyan]")
            table.add_column("Prompt", style="green")
            table.add_column("Use Case", style="dim")
            for prompt, use_case in cat['prompts']:
                table.add_row(f'"{prompt}"', use_case)
            console.print(table)
        elif category:
            console.print(f"[yellow]Unknown category: {category}[/yellow]")
            console.print(f"[dim]Available: {', '.join(prompts.keys())}[/dim]")
        else:
            # Show all categories
            console.print("\n[bold cyan]Prompt Library Categories[/bold cyan]\n")
            for key, cat in prompts.items():
                console.print(f"  [green]prompts {key}[/green] - {cat['title']} ({len(cat['prompts'])} prompts)")
            console.print(f"\n[dim]Type 'prompts <category>' to see prompts in that category[/dim]")


# Convenience function for one-off questions
def ask_aws_question(question: str, model_id: str = "anthropic.claude-3-5-sonnet-20241022-v2:0") -> str:
    """
    Ask a single question about AWS.

    Args:
        question: Natural language question
        model_id: Bedrock model to use

    Returns:
        Answer from the AI assistant
    """
    assistant = BedrockAWSAssistant(model_id=model_id)
    return assistant.ask(question)
