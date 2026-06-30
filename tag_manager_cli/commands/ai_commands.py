"""AI-powered AWS assistant commands using Bedrock."""

import typer
from typing import Optional
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ..integrations.aws_assistant import BedrockAWSAssistant, ask_aws_question
from ..integrations.output_formatter import AIOutputFormatter

app = typer.Typer(
    name="ask",
    help="AI-powered AWS assistant - Ask questions about your AWS infrastructure in natural language",
    no_args_is_help=False
)
console = Console()


def show_ask_help():
    """Show the enhanced ask help format."""
    console.print("\n[bold cyan]AI Assistant[/bold cyan] - Ask questions about your AWS infrastructure in natural language\n")

    console.print("[bold green]USAGE[/bold green]:")
    console.print("- [cyan]chat[/cyan]          - Start conversational chat session")
    console.print("- [cyan]question[/cyan]      - Ask a single question and get instant answer\n")

    console.print("[bold green]QUICK START[/bold green]:")
    console.print("1. [dim]ask question \"List my EC2 instances\"[/dim]  # Ask anything (auto-setup on first use)")
    console.print("2. [dim]ask chat[/dim]                            # Start interactive session")
    console.print("3. [dim]ask chat --model sonnet[/dim]             # Use more powerful model\n")

    # Highlight CUR cost intelligence feature
    console.print(Panel.fit(
        "[bold yellow]TIP:[/bold yellow] Ask about costs in natural language:\n\n"
        "[cyan]\"Break down my 'Others' category in cost reports\"[/cyan]\n"
        "[cyan]\"What are my top spending services?\"[/cyan]\n"
        "[cyan]\"Show EC2 costs by instance type\"[/cyan]\n\n"
        "[dim]Uses CUR (Cost & Usage Reports) for detailed analysis![/dim]",
        title="[bold magenta]Cost Intelligence[/bold magenta]",
        border_style="yellow"
    ))
    console.print()

    console.print("[bold cyan]MODEL OPTIONS[/bold cyan] (use with --model flag):")
    console.print("- [green]haiku[/green]  - Latest Haiku (cheapest, fastest) [bold green][DEFAULT][/bold green]  ~$0.0004/question")
    console.print("- [yellow]sonnet[/yellow] - Latest Sonnet (better quality)           ~$0.0045/question")
    console.print("- [red]opus[/red]   - Latest Opus (highest quality)            ~$0.0225/question\n")

    console.print("[bold magenta]EXAMPLE QUESTIONS[/bold magenta]:")
    console.print("- \"What EC2 instances are running in us-east-1?\"")
    console.print("- \"Show me my AWS costs for last month\"")
    console.print("- \"Which S3 buckets don't have required tags?\"")
    console.print("- \"List all Lambda functions with their runtimes\"")
    console.print("- \"Find RDS databases that are publicly accessible\"\n")

    console.print("[bold green]FEATURES[/bold green]:")
    console.print("- [green][OK][/green] Automatic Bedrock setup on first use")
    console.print("- [green][OK][/green] Uses your existing AWS SSO credentials")
    console.print("- [green][OK][/green] 17 specialized tools + AWS CLI for 100+ services")
    console.print("- [green][OK][/green] Session statistics and cost tracking")
    console.print("- [green][OK][/green] Streaming responses for real-time feedback")
    console.print("- [green][OK][/green] Prompt caching for 90% cost reduction on repeated context")
    console.print("- [green][OK][/green] Automatic retry with exponential backoff\n")

    console.print("[dim]First time? Just run a question - setup is automatic if needed![/dim]")


@app.callback(invoke_without_command=True)
def ask_main(
    ctx: typer.Context,
    help_flag: bool = typer.Option(False, "--help", "-h", help="Show this message and exit.")
):
    """
    AI-powered AWS assistant - Ask questions about your AWS infrastructure.

    Uses Amazon Bedrock with Claude models to answer questions using natural language.
    """
    if help_flag or ctx.invoked_subcommand is None:
        show_ask_help()
        raise typer.Exit(0)


