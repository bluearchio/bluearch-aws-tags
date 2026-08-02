#!/usr/bin/env python3
"""Demo script for AWS AI Assistant using Bedrock."""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tag_manager_cli.integrations.aws_assistant import BedrockAWSAssistant
from rich.console import Console
from rich.panel import Panel

console = Console()


def demo_single_question():
    """Demo: Ask a single question."""
    console.print(Panel.fit(
        "[bold cyan]Demo: Single Question Mode[/bold cyan]\n"
        "Asking: 'What EC2 instances are running in us-east-1?'",
        border_style="cyan"
    ))

    assistant = BedrockAWSAssistant()
    answer = assistant.ask("What EC2 instances are running in us-east-1?")

    console.print("\n[bold green]Answer:[/bold green]")
    console.print(answer)


def demo_cost_question():
    """Demo: Cost analysis question."""
    console.print(Panel.fit(
        "[bold cyan]Demo: Cost Analysis[/bold cyan]\n"
        "Asking: 'What were my AWS costs last month grouped by service?'",
        border_style="cyan"
    ))

    assistant = BedrockAWSAssistant()
    answer = assistant.ask("What were my AWS costs last month grouped by service?")

    console.print("\n[bold green]Answer:[/bold green]")
    console.print(answer)


def demo_tagging_question():
    """Demo: Tagging compliance question."""
    console.print(Panel.fit(
        "[bold cyan]Demo: Tagging Compliance[/bold cyan]\n"
        "Asking: 'Find resources missing required tags'",
        border_style="cyan"
    ))

    assistant = BedrockAWSAssistant()
    answer = assistant.ask("Find resources missing the Environment tag")

    console.print("\n[bold green]Answer:[/bold green]")
    console.print(answer)


def demo_interactive():
    """Demo: Interactive mode."""
    console.print(Panel.fit(
        "[bold cyan]Demo: Interactive Chat Mode[/bold cyan]\n"
        "Starting interactive session...\n"
        "Try asking:\n"
        "- What S3 buckets do I have?\n"
        "- List my Lambda functions\n"
        "- Show me IAM users",
        border_style="cyan"
    ))

    assistant = BedrockAWSAssistant()
    assistant.interactive_mode()


def main():
    """Run demo based on command line argument."""
    console.print("\n[bold blue]AWS AI Assistant Demo[/bold blue]\n")

    if len(sys.argv) > 1:
        mode = sys.argv[1]

        if mode == "single":
            demo_single_question()
        elif mode == "cost":
            demo_cost_question()
        elif mode == "tagging":
            demo_tagging_question()
        elif mode == "interactive":
            demo_interactive()
        else:
            console.print(f"[red]Unknown mode: {mode}[/red]")
            show_usage()
    else:
        show_usage()


def show_usage():
    """Show usage information."""
    console.print("""
[bold]Usage:[/bold]
    python examples/bedrock_ai_assistant_demo.py [mode]

[bold]Modes:[/bold]
    single       - Ask a single EC2 question
    cost         - Ask about costs
    tagging      - Ask about tagging compliance
    interactive  - Start interactive chat

[bold]Or use the CLI directly:[/bold]
    bluearch-aws-tags ask chat                                    # Interactive mode
    bluearch-aws-tags ask question "What EC2 instances exist?"   # Single question
    bluearch-aws-tags ask models                                  # List available models
    """)


if __name__ == "__main__":
    main()
