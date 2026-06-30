# AI Chat Feature: Competitive Analysis and Improvement Roadmap

**Objective:** Position the Tag Manager AI assistant as a highlighted differentiator against Amazon Q and similar AWS management tools.

---

## Table of Contents

1. [Current Architecture](#current-architecture)
2. [Amazon Q Comparison](#amazon-q-comparison)
3. [Quick Wins (Current Sprint)](#quick-wins-current-sprint)
4. [Medium-Term Improvements](#medium-term-improvements)
5. [Long-Term Vision](#long-term-vision)
6. [Priority Roadmap](#priority-roadmap)

---

## Current Architecture

### Backend: BedrockAWSAssistant

The AI chat is powered by `BedrockAWSAssistant` (`tag_manager_cli/integrations/aws_assistant.py`), a Python class that wraps the Bedrock Converse and Converse Stream APIs with an agentic tool-use loop.

**Core capabilities:**

- **20 AWS tools** exposed via Bedrock `tool_use` -- covering EC2, S3, Lambda, RDS, VPC, IAM, Cost Explorer, CUR, tag compliance, CloudWatch alarms, cross-account queries, and CLI self-execution.
- **Agentic loop** with up to 5 turns per request. The assistant can chain multiple tool calls to answer complex questions (e.g., "find untagged EC2 instances and estimate their monthly cost").
- **Model selection** via alias shortcuts (`haiku`, `sonnet`, `opus`) resolved at runtime through `model_resolver.py` to the latest inference profile IDs. Performance config (`latency: optimized`) is applied automatically for Sonnet and Opus.
- **Prompt caching** on both the system prompt and tool definitions via Bedrock `cachePoint` markers, yielding approximately 90% input token cost reduction on subsequent turns.
- **Follow-up suggestions** -- the system prompt instructs the model to generate 2-3 contextual follow-up questions after each response, covering cost, compliance, and optimization angles.
- **Cross-account awareness** -- the system prompt includes detailed instructions for scope negotiation (current account, specific accounts, all accounts) with session-level persistence via `set_account_scope`/`get_current_account_scope` tools.

### SSE Streaming Pipeline

The web API layer (`tag_manager_cli/web/routers/ai.py`) bridges the synchronous Bedrock streaming generator to the async FastAPI frontend via a thread-and-queue architecture:

1. `POST /api/v1/ai/chat` receives the question and session ID.
2. A background thread runs `assistant.ask_stream(question)`, which calls `client.converse_stream()` and yields text chunks.
3. A `ToolCallCapture` proxy wraps the assistant's formatter to intercept `print_tool_call` and `print_tool_result_summary` events, pushing them into the same queue as text chunks.
4. The async generator reads from the queue and emits SSE events with types: `text`, `tool_call`, `tool_result`, `done`, and `error`.
5. The `done` event includes session ID and cumulative token counts (input/output).

### Session Management

Sessions are stored in an in-memory `OrderedDict` with FIFO eviction at 20 sessions. Each session holds a full `BedrockAWSAssistant` instance with its conversation history. There is no persistence across server restarts.

### Frontend: Vue 3 ChatView

The chat UI (`frontend/src/views/ChatView.vue`) provides:

- **Example question chips** on the empty state to reduce cold-start friction.
- **Real-time tool call visualization** -- a panel showing each tool's name, spinner/check/error status, and result summary while the assistant executes AWS operations.
- **Markdown rendering** via `marked` with GFM and line-break support.
- **Clickable entities** -- resource ARNs, 12-digit account IDs, and AWS service names are detected via regex and rendered as interactive links that navigate to the Resources view with appropriate filters.
- **Model selector** (Haiku/Sonnet/Opus) and conversation clear button.
- **Auto-scrolling** during streaming responses.

### Tool Inventory (20 Tools)

| Tool | Category | Description |
|------|----------|-------------|
| `list_ec2_instances` | Compute | EC2 instances with cross-account support |
| `describe_s3_buckets` | Storage | S3 buckets with cross-account aggregation |
| `list_lambda_functions` | Compute | Lambda functions with cross-account support |
| `describe_rds_instances` | Database | RDS instances with cross-account support |
| `list_vpc_resources` | Networking | VPCs, subnets, security groups |
| `list_iam_users` | Security | IAM users with access key details |
| `get_account_summary` | Overview | Account-level resource summary |
| `query_cur_costs` | FinOps | CUR-powered cost queries with account filtering |
| `get_cost_analysis` | FinOps | Cost Explorer time-series analysis |
| `find_untagged_resources` | Compliance | Resources missing required tags |
| `get_tag_compliance_summary` | Compliance | Overall compliance rates and stats |
| `get_tag_compliance_by_service` | Compliance | Per-service compliance breakdown |
| `get_high_risk_untagged_resources` | Compliance | Risk-scored non-compliant resources |
| `suggest_cloudwatch_alarms` | Monitoring | Alarm recommendations for resources |
| `list_managed_alarms` | Monitoring | Tag Manager-created alarms |
| `get_alarm_templates` | Monitoring | Available alarm templates |
| `create_cloudwatch_alarm` | Monitoring | Create alarms (with confirmation) |
| `list_available_accounts` | Multi-account | Organization account listing |
| `set_account_scope` / `get_current_account_scope` | Multi-account | Session scope management |
| `run_tag_manager_command` | CLI | Execute CLI commands (sandboxed) |
| `get_cli_help` | CLI | Documentation and usage help |

---

## Amazon Q Comparison

### Where Tag Manager AI Excels

**1. Deep lifecycle and compliance context.**
Amazon Q has no concept of resource TTLs, lifecycle policies, or tag compliance rules. Tag Manager's AI operates with full awareness of local lifecycle policies, expiration dates, and tag governance rules. When a user asks "which resources are expiring soon?", the assistant queries the local policy engine -- not just raw AWS APIs.

**2. Integrated cost intelligence.**
The AI can query both CUR data (via Athena) and Cost Explorer in the same conversation, with cross-account filtering. Amazon Q's cost capabilities are limited to high-level summaries. Tag Manager can answer "what is the daily cost trend for untagged resources in my dev account?" by chaining `find_untagged_resources` with `query_cur_costs`.

**3. Cross-account scope negotiation.**
The assistant proactively asks users about account scope, remembers their preference for the session, and applies it across all subsequent tool calls. Amazon Q operates within a single account context by default.

**4. Tool transparency.**
Every AWS API call is visible in the UI as a tool call with status indicators. Users see exactly what data the AI is accessing. Amazon Q operates as a black box.

**5. Model flexibility.**
Users can choose between Haiku (fast/cheap), Sonnet (balanced), and Opus (highest quality) per conversation. Amazon Q offers no model selection.

**6. CLI integration.**
The assistant can execute Tag Manager CLI commands on behalf of the user and provide documentation via `get_cli_help`. This creates a natural language interface to the entire tool, not just AWS APIs.

### Where Amazon Q Excels

**1. Breadth of service coverage.**
Amazon Q covers 200+ AWS services. Tag Manager covers the services most relevant to tag governance and lifecycle management (EC2, S3, Lambda, RDS, ECS, ELB, IAM, VPC, CloudWatch). Users asking about niche services (e.g., AppSync, Bedrock model management, SageMaker) will hit tool gaps.

**2. Native AWS console integration.**
Amazon Q is embedded in the AWS console, CloudWatch, and IDE plugins. Tag Manager's AI lives exclusively in its own web dashboard.

**3. Code generation and IaC.**
Amazon Q can generate CloudFormation, CDK, and Terraform code. Tag Manager's AI does not generate infrastructure-as-code.

**4. Troubleshooting depth.**
Amazon Q can access CloudTrail logs, VPC flow logs, and service-specific diagnostics. Tag Manager's AI is limited to its 20 tools.

**5. No additional Bedrock costs.**
Amazon Q is priced as a flat subscription. Tag Manager's AI incurs per-token Bedrock charges (mitigated by prompt caching, but still a variable cost).

### Key Differentiators to Exploit

These are areas where Tag Manager has a structural advantage that Amazon Q cannot easily replicate:

1. **Opinionated workflows.** Amazon Q is general-purpose. Tag Manager can guide users through specific outcomes: "clean up dev resources older than 30 days", "bring this account to 90% tag compliance", "set up cost anomaly detection for production".

2. **Local policy engine integration.** Lifecycle policies, TTL rules, and compliance baselines are local state that Amazon Q has no access to. Every AI response can be enriched with this context.

3. **Cross-account as a first-class concept.** Multi-account queries with scope persistence are built into the tool system. Amazon Q requires manual account switching.

4. **Actionable outputs.** The AI can create CloudWatch alarms, execute CLI commands, and (with approval workflows) modify resources. Amazon Q is primarily read-only.

---

## Quick Wins (Current Sprint)

These improvements require minimal backend changes and deliver immediate UX impact.

### 1. Clickable Follow-Up Suggestion Chips

**Current state:** The AI generates follow-up suggestions as markdown text (bullet points with dashes). Users must manually copy-paste or retype these suggestions.

**Improvement:** Parse the suggestion block from the AI response (text between the final `---` delimiters), extract individual suggestions, and render them as clickable chip buttons below the response. Clicking a chip sends it as the next user message.

**Implementation:**
- Frontend: Add a `parseSuggestions(content)` function that extracts suggestions via regex on the markdown pattern. Render extracted suggestions as `<button>` elements styled like the example question chips.
- Backend: No changes required -- the system prompt already generates suggestions in a consistent format.

**Impact:** Reduces friction for multi-turn exploration. Increases average session depth.

### 2. Smart Model Routing

**Current state:** Users manually select Haiku, Sonnet, or Opus from a dropdown. Most users leave it on the default (Haiku), which underperforms on complex analytical questions.

**Improvement:** Auto-select the model based on query complexity analysis:
- **Haiku:** Simple lookups, single-tool queries ("list my EC2 instances", "show S3 buckets").
- **Sonnet:** Multi-step analysis, cross-account queries, cost trends ("compare costs across accounts for the last 3 months").
- **Opus:** Complex reasoning, policy recommendations, multi-dimensional analysis ("design a lifecycle policy for dev resources that balances cost savings with team productivity").

**Implementation:**
- Backend: Add a lightweight classifier (keyword matching + message length heuristic) in the `/api/v1/ai/chat` handler. Override the user's model selection when the classifier recommends a higher tier. Return the actual model used in the `done` SSE event.
- Frontend: Show the auto-selected model as a subtle indicator ("Upgraded to Sonnet for this query"). Allow users to pin a specific model to override auto-selection.

**Impact:** Better response quality without user effort. Estimated 40% improvement in complex query satisfaction.

### 3. Tool Result Caching

**Current state:** Every tool call hits the AWS API directly. Repeated questions within a session re-execute the same API calls.

**Improvement:** Cache tool results for 60 seconds using the existing diskcache infrastructure. Cache key is `tool_name + sorted(tool_input)`. Bypass cache for write operations (`create_cloudwatch_alarm`, `set_account_scope`).

**Implementation:**
- Backend: Wrap the `execute_tool()` call in `aws_tools.py` with a diskcache lookup. Add a `cacheable` flag to each tool's schema (default `True`, set `False` for mutations).
- Emit a `tool_cached` SSE event type (distinct from `tool_result`) so the frontend can indicate cached results.

**Impact:** Faster follow-up queries. Reduced AWS API costs. Better UX for iterative exploration.

### 4. Streaming Tool Progress with Elapsed Time

**Current state:** Tool calls show a spinner, name, and completion status. No indication of how long each tool takes.

**Improvement:** Track and display elapsed time for each tool call. Show a running timer while the tool executes and the final duration on completion (e.g., "List EC2 Instances -- 2.3s").

**Implementation:**
- Backend: Add `started_at` timestamp to the `tool_call` SSE event. Add `elapsed_ms` to the `tool_result` SSE event.
- Frontend: Display a running counter based on `started_at` while status is `running`. Display final `elapsed_ms` on completion.

**Impact:** Builds user trust by showing the system is working. Helps identify slow API calls.

### 5. Conversation Persistence

**Current state:** Sessions are in-memory (`OrderedDict`, max 20). All conversations are lost on server restart.

**Improvement:** Persist conversations to SQLite. Add a sidebar panel listing previous conversations with timestamps and preview text. Allow users to resume, rename, and delete conversations.

**Implementation:**
- Backend: Add `Conversation` and `ConversationMessage` SQLAlchemy models. Store messages on each SSE `done` event. Add REST endpoints: `GET /api/v1/ai/conversations`, `GET /api/v1/ai/conversations/{id}`, `DELETE /api/v1/ai/conversations/{id}`, `PATCH /api/v1/ai/conversations/{id}` (rename).
- Frontend: Add a collapsible conversation sidebar to `ChatView`. Load conversation list on mount. Clicking a conversation restores the assistant session with its history.
- Migration: Add Alembic migration for the new tables.

**Impact:** Transforms the chat from a throwaway tool into a persistent knowledge base. Critical for teams sharing the dashboard.

---

## Medium-Term Improvements

### Context-Aware System Prompts

Inject live infrastructure context into the system prompt so the AI can provide informed responses without initial tool calls:

```
Current environment snapshot (as of {timestamp}):
- Total resources tracked: {count}
- Tag compliance rate: {rate}%
- Monthly spend (MTD): ${amount}
- Resources expiring in 7 days: {count}
- Active lifecycle policies: {count}
- Accounts in scope: {list}
```

**Implementation:** Query the database and cache on session creation. Refresh every 5 minutes. Append to the system prompt before the first `cachePoint`.

**Value:** Eliminates the need for "warm-up" tool calls. The AI can immediately reference compliance rates or cost figures without the user asking first.

### Prompt Templates Library

Provide a curated set of prompt templates accessible from the chat UI:

- **Cost review:** "Run a complete cost analysis for {account} covering the last {period}. Include top services, daily trends, and anomalies."
- **Compliance audit:** "Generate a tag compliance report for {service}. List all non-compliant resources with their owners and remediation priority."
- **Lifecycle cleanup:** "Identify all {environment} resources older than {days} days that have no lifecycle policy. Recommend TTL settings."
- **Security review:** "List all IAM users with access keys older than 90 days. Check for unused keys and recommend rotations."

**Implementation:** Store templates as JSON in the database (or a static config file). Add a template picker button next to the chat input. Templates with `{variables}` open a form dialog before sending.

**Value:** Reduces the "blank page" problem. Encodes best practices into reusable queries. Enables team standardization.

### Multi-Modal Support

Allow users to paste or upload screenshots (e.g., AWS console charts, cost graphs) for the AI to analyze.

**Implementation:** Use Bedrock's multi-modal input support (Claude models accept images). Add image upload to the chat input. Encode images as base64 and include as `image` content blocks in the Bedrock API call.

**Value:** Enables scenarios like "here is a screenshot of my CloudWatch dashboard -- what anomalies do you see?" Differentiates strongly from Amazon Q, which does not support image analysis in its chat interface.

### Conversation Export

Allow users to export conversations as PDF or Markdown files for documentation, auditing, or sharing.

**Implementation:**
- Markdown export: Serialize the conversation with tool calls, results, and timestamps. Straightforward text transformation.
- PDF export: Use a server-side library (e.g., `weasyprint` or `reportlab`) to render the markdown export as a styled PDF with the Tag Manager branding.
- Add export buttons to the conversation sidebar and the active chat.

**Value:** Supports compliance documentation requirements. Enables sharing analysis results with stakeholders who do not have dashboard access.

### Guided Workflows (Wizard-Like AI Interactions)

Create structured, multi-step AI interactions for common workflows:

1. **Cost Optimization Wizard:** The AI walks the user through account selection, identifies high-spend services, recommends Reserved Instances or Savings Plans, and generates an action plan.
2. **Compliance Remediation Wizard:** The AI identifies non-compliant resources, prioritizes by risk/cost, generates tagging recommendations, and offers to apply tags.
3. **Lifecycle Policy Builder:** The AI interviews the user about their environment conventions, suggests lifecycle policies, and creates them upon approval.

**Implementation:** Use `custom_system_prompt` (already supported by `BedrockAWSAssistant`) to swap in wizard-specific prompts. Add a workflow selector to the chat UI that initializes a session with the appropriate prompt and constrained tool set.

**Value:** Transforms the AI from a Q&A tool into a guided advisor. Directly competes with AWS Well-Architected Tool but with actionable automation.

---

## Long-Term Vision

### Multi-Agent Architecture

For complex queries that span multiple domains (e.g., "optimize my AWS spend while maintaining compliance"), decompose the work across specialized agents:

- **Cost Agent:** Focused on FinOps analysis, CUR queries, and spend optimization.
- **Compliance Agent:** Focused on tag policies, compliance gaps, and remediation.
- **Lifecycle Agent:** Focused on TTL policies, resource cleanup, and protection rules.
- **Orchestrator Agent:** Routes queries, merges results, and presents unified recommendations.

**Technical approach:** Each agent is a `BedrockAWSAssistant` instance with a specialized system prompt and a subset of tools. The orchestrator uses Bedrock's tool_use to call sub-agents as tools. This is achievable with the current architecture by adding "meta-tools" that invoke other assistant instances.

### Proactive Insights

Move from reactive Q&A to proactive notifications:

- **Scheduled analysis:** Run cost trend analysis, compliance checks, and lifecycle scans on a daily/weekly cadence. Surface findings as dashboard notifications and optional email/Slack digests.
- **Anomaly alerts:** When cost anomaly detection flags a spike, automatically generate an AI analysis explaining the likely cause and recommended actions.
- **Policy drift detection:** When compliance rates drop below a threshold, trigger an AI-generated report identifying the root cause.

**Technical approach:** Add a lightweight scheduler (APScheduler or a cron-based approach) that runs predefined prompts through `BedrockAWSAssistant` and stores the results. Surface in the dashboard via a notifications panel.

### Custom Tool Creation

Allow advanced users to define custom tools that the AI can invoke:

- **HTTP tools:** Define a URL, method, headers, and response mapping. The AI calls external APIs (e.g., PagerDuty, Jira, Datadog).
- **Script tools:** Upload a Python script that the AI can execute in a sandboxed environment.
- **Query tools:** Define SQL queries against the local SQLite database that the AI can parameterize and execute.

**Technical approach:** Store tool definitions in the database. Dynamically register them with `AWSTools.get_tools_schema()` at session creation. Execute via a sandboxed runner with timeout and resource limits.

### Natural Language Policy Authoring

Allow users to define lifecycle and compliance policies in natural language:

- "All dev EC2 instances should expire after 7 days unless they have a `keep=true` tag."
- "S3 buckets without a `team` tag should be flagged as high-risk non-compliant."
- "Lambda functions in the sandbox account older than 30 days with zero invocations should be candidates for deletion."

**Technical approach:** The AI translates natural language into the existing policy schema (JSON). Show the generated policy for user review and approval before persisting. Use the existing `ResourceLifecyclePolicy` model for storage.

### AI-Powered Remediation with Approval Workflows

Enable the AI to propose and execute remediation actions with a human-in-the-loop approval step:

1. AI identifies an issue (e.g., 15 untagged EC2 instances in production).
2. AI generates a remediation plan (apply `team=platform`, `environment=production` tags based on naming conventions and VPC placement).
3. Plan is presented to the user with a diff-like view showing proposed changes.
4. User approves, modifies, or rejects the plan.
5. On approval, the system executes the changes and records them in the audit log.

**Technical approach:** Add a `RemediationPlan` model with status tracking (proposed/approved/rejected/executed). Extend the tool set with a `propose_remediation` tool that creates a plan without executing it. Add approval endpoints and a plan review UI.

---

## Priority Roadmap

### P0: Quick Wins (Current Sprint -- Weeks 1-2)

| Item | Effort | Impact |
|------|--------|--------|
| Clickable follow-up suggestion chips | 0.5 days | High -- immediate engagement lift |
| Smart model routing | 1 day | High -- better quality without user effort |
| Tool result caching (60s, diskcache) | 1 day | Medium -- faster follow-ups, lower API costs |
| Streaming tool progress with elapsed time | 0.5 days | Medium -- trust and transparency |
| Conversation persistence (SQLite) | 2 days | High -- retention and continuity |

**Total estimated effort:** 5 days
**Success metrics:** Average session depth (messages per conversation), return visit rate, time-to-first-useful-answer.

### P1: Context and Templates (Weeks 3-5)

| Item | Effort | Impact |
|------|--------|--------|
| Context-aware system prompts | 2 days | High -- eliminates warm-up calls |
| Prompt templates library (8-10 templates) | 3 days | High -- reduces blank-page problem |
| Conversation search and filtering | 1 day | Medium -- findability for persistent conversations |

**Total estimated effort:** 6 days
**Success metrics:** First-response relevance (qualitative), template usage rate, prompt cache hit rate.

### P2: Guided Workflows and Export (Weeks 6-10)

| Item | Effort | Impact |
|------|--------|--------|
| Guided workflows (3 wizards) | 5 days | High -- moves from Q&A to advisory |
| Conversation export (Markdown + PDF) | 2 days | Medium -- compliance and sharing |
| Multi-modal support (image upload) | 3 days | Medium -- differentiation vs Amazon Q |

**Total estimated effort:** 10 days
**Success metrics:** Wizard completion rate, export downloads, image query volume.

### P3: Advanced Capabilities (Weeks 11-20)

| Item | Effort | Impact |
|------|--------|--------|
| Multi-agent architecture | 8 days | High -- handles complex queries |
| Proactive insights (scheduler + notifications) | 5 days | High -- moves to proactive value |
| Natural language policy authoring | 5 days | Medium -- reduces policy creation friction |
| Custom tool creation | 8 days | Medium -- extensibility for power users |
| AI-powered remediation with approvals | 8 days | High -- full automation loop |

**Total estimated effort:** 34 days
**Success metrics:** Complex query resolution rate, proactive insight engagement, policy creation via AI, remediation plan approval rate.

---

## Cost Considerations

### Current Bedrock Costs (Per Conversation)

| Model | Input (per 1M tokens) | Output (per 1M tokens) | Typical 5-turn cost |
|-------|-----------------------|------------------------|---------------------|
| Haiku | $0.80 | $4.00 | ~$0.01-0.03 |
| Sonnet | $3.00 | $15.00 | ~$0.05-0.15 |
| Opus | $15.00 | $75.00 | ~$0.25-0.75 |

**Prompt caching** reduces input token costs by approximately 90% after the first turn in a session. With caching, a typical 5-turn Haiku conversation costs under $0.01.

### Cost Optimization Levers

1. **Smart model routing** directs 70-80% of queries to Haiku, reserving Sonnet/Opus for queries that benefit from them.
2. **Tool result caching** eliminates redundant API calls and reduces turn count.
3. **Context-aware prompts** reduce the need for initial "discovery" tool calls, cutting 1-2 turns from average conversations.
4. **Prompt caching** is already implemented and provides the largest single cost reduction.

### Projected Monthly Cost at Scale

| Users | Conversations/day | Model mix (H/S/O) | Monthly Bedrock cost |
|-------|--------------------|--------------------|----------------------|
| 10 | 30 | 80/15/5 | ~$15-30 |
| 50 | 150 | 75/20/5 | ~$75-150 |
| 200 | 600 | 70/25/5 | ~$300-600 |

These estimates assume 5 turns per conversation with prompt caching active. Actual costs will vary based on query complexity and tool call volume.

---

## Summary

The Tag Manager AI assistant has a defensible advantage over Amazon Q in three areas: **deep lifecycle/compliance context**, **integrated cross-account FinOps**, and **tool transparency with actionable outputs**. The quick wins in this sprint will address the most visible UX gaps (suggestion interactivity, model selection friction, session persistence). The medium-term work on guided workflows and context-aware prompts will transform the feature from a chat interface into an advisory system that Amazon Q's general-purpose design cannot replicate.

The key strategic insight: Amazon Q tries to be everything for everyone. Tag Manager's AI should be the best possible assistant for AWS resource governance -- lifecycle management, cost optimization, and tag compliance -- and nothing else. Depth beats breadth when users have a specific job to do.