@app.command(name="chat")
def interactive_chat(
    model: str = typer.Option(
        None,
        "--model",
        "-m",
        help="Model: 'haiku' (default), 'sonnet', 'opus', or specific model ID"
    ),
    region: str = typer.Option(
        "us-east-1",
        "--region",
        "-r",
        help="AWS region for Bedrock"
    )
):
    """
    Start interactive chat with AWS AI assistant.

    Examples:
        tag-manager ask chat                    # Uses latest Haiku (cheapest)
        tag-manager ask chat --model sonnet     # Uses latest Sonnet
        tag-manager ask chat --model haiku      # Uses latest Haiku
        tag-manager ask chat --model us.anthropic.claude-3-5-sonnet-20241022-v2:0

    Model Shortcuts:
        haiku  - Latest Haiku (cheapest, fastest) [DEFAULT]
        sonnet - Latest Sonnet (better quality, 10x cost)
        opus   - Latest Opus (highest quality, highest cost)
    """
    try:
        assistant = BedrockAWSAssistant(model_id=model, region=region)
        assistant.interactive_mode()
    except Exception as e:
        console.print(f"[red]Error starting assistant: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def question(
    query: str = typer.Argument(..., help="Your question about AWS"),
    model: str = typer.Option(
        None,
        "--model",
        "-m",
        help="Model: 'haiku' (default), 'sonnet', 'opus', or specific model ID"
    )
):
    """
    Ask a single question about your AWS account.

    Examples:
        tag-manager ask question "What EC2 instances are running?"
        tag-manager ask question "Show me my costs last month"
        tag-manager ask question "Which resources are missing tags?"
    """
    try:
        formatter = AIOutputFormatter(console)
        console.print(f"\n[bold cyan]Question:[/bold cyan] {query}\n")

        with console.status("[dim]Thinking...[/dim]"):
            answer = ask_aws_question(query, model_id=model)

        console.print(f"[bold green]Answer:[/bold green]\n")
        formatter.format_and_print(answer, streaming=False)
        console.print()

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


@app.command(hidden=True)
def models():
    """List available Bedrock Claude models and their characteristics."""
    from rich.table import Table

    table = Table(title="Available Bedrock Claude Models")
    table.add_column("Model ID", style="cyan")
    table.add_column("Name", style="green")
    table.add_column("Cost", style="yellow")
    table.add_column("Use Case", style="blue")

    models_list = [
        (
            "us.anthropic.claude-haiku-4-5-20251001-v1:0",
            "Claude Haiku 4.5 (US)",
            "$",
            "DEFAULT - Cheapest, fastest"
        ),
        (
            "us.anthropic.claude-3-haiku-20240307-v1:0",
            "Claude 3 Haiku (US)",
            "$",
            "Previous Haiku version"
        ),
        (
            "us.anthropic.claude-3-5-sonnet-20241022-v2:0",
            "Claude 3.5 Sonnet v2 (US)",
            "$$",
            "Better quality, 10x cost"
        ),
        (
            "us.anthropic.claude-3-5-sonnet-20240620-v1:0",
            "Claude 3.5 Sonnet v1 (US)",
            "$$",
            "Older Sonnet version"
        ),
        (
            "eu.anthropic.claude-3-5-sonnet-20241022-v2:0",
            "Claude 3.5 Sonnet v2 (EU)",
            "$$",
            "EU region (Frankfurt)"
        )
    ]

    for model_id, name, cost, use_case in models_list:
        table.add_row(model_id, name, cost, use_case)

    console.print(table)
    console.print("\n[dim]Use --model to specify a different model[/dim]")


