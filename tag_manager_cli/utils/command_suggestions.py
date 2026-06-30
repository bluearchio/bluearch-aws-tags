# -*- coding: utf-8 -*-
"""Command suggestions module for AWS Tag Manager CLI.

This module provides contextual suggestions and next-step guidance
after each command execution, helping users navigate the CLI more effectively.
"""

from typing import List, Dict, Optional, Any
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.columns import Columns
from rich.text import Text
from .console_safe import safe_print


class CommandSuggestions:
    """Manages contextual command suggestions and next-step guidance."""

    def __init__(self):
        self.console = Console()

        # Define suggestion mappings for different contexts
        self.suggestions_map = {
            # Tags commands
            "tags.scan": [
                {"cmd": "tags apply --interactive", "desc": "Start tagging resources interactively"},
                {"cmd": "tags bulk --service ec2", "desc": "Bulk tag EC2 instances"},
                {"cmd": "tags rules create", "desc": "Create automated tagging rules"},
                {"cmd": "tags report compliance", "desc": "Generate compliance report"}
            ],
            "tags.scan.no_untagged": [
                {"cmd": "tags report compliance", "desc": "Generate full compliance report"},
                {"cmd": "tags lifecycle list", "desc": "Review resource lifecycle policies"},
                {"cmd": "tags rules list", "desc": "View your automation rules"},
                {"cmd": "discover all", "desc": "Update resource discovery"}
            ],
            "tags.apply.success": [
                {"cmd": "tags scan", "desc": "Find more untagged resources"},
                {"cmd": "tags report audit --last-hours 1", "desc": "Review recent tagging changes"},
                {"cmd": "tags rules create", "desc": "Automate similar tagging"},
                {"cmd": "tags status", "desc": "Check tagging system status"}
            ],
            "tags.bulk.complete": [
                {"cmd": "tags scan", "desc": "Verify remaining untagged resources"},
                {"cmd": "tags report compliance", "desc": "Check compliance after bulk tagging"},
                {"cmd": "tags lifecycle set-ttl --ttl-days 30", "desc": "Set resource lifecycles"},
                {"cmd": "tags apply --auto", "desc": "Apply automation rules"}
            ],
            "tags.rules.created": [
                {"cmd": "tags apply --auto", "desc": "Apply your new rules immediately"},
                {"cmd": "tags rules test --dry-run", "desc": "Test rules before applying"},
                {"cmd": "tags rules list", "desc": "Review all your rules"},
                {"cmd": "tags scan", "desc": "Find resources for rules"}
            ],
            "tags.rules.list": [
                {"cmd": "tags apply --auto", "desc": "Apply enabled rules to resources"},
                {"cmd": "tags rules enable <rule-name>", "desc": "Enable specific rules"},
                {"cmd": "tags rules create", "desc": "Create new tagging rules"},
                {"cmd": "tags report automation", "desc": "View automation effectiveness"}
            ],
            "tags.lifecycle.set": [
                {"cmd": "tags lifecycle list", "desc": "View all lifecycle policies"},
                {"cmd": "tags lifecycle cleanup --dry-run", "desc": "Preview cleanup actions"},
                {"cmd": "tags report lifecycle", "desc": "Generate lifecycle report"},
                {"cmd": "tags scan --min-age 720", "desc": "Find old untagged resources"}
            ],
            "tags.report.compliance": [
                {"cmd": "tags scan", "desc": "Find and fix non-compliant resources"},
                {"cmd": "tags apply --interactive", "desc": "Fix compliance issues"},
                {"cmd": "tags bulk --service <service>", "desc": "Fix specific service compliance"},
                {"cmd": "cost report --tag-key CostCenter", "desc": "Analyze costs by tags"}
            ],
            "tags.status": [
                {"cmd": "workers health", "desc": "Check worker health status"},
                {"cmd": "tags scan", "desc": "Find resources to tag"},
                {"cmd": "tags report audit", "desc": "View recent tagging activity"},
                {"cmd": "tags apply --auto", "desc": "Run automated tagging"}
            ],

            # Worker commands
            "workers.discover.complete": [
                {"cmd": "workers list", "desc": "View all discovered resources"},
                {"cmd": "tags scan", "desc": "Find untagged among discovered resources"},
                {"cmd": "tags apply --interactive", "desc": "Start tagging discovered resources"},
                {"cmd": "workers status", "desc": "Check discovery status"}
            ],
            "workers.discover.failed": [
                {"cmd": "system validate", "desc": "Check AWS configuration"},
                {"cmd": "setup validate", "desc": "Validate AWS connectivity"},
                {"cmd": "workers health --auto-fix", "desc": "Try automatic fixes"},
                {"cmd": "setup wizard", "desc": "Reconfigure AWS access"}
            ],
            "workers.start.success": [
                {"cmd": "workers status", "desc": "Verify workers are running"},
                {"cmd": "workers health", "desc": "Check worker health"},
                {"cmd": "tags apply --auto", "desc": "Enable automated tagging"},
                {"cmd": "slack worker start", "desc": "Start Slack integration"}
            ],
            "workers.stop.success": [
                {"cmd": "workers status", "desc": "Verify workers stopped"},
                {"cmd": "docker stop", "desc": "Stop Docker services too"},
                {"cmd": "service stop", "desc": "Stop system service"}
            ],
            "workers.status.healthy": [
                {"cmd": "lifecycle scan", "desc": "Scan resources"},
                {"cmd": "lifecycle set-ttl", "desc": "Apply TTL to resources"},
                {"cmd": "lifecycle review", "desc": "Review expiring resources"}
            ],
            "workers.status.issues": [
                {"cmd": "workers health --auto-fix", "desc": "Fix issues automatically"},
                {"cmd": "workers restart", "desc": "Restart worker processes"},
                {"cmd": "setup validate", "desc": "Run system validation"},
                {"cmd": "docker restart", "desc": "Restart Docker services"}
            ],
            "workers.health.fixed": [
                {"cmd": "workers status", "desc": "Verify everything is working"},
                {"cmd": "tags scan", "desc": "Resume tagging operations"},
                {"cmd": "tags apply --auto", "desc": "Resume automated tagging"}
            ],

            # System commands
            "system.validate.success": [
                {"cmd": "lifecycle scan", "desc": "Scan AWS resources"},
                {"cmd": "lifecycle wizard", "desc": "Start guided workflow"},
                {"cmd": "setup wizard", "desc": "Run interactive setup wizard"}
            ],
            "system.validate.failed": [
                {"cmd": "setup wizard", "desc": "Run guided setup to fix issues"},
                {"cmd": "system config", "desc": "Review configuration"},
                {"cmd": "setup validate", "desc": "Run validation checks"},
                {"cmd": "aws sso login", "desc": "Refresh AWS credentials"}
            ],
            "system.status": [
                {"cmd": "workers health", "desc": "Check worker health"},
                {"cmd": "setup validate", "desc": "Run system validation"},
                {"cmd": "tags status", "desc": "Check tagging status"},
                {"cmd": "update check", "desc": "Check for updates"}
            ],

            # Setup commands
            "setup.wizard.complete": [
                {"cmd": "setup validate", "desc": "Verify setup completed successfully"},
                {"cmd": "lifecycle wizard", "desc": "Complete guided lifecycle workflow"},
                {"cmd": "lifecycle scan", "desc": "Scan and discover resources"}
            ],
            "setup.wizard.skipped_slack": [
                {"cmd": "lifecycle scan", "desc": "Scan and discover resources"},
                {"cmd": "lifecycle wizard", "desc": "Complete guided lifecycle workflow"},
                {"cmd": "setup validate", "desc": "Verify system health"}
            ],

            # Slack commands
            "slack.setup.success": [
                {"cmd": "slack test", "desc": "Test Slack connection"},
                {"cmd": "slack worker start", "desc": "Start Slack bot daemon"},
                {"cmd": "slack status", "desc": "Check integration status"},
                {"cmd": "tags apply --slack-notify", "desc": "Tag with Slack notifications"}
            ],
            "slack.test.success": [
                {"cmd": "slack worker start", "desc": "Start the Slack daemon"},
                {"cmd": "slack status", "desc": "View detailed status"},
                {"cmd": "tags apply --slack-approval", "desc": "Use Slack approval workflow"},
                {"cmd": "tags rules create --slack-notify", "desc": "Create rules with notifications"}
            ],
            "slack.worker.started": [
                {"cmd": "slack status", "desc": "Verify worker is running"},
                {"cmd": "slack test", "desc": "Send test message"},
                {"cmd": "tags apply --slack-approval", "desc": "Try approval workflow"},
                {"cmd": "service install", "desc": "Install as system service"}
            ],
            "slack.worker.stopped": [
                {"cmd": "slack worker start", "desc": "Restart when ready"},
                {"cmd": "service stop", "desc": "Stop system service too"},
                {"cmd": "slack status", "desc": "Check current status"}
            ],

            # Update commands
            "update.check.available": [
                {"cmd": "update install", "desc": "Install the latest version"},
                {"cmd": "update changelog", "desc": "View detailed changes"},
                {"cmd": "setup validate", "desc": "Check current system health"}
            ],
            "update.check.current": [
                {"cmd": "tags scan", "desc": "Continue with tagging"},
                {"cmd": "workers status", "desc": "Check system status"},
                {"cmd": "setup validate", "desc": "Run health check"}
            ],
            "update.install.success": [
                {"cmd": "setup validate", "desc": "Verify update successful"},
                {"cmd": "--version", "desc": "Check new version"},
                {"cmd": "workers restart", "desc": "Restart workers with new version"},
                {"cmd": "database migrate", "desc": "Run any new migrations"}
            ],

            # Docker commands
            "docker.start.success": [
                {"cmd": "docker status", "desc": "Verify services running"},
                {"cmd": "workers start", "desc": "Start background workers"},
                {"cmd": "setup validate", "desc": "Check service health"},
                {"cmd": "tags scan", "desc": "Begin tagging operations"}
            ],
            "docker.stop.success": [
                {"cmd": "docker status", "desc": "Verify services stopped"},
                {"cmd": "workers stop", "desc": "Stop workers too"},
                {"cmd": "service stop", "desc": "Stop system service"}
            ],

            # Database commands
            "database.migrate.success": [
                {"cmd": "database status", "desc": "Check migration status"},
                {"cmd": "workers restart", "desc": "Restart workers after migration"},
                {"cmd": "setup validate", "desc": "Verify system health"},
                {"cmd": "tags scan", "desc": "Resume operations"}
            ],
            "database.reset.success": [
                {"cmd": "database migrate", "desc": "Run migrations on clean database"},
                {"cmd": "lifecycle scan", "desc": "Scan resources"},
                {"cmd": "setup wizard", "desc": "Reconfigure if needed"}
            ],

            # Validation commands (replaces diagnose)
            "setup.validate.success": [
                {"cmd": "lifecycle scan", "desc": "Scan resources"},
                {"cmd": "lifecycle wizard", "desc": "Complete guided workflow"},
                {"cmd": "lifecycle set-ttl", "desc": "Apply TTL to resources"},
                {"cmd": "lifecycle review", "desc": "Review expiring resources"}
            ],
            "setup.validate.failed": [
                {"cmd": "workers health --auto-fix", "desc": "Try automatic fixes"},
                {"cmd": "setup wizard", "desc": "Fix configuration issues"},
                {"cmd": "aws sso login", "desc": "Refresh AWS credentials"},
                {"cmd": "system validate", "desc": "Check specific components"}
            ],

            # First-time user flow
            "first_time": [
                {"cmd": "setup wizard", "desc": "Complete guided setup (recommended)"},
                {"cmd": "system validate", "desc": "Check your AWS configuration"},
                {"cmd": "interactive", "desc": "Use menu-driven interface"},
                {"cmd": "--help", "desc": "View all available commands"}
            ],

            # Interactive mode suggestions
            "interactive.exit": [
                {"cmd": "tags scan", "desc": "Quick untagged resource scan"},
                {"cmd": "workers status", "desc": "Check system status"},
                {"cmd": "setup validate", "desc": "Run system validation"}
            ],

            # Cost analysis suggestions
            "cost.analysis.complete": [
                {"cmd": "tags report cost-allocation", "desc": "Detailed cost allocation report"},
                {"cmd": "tags apply --tag CostCenter=<value>", "desc": "Apply cost center tags"},
                {"cmd": "tags lifecycle optimize", "desc": "Optimize resource lifecycles"},
                {"cmd": "tags scan --required-tags CostCenter", "desc": "Find resources missing cost tags"}
            ]
        }

        # Define workflow-based suggestions
        self.workflow_suggestions = {
            "initial_setup": [
                "1. Run 'setup wizard' for complete guided setup",
                "2. Use 'lifecycle scan' to discover AWS resources",
                "3. Check with 'setup validate' to verify everything works",
                "4. Start managing lifecycle with 'lifecycle set-ttl'"
            ],
            "daily_operations": [
                "- 'lifecycle scan' to scan resources",
                "- 'lifecycle scan --expiring 7' to find expiring resources",
                "- 'lifecycle review' to review and manage resources",
                "- 'setup validate' to check system health"
            ],
            "troubleshooting": [
                "- 'setup validate' for detailed system checks",
                "- 'workers health --auto-fix' to fix worker issues",
                "- 'aws sso login' to refresh AWS credentials",
                "- 'update install' to get the latest fixes"
            ],
            "automation_setup": [
                "1. 'tags rules create' to define tagging rules",
                "2. 'tags rules test --dry-run' to test rules",
                "3. 'tags apply --auto' to apply rules",
                "4. 'tags report automation' to track effectiveness"
            ],
            "compliance_workflow": [
                "1. 'tags scan --required-tags Environment,Owner,CostCenter'",
                "2. 'tags apply --interactive' for manual fixes",
                "3. 'tags bulk --service <service>' for bulk fixes",
                "4. 'tags report compliance' to verify compliance"
            ],
            "cost_optimization": [
                "1. 'cost report --tag-key CostCenter' to analyze costs",
                "2. 'cost gaps' to find untagged resource costs",
                "3. 'cost anomalies detect' to find cost spikes",
                "4. 'cost trends' for historical cost analysis"
            ]
        }

        # Quick tips pool
        self.quick_tips = {
            "general": [
                "Use 'interactive' mode for a guided menu-driven experience",
                "Run 'setup validate' regularly to check system health",
                "Use '--help' with any command for detailed information",
                "Commands support '--dry-run' to preview changes safely",
                # "Use TAB completion for faster command entry"
            ],
            "tagging": [
                "Use '--dry-run' to preview tag changes before applying",
                "Create tagging rules to automate repetitive tagging",
                "Set up resource lifecycles to automatically clean up old resources",
                "Use bulk tagging for faster operations on similar resources",
                "Required tags help ensure compliance across your organization"
            ],
            "automation": [
                "Enable workers for background processing and automation",
                "Use Slack integration for approval workflows",
                "Tagging rules can use regex patterns for flexible matching",
                "Auto-tagging runs continuously when workers are active"
            ],
            "performance": [
                "Limit scan regions with '--regions' for faster results",
                "Use '--services' to focus on specific AWS services",
                "Enable Redis caching for improved performance",
                "Use '--limit' to process resources in smaller batches",
                "Discovery results are cached for 24 hours"
            ],
            "troubleshooting": [
                "Use '--verbose' flag for detailed error messages",
                "Check 'setup validate' output for system issues",
                "AWS SSO sessions expire - use 'aws sso login' to refresh",
                "'workers health --auto-fix' resolves most common issues",
                "Service logs are available via 'service logs'"
            ]
        }

    def show_suggestions(self, context: str, data: Optional[Dict[str, Any]] = None,
                        show_workflow: bool = False, workflow_type: Optional[str] = None,
                        show_tip: bool = True) -> None:
        """Display contextual suggestions based on the command context.

        Args:
            context: The command context (e.g., 'tags.scan', 'workers.discover')
            data: Optional data from command execution for dynamic suggestions
            show_workflow: Whether to show workflow suggestions
            workflow_type: Type of workflow to show (initial_setup, daily_operations, etc.)
            show_tip: Whether to show a quick tip
        """
        suggestions = self._get_contextual_suggestions(context, data)

        if not suggestions and not show_workflow and not show_tip:
            return

        # Create the suggestions panel
        content_lines = []

        if suggestions:
            content_lines.append("[bold cyan]Suggested next steps:[/bold cyan]")
            content_lines.append("")

            for i, suggestion in enumerate(suggestions[:4], 1):  # Show top 4 suggestions
                cmd_text = f"[cyan]tag-manager {suggestion['cmd']}[/cyan]"
                desc_text = f"[dim]{suggestion['desc']}[/dim]"
                content_lines.append(f"  {i}. {cmd_text}")
                content_lines.append(f"     {desc_text}")
                if i < min(4, len(suggestions)):
                    content_lines.append("")

        if show_workflow and workflow_type and workflow_type in self.workflow_suggestions:
            if suggestions:
                content_lines.append("")
            content_lines.append(f"[bold yellow]Recommended {workflow_type.replace('_', ' ').title()} Workflow:[/bold yellow]")
            content_lines.append("")
            for step in self.workflow_suggestions[workflow_type]:
                content_lines.append(f"  {step}")

        # Display the panel
        if content_lines:
            panel = Panel(
                "\n".join(content_lines),
                title="[bold green]What to do next[/bold green]",
                border_style="green",
                padding=(1, 2)
            )
            safe_print("")
            self.console.print(panel)

        # Show a quick tip if requested
        if show_tip:
            self.show_quick_tip()

    def _get_contextual_suggestions(self, context: str, data: Optional[Dict[str, Any]] = None) -> List[Dict[str, str]]:
        """Get suggestions based on context and optional execution data.

        Args:
            context: The command context
            data: Optional execution data for dynamic suggestions

        Returns:
            List of suggestion dictionaries
        """
        # Check for data-driven context modifications
        if data:
            # Modify context based on execution results
            if context == "tags.scan" and data.get("untagged_count", 0) == 0:
                context = "tags.scan.no_untagged"
            elif context == "tags.apply" and data.get("success", False):
                context = "tags.apply.success"
            elif context == "workers.discover" and data.get("success", False):
                context = "workers.discover.complete"
            elif context == "workers.discover" and not data.get("success", True):
                context = "workers.discover.failed"
            elif context == "system.validate" and data.get("all_valid", False):
                context = "system.validate.success"
            elif context == "system.validate" and not data.get("all_valid", True):
                context = "system.validate.failed"
            elif context == "setup.validate" and data.get("all_healthy", False):
                context = "setup.validate.success"
            elif context == "setup.validate" and data.get("issues_found", 0) > 0:
                context = "setup.validate.failed"

        # Get base suggestions for the context
        suggestions = self.suggestions_map.get(context, []).copy()

        # Add dynamic suggestions based on execution data
        if data:
            suggestions = self._enhance_suggestions_with_data(context, suggestions, data)

        return suggestions

    def _enhance_suggestions_with_data(self, context: str, base_suggestions: List[Dict[str, str]],
                                      data: Dict[str, Any]) -> List[Dict[str, str]]:
        """Enhance suggestions based on command execution data.

        Args:
            context: The command context
            base_suggestions: Base suggestions for the context
            data: Execution data from the command

        Returns:
            Enhanced list of suggestions
        """
        enhanced = base_suggestions.copy()

        # Context-specific enhancements
        if "tags.scan" in context and data.get("untagged_count", 0) > 0:
            # Customize based on the number of untagged resources
            count = data.get("untagged_count", 0)
            if count > 50:
                enhanced.insert(0, {
                    "cmd": f"tags bulk --service {data.get('top_service', 'ec2')}",
                    "desc": f"Bulk tag {count} untagged resources (start with {data.get('top_service', 'ec2')})"
                })
            elif count > 0:
                enhanced.insert(0, {
                    "cmd": "tags apply --interactive --limit 10",
                    "desc": f"Interactively tag the {min(count, 10)} highest priority resources"
                })

        elif "workers.discover" in context and data.get("discovered_count", 0) > 0:
            enhanced.insert(0, {
                "cmd": "tags scan --limit 50",
                "desc": f"Scan the {data.get('discovered_count')} discovered resources for missing tags"
            })

        elif "tags.apply" in context and data.get("resources_tagged", 0) > 0:
            enhanced.insert(0, {
                "cmd": "tags report audit --last-hours 1",
                "desc": f"Review the {data.get('resources_tagged')} resources you just tagged"
            })

        elif "system.validate" in context and data.get("failed_checks", []):
            for check in data.get("failed_checks", [])[:1]:  # Show fix for first failed check
                if "AWS" in check:
                    enhanced.insert(0, {
                        "cmd": "aws sso login",
                        "desc": "Refresh your AWS credentials"
                    })
                elif "Docker" in check:
                    enhanced.insert(0, {
                        "cmd": "docker start",
                        "desc": "Start Docker services"
                    })

        elif "workers.health" in context and data.get("issues_fixed", 0) > 0:
            enhanced.insert(0, {
                "cmd": "workers status",
                "desc": f"Verify the {data.get('issues_fixed')} issues were resolved"
            })

        elif "update.check" in context and data.get("updates_available", 0) > 0:
            enhanced.insert(0, {
                "cmd": "update install",
                "desc": f"Install {data.get('updates_available')} available update(s)"
            })

        return enhanced

    def show_quick_tip(self, tip_type: str = "general") -> None:
        """Show a quick tip to help users.

        Args:
            tip_type: Type of tip to show (general, tagging, automation, etc.)
        """
        import random

        # Select tip category based on context
        if tip_type not in self.quick_tips:
            # Randomly select a category
            categories = list(self.quick_tips.keys())
            tip_type = random.choice(categories)

        selected_tips = self.quick_tips.get(tip_type, self.quick_tips["general"])
        tip = random.choice(selected_tips)

        safe_print(f"\n[dim][bold]Pro tip:[/bold] {tip}[/dim]")

    def show_error_recovery(self, error_context: str, error_message: str) -> None:
        """Show recovery suggestions when an error occurs.

        Args:
            error_context: Context where the error occurred
            error_message: The error message
        """
        recovery_suggestions = {
            "aws_auth": [
                {"cmd": "system validate", "desc": "Check AWS configuration"},
                {"cmd": "aws sso login", "desc": "Refresh AWS SSO session"},
                {"cmd": "setup wizard", "desc": "Reconfigure AWS access"}
            ],
            "database": [
                {"cmd": "database migrate", "desc": "Run database migrations"},
                {"cmd": "database status", "desc": "Check database status"},
                {"cmd": "docker restart", "desc": "Restart database container"}
            ],
            "workers": [
                {"cmd": "workers health --auto-fix", "desc": "Auto-fix worker issues"},
                {"cmd": "workers restart", "desc": "Restart worker processes"},
                {"cmd": "setup validate", "desc": "Check service health"}
            ],
            "slack": [
                {"cmd": "slack setup", "desc": "Reconfigure Slack integration"},
                {"cmd": "slack test", "desc": "Test Slack connection"},
                {"cmd": "setup validate", "desc": "Check system status"}
            ],
            "docker": [
                {"cmd": "docker start", "desc": "Start Docker services"},
                {"cmd": "docker status", "desc": "Check Docker status"},
                {"cmd": "setup validate", "desc": "Check all services"}
            ],
            "permission": [
                {"cmd": "sudo tag-manager <command>", "desc": "Run with elevated privileges"},
                {"cmd": "system validate", "desc": "Check permissions"},
                {"cmd": "setup wizard", "desc": "Reconfigure with correct permissions"}
            ]
        }

        suggestions = recovery_suggestions.get(error_context, [
            {"cmd": "setup validate", "desc": "Run system validation"},
            {"cmd": "--help", "desc": "View command help"},
            {"cmd": "setup wizard", "desc": "Check system configuration"}
        ])

        content_lines = [
            f"[bold red]Error:[/bold red] {error_message}",
            "",
            "[bold yellow]Suggested recovery steps:[/bold yellow]",
            ""
        ]

        for i, suggestion in enumerate(suggestions, 1):
            cmd_text = f"[cyan]tag-manager {suggestion['cmd']}[/cyan]"
            desc_text = f"[dim]{suggestion['desc']}[/dim]"
            content_lines.append(f"  {i}. {cmd_text}: {desc_text}")

        panel = Panel(
            "\n".join(content_lines),
            title="[bold red]Error Recovery[/bold red]",
            border_style="red",
            padding=(1, 2)
        )
        safe_print("")
        self.console.print(panel)

    def show_workflow_prompt(self, workflow_type: str) -> bool:
        """Prompt user to follow a suggested workflow.

        Args:
            workflow_type: The type of workflow to suggest

        Returns:
            True if user wants to follow the workflow
        """
        from rich.prompt import Confirm

        if workflow_type in self.workflow_suggestions:
            safe_print(f"\n[bold yellow]Would you like to follow the {workflow_type.replace('_', ' ')} workflow?[/bold yellow]")
            return Confirm.ask("Start guided workflow", default=True)
        return False


# Singleton instance
command_suggestions = CommandSuggestions()


def show_suggestions(context: str, **kwargs) -> None:
    """Convenience function to show suggestions.

    Args:
        context: The command context
        **kwargs: Additional arguments passed to show_suggestions
    """
    command_suggestions.show_suggestions(context, **kwargs)


def show_quick_tip(tip_type: str = "general") -> None:
    """Convenience function to show a quick tip.

    Args:
        tip_type: Type of tip to show
    """
    command_suggestions.show_quick_tip(tip_type)


def show_error_recovery(error_context: str, error_message: str) -> None:
    """Convenience function to show error recovery suggestions.

    Args:
        error_context: Context where the error occurred
        error_message: The error message
    """
    command_suggestions.show_error_recovery(error_context, error_message)