@app.command(hidden=True)
def check_access(region: str = typer.Option("us-east-1", "--region", "-r", help="AWS region to check")):
    """
    Check which Bedrock models are accessible in your AWS account.

    This command lists all available foundation models and highlights
    which Claude models you can use.
    """
    import boto3
    from rich.table import Table
    from botocore.exceptions import ClientError

    try:
        console.print(f"\n[cyan]Checking Bedrock access in {region}...[/cyan]\n")

        # Create Bedrock client
        bedrock = boto3.client('bedrock', region_name=region)

        # List all foundation models
        response = bedrock.list_foundation_models(
            byProvider='Anthropic'
        )

        # Create table
        table = Table(title=f"Anthropic Models in {region}")
        table.add_column("Model ID", style="cyan")
        table.add_column("Model Name", style="green")
        table.add_column("Status", style="yellow")

        claude_models = response.get('modelSummaries', [])

        if not claude_models:
            console.print(f"[yellow]No Anthropic models found in {region}[/yellow]")
            console.print("\n[yellow]This region may not support Bedrock yet.[/yellow]")
            console.print("[yellow]Try: us-east-1, us-west-2, or eu-west-1[/yellow]")
            return

        # Display available models
        for model in claude_models:
            model_id = model.get('modelId', 'Unknown')
            model_name = model.get('modelName', 'Unknown')

            # Check lifecycle status
            lifecycle = model.get('modelLifecycle', {})
            status = lifecycle.get('status', 'Unknown')

            status_display = "✅ Active" if status == "ACTIVE" else f"⚠️ {status}"

            table.add_row(model_id, model_name, status_display)

        console.print(table)

        # Test actual access by trying to invoke
        console.print(f"\n[cyan]Testing access to Claude 3.5 Sonnet...[/cyan]")

        try:
            bedrock_runtime = boto3.client('bedrock-runtime', region_name=region)

            # Try a minimal request
            test_response = bedrock_runtime.converse(
                modelId="anthropic.claude-haiku-4-5-20251001-v1:0",
                messages=[
                    {
                        "role": "user",
                        "content": [{"text": "Hello"}]
                    }
                ],
                inferenceConfig={
                    "maxTokens": 10,
                    "temperature": 0.5
                }
            )

            console.print("[green]✅ SUCCESS! You have access to Claude models![/green]")
            console.print("[green]You can start using: tag-manager ask chat[/green]")

        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_msg = e.response['Error']['Message']

            if error_code == 'ResourceNotFoundException':
                console.print("\n[red]❌ ACCESS NOT ENABLED[/red]")
                console.print("\n[yellow]You need to enable model access first:[/yellow]")
                console.print("1. Go to AWS Console > Bedrock > Model access")
                console.print("2. Click 'Modify model access'")
                console.print("3. Enable: Anthropic Claude 3.5 Sonnet")
                console.print("4. Fill out the use case form")
                console.print("5. Wait 2-15 minutes for activation\n")
                console.print(f"[yellow]Or run: tag-manager ask setup-bedrock[/yellow]")

            elif error_code == 'AccessDeniedException':
                console.print("\n[red]❌ PERMISSION DENIED[/red]")
                console.print("\n[yellow]Your IAM role needs these permissions:[/yellow]")
                console.print("  - bedrock:InvokeModel")
                console.print("  - bedrock:InvokeModelWithResponseStream")

            else:
                console.print(f"\n[red]❌ Error: {error_msg}[/red]")

    except ClientError as e:
        console.print(f"[red]Error checking Bedrock access: {e}[/red]")
        console.print("[yellow]Make sure you have bedrock:ListFoundationModels permission[/yellow]")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Unexpected error: {e}[/red]")
        raise typer.Exit(1)


@app.command(hidden=True)
def enable_access(
    model: str = typer.Option(
        None,
        "--model",
        "-m",
        help="Model: 'haiku' (default), 'sonnet', 'opus', or specific model ID"
    ),
    region: str = typer.Option(
        "us-east-1",
        "--region",
        "-r",
        help="AWS region"
    )
):
    """
    Programmatically enable Bedrock model access.

    This command automatically:
    1. Accepts the model license agreement
    2. Submits use case details to Anthropic
    3. Enables model access in your account

    Examples:
        tag-manager ask enable-access
        tag-manager ask enable-access --model us.anthropic.claude-haiku-4-5-20251001-v1:0
    """
    try:
        from ..integrations.aws_assistant import BedrockAWSAssistant
        from rich.panel import Panel

        assistant = BedrockAWSAssistant(model_id=model, region=region)

        console.print(Panel.fit(
            "[bold cyan]Enable Bedrock Model Access[/bold cyan]\n\n"
            f"Model: {model}\n"
            f"Region: {region}",
            border_style="cyan"
        ))

        console.print()
        success = assistant._enable_model_access_programmatically(model)

        if success:
            console.print("[green]You can now use the AI assistant![/green]")
            console.print(f"[green]Try: tag-manager ask question \"How many EC2 instances do I have?\"[/green]")
        else:
            console.print("[yellow]Automatic enablement failed. Please use manual setup.[/yellow]")
            console.print("[yellow]Run: tag-manager ask setup-bedrock[/yellow]")
            raise typer.Exit(1)

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


@app.command(hidden=True)
def setup_bedrock():
    """
    Show step-by-step instructions for enabling Bedrock model access.

    This guide walks you through enabling Claude models in your AWS account.
    """
    from rich.panel import Panel
    from rich.markdown import Markdown

    instructions = """
# Enable AWS Bedrock Model Access

## Step 1: Open AWS Console

1. Go to [AWS Bedrock Console](https://console.aws.amazon.com/bedrock/)
2. Select your region (e.g., `us-east-1`)

## Step 2: Request Model Access

1. Click **"Model access"** in the left sidebar
2. Click **"Modify model access"** button
3. Find and check these models:
   - ✅ **Anthropic Claude 3.5 Sonnet**
   - ✅ **Anthropic Claude 3 Haiku** (optional, cheaper)
4. Click **"Next"**

## Step 3: Fill Use Case Form

Anthropic requires a brief use case description:

- **Use Case**: Select "Development/Testing" or "Enterprise Application"
- **Description**:
  ```
  AWS infrastructure management and analysis CLI tool.
  Used for querying AWS resources, cost analysis, and
  compliance checking via natural language interface.
  ```
- Click **"Submit"**

## Step 4: Wait for Activation

- ⏱️ Usually takes **2-15 minutes**
- ✉️ You'll receive email confirmation
- Status shown in Model access page

## Step 5: Verify Access

Run this command to check:

```bash
tag-manager ask check-access
```

## Step 6: Start Using!

Once enabled:

```bash
# Interactive chat
tag-manager ask chat

# Single question
tag-manager ask question "What EC2 instances are running?"
```

## Troubleshooting

**Still getting errors?**

1. **Check Region**: Bedrock must be available in your region
   - Supported: us-east-1, us-west-2, eu-west-1, etc.

2. **Check Permissions**: Your IAM role needs:
   ```json
   {
     "Effect": "Allow",
     "Action": [
       "bedrock:InvokeModel",
       "bedrock:InvokeModelWithResponseStream"
     ],
     "Resource": "arn:aws:bedrock:*::foundation-model/anthropic.claude-*"
   }
   ```

3. **Wait Longer**: Sometimes takes up to 15 minutes

4. **Refresh**: Close and reopen AWS Console

## Need Help?

Run: `tag-manager ask check-access` to check for issues
    """

    console.print(Panel(
        Markdown(instructions),
        title="[bold cyan]Bedrock Setup Guide[/bold cyan]",
        border_style="cyan",
        padding=(1, 2)
    ))

    console.print("\n[green]After setup, verify with:[/green] tag-manager ask check-access\n")


# Callback removed - now using ask_main() defined earlier with custom help format
