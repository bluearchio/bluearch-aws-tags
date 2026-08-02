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

    PUBLIC_COMMAND_ROOTS = frozenset(
        {
            "--help",
            "--version",
            "ask",
            "cost",
            "discover",
            "interactive",
            "lifecycle",
            "policy",
            "setup",
            "uninstall",
            "update",
            "web",
        }
    )

    def __init__(self):
        self.console = Console()

        # Every command below is a suffix that the renderer prefixes with the
        # public executable name. Keep the first token on the registered public
        # CLI surface; dormant legacy contexts are intentionally redirected to
        # the supported lifecycle, policy, discovery, setup, and cost flows.
        self.suggestions_map = {
            "tags.scan": [
                {"cmd": "lifecycle wizard", "desc": "Start the guided lifecycle and tagging workflow"},
                {"cmd": "lifecycle set-ttl --dry-run", "desc": "Preview supported TTL tag changes"},
                {"cmd": "lifecycle policies create", "desc": "Create a lifecycle policy"},
                {"cmd": "policy check-compliance --details", "desc": "Review organization tag-policy compliance"},
            ],
            "tags.scan.no_untagged": [
                {"cmd": "policy check-compliance --details", "desc": "Generate a detailed compliance view"},
                {"cmd": "lifecycle policies list", "desc": "Review lifecycle policies"},
                {"cmd": "lifecycle review", "desc": "Review resources with active TTLs"},
                {"cmd": "discover all", "desc": "Refresh resource discovery"},
            ],
            "tags.apply.success": [
                {"cmd": "lifecycle scan", "desc": "Verify current resource lifecycle state"},
                {"cmd": "lifecycle review", "desc": "Review resources with TTLs"},
                {"cmd": "policy check-compliance --details", "desc": "Check tag-policy compliance"},
                {"cmd": "setup validate", "desc": "Validate the public runtime"},
            ],
            "tags.bulk.complete": [
                {"cmd": "lifecycle scan", "desc": "Verify current lifecycle state"},
                {"cmd": "policy check-compliance --details", "desc": "Check compliance after changes"},
                {"cmd": "lifecycle set-ttl --ttl-days 30 --dry-run", "desc": "Preview 30-day TTL changes"},
                {"cmd": "lifecycle wizard", "desc": "Continue with the guided workflow"},
            ],
            "tags.rules.created": [
                {"cmd": "lifecycle set-ttl --dry-run", "desc": "Preview the policy before applying TTL tags"},
                {"cmd": "lifecycle policies list", "desc": "Review lifecycle policies"},
                {"cmd": "lifecycle scan", "desc": "Find resources matching policies"},
                {"cmd": "lifecycle wizard", "desc": "Continue with the guided workflow"},
            ],
            "tags.rules.list": [
                {"cmd": "lifecycle policies list", "desc": "Review lifecycle policies"},
                {"cmd": "lifecycle policies create", "desc": "Create a lifecycle policy"},
                {"cmd": "lifecycle set-ttl --dry-run", "desc": "Preview policy-driven TTL changes"},
                {"cmd": "lifecycle scan", "desc": "Find matching resources"},
            ],
            "tags.lifecycle.set": [
                {"cmd": "lifecycle policies list", "desc": "View lifecycle policies"},
                {"cmd": "lifecycle delete --dry-run", "desc": "Preview expired-resource cleanup"},
                {"cmd": "lifecycle review", "desc": "Review resource lifecycle state"},
                {"cmd": "lifecycle scan --expiring 30", "desc": "Find resources expiring within 30 days"},
            ],
            "tags.report.compliance": [
                {"cmd": "policy check-compliance --details", "desc": "Inspect non-compliant resources"},
                {"cmd": "lifecycle wizard", "desc": "Use the supported guided remediation flow"},
                {"cmd": "lifecycle set-ttl --noncompliant --dry-run", "desc": "Preview TTL changes for non-compliant resources"},
                {"cmd": "cost report --tag-key CostCenter", "desc": "Analyze costs by tags"},
            ],
            "tags.status": [
                {"cmd": "setup validate", "desc": "Check public runtime health"},
                {"cmd": "lifecycle scan", "desc": "Inspect lifecycle resources"},
                {"cmd": "lifecycle review", "desc": "Review current TTL decisions"},
                {"cmd": "discover all", "desc": "Refresh resource inventory"},
            ],
            "workers.discover.complete": [
                {"cmd": "lifecycle scan", "desc": "View discovered lifecycle resources"},
                {"cmd": "policy check-compliance --details", "desc": "Check organization tag compliance"},
                {"cmd": "lifecycle wizard", "desc": "Start the guided workflow"},
                {"cmd": "discover all", "desc": "Refresh resource discovery"},
            ],
            "workers.discover.failed": [
                {"cmd": "setup validate", "desc": "Validate AWS connectivity"},
                {"cmd": "setup doctor", "desc": "Diagnose the installation"},
                {"cmd": "setup wizard", "desc": "Reconfigure AWS access"},
                {"cmd": "discover all", "desc": "Retry public resource discovery"},
            ],
            "workers.start.success": [
                {"cmd": "setup validate", "desc": "Verify runtime health"},
                {"cmd": "discover all", "desc": "Refresh resource inventory"},
                {"cmd": "lifecycle scan", "desc": "Scan lifecycle resources"},
            ],
            "workers.stop.success": [
                {"cmd": "setup validate", "desc": "Verify runtime health"},
                {"cmd": "web status", "desc": "Check the managed web dashboard"},
                {"cmd": "lifecycle scan", "desc": "Continue with synchronous lifecycle operations"},
            ],
            "workers.status.healthy": [
                {"cmd": "lifecycle scan", "desc": "Scan resources"},
                {"cmd": "lifecycle set-ttl --dry-run", "desc": "Preview TTL changes"},
                {"cmd": "lifecycle review", "desc": "Review expiring resources"},
            ],
            "workers.status.issues": [
                {"cmd": "setup validate", "desc": "Run system validation"},
                {"cmd": "setup doctor", "desc": "Diagnose installation issues"},
                {"cmd": "setup wizard", "desc": "Repair configuration"},
            ],
            "workers.health.fixed": [
                {"cmd": "setup validate", "desc": "Verify everything is working"},
                {"cmd": "lifecycle scan", "desc": "Resume lifecycle operations"},
                {"cmd": "lifecycle set-ttl --dry-run", "desc": "Preview supported TTL changes"},
            ],
            "system.validate.success": [
                {"cmd": "lifecycle scan", "desc": "Scan AWS resources"},
                {"cmd": "lifecycle wizard", "desc": "Start guided workflow"},
                {"cmd": "setup wizard", "desc": "Run interactive setup wizard"},
            ],
            "system.validate.failed": [
                {"cmd": "setup wizard", "desc": "Run guided setup to fix issues"},
                {"cmd": "setup validate", "desc": "Run validation checks"},
                {"cmd": "setup doctor", "desc": "Review installation diagnostics"},
                {"cmd": "setup aws", "desc": "Reconfigure AWS credentials"},
            ],
            "system.status": [
                {"cmd": "setup validate", "desc": "Run system validation"},
                {"cmd": "web status", "desc": "Check the managed dashboard"},
                {"cmd": "lifecycle scan", "desc": "Check lifecycle resources"},
                {"cmd": "update --check", "desc": "Check for updates"},
            ],
            "setup.wizard.complete": [
                {"cmd": "setup validate", "desc": "Verify setup completed successfully"},
                {"cmd": "lifecycle wizard", "desc": "Complete guided lifecycle workflow"},
                {"cmd": "lifecycle scan", "desc": "Scan and discover resources"},
            ],
            "setup.wizard.skipped_notifications": [
                {"cmd": "lifecycle scan", "desc": "Scan and discover resources"},
                {"cmd": "lifecycle wizard", "desc": "Complete guided lifecycle workflow"},
                {"cmd": "setup validate", "desc": "Verify system health"},
            ],
            "update.check.available": [
                {"cmd": "update --yes", "desc": "Install the latest public release"},
                {"cmd": "update --check", "desc": "Recheck public release metadata"},
                {"cmd": "setup validate", "desc": "Check current system health"},
            ],
            "update.check.current": [
                {"cmd": "lifecycle scan", "desc": "Continue with lifecycle management"},
                {"cmd": "web status", "desc": "Check the managed dashboard"},
                {"cmd": "setup validate", "desc": "Run health checks"},
            ],
            "update.install.success": [
                {"cmd": "setup validate", "desc": "Verify update successful"},
                {"cmd": "--version", "desc": "Check new version"},
                {"cmd": "web status", "desc": "Check the Core-managed dashboard"},
                {"cmd": "lifecycle scan", "desc": "Verify lifecycle operations"},
            ],
            "docker.start.success": [
                {"cmd": "setup validate", "desc": "Check service health"},
                {"cmd": "web status", "desc": "Verify the managed dashboard"},
                {"cmd": "lifecycle scan", "desc": "Begin lifecycle operations"},
            ],
            "docker.stop.success": [
                {"cmd": "setup validate", "desc": "Check public runtime health"},
                {"cmd": "web status", "desc": "Check the managed dashboard"},
            ],
            "database.migrate.success": [
                {"cmd": "setup database", "desc": "Check Core-owned database setup"},
                {"cmd": "setup validate", "desc": "Verify system health"},
                {"cmd": "lifecycle scan", "desc": "Resume lifecycle operations"},
            ],
            "database.reset.success": [
                {"cmd": "setup database", "desc": "Initialize the Core-owned database"},
                {"cmd": "lifecycle scan", "desc": "Scan resources"},
                {"cmd": "setup wizard", "desc": "Reconfigure if needed"},
            ],
            "setup.validate.success": [
                {"cmd": "lifecycle scan", "desc": "Scan resources"},
                {"cmd": "lifecycle wizard", "desc": "Complete guided workflow"},
                {"cmd": "lifecycle set-ttl --dry-run", "desc": "Preview TTL changes"},
                {"cmd": "lifecycle review", "desc": "Review expiring resources"},
            ],
            "setup.validate.failed": [
                {"cmd": "setup wizard", "desc": "Fix configuration issues"},
                {"cmd": "setup aws", "desc": "Refresh AWS configuration"},
                {"cmd": "setup doctor", "desc": "Check installation components"},
                {"cmd": "setup validate", "desc": "Rerun validation"},
            ],
            "first_time": [
                {"cmd": "setup wizard", "desc": "Complete guided setup (recommended)"},
                {"cmd": "setup validate", "desc": "Check your AWS configuration"},
                {"cmd": "interactive", "desc": "Use menu-driven interface"},
                {"cmd": "--help", "desc": "View all available commands"},
            ],
            "interactive.exit": [
                {"cmd": "policy check-compliance --details", "desc": "Check tag-policy compliance"},
                {"cmd": "lifecycle scan", "desc": "Review lifecycle resources"},
                {"cmd": "setup validate", "desc": "Run system validation"},
            ],
            "cost.analysis.complete": [
                {"cmd": "cost report --tag-key CostCenter", "desc": "Generate a detailed cost-allocation report"},
                {"cmd": "cost gaps", "desc": "Find costs that lack allocation tags"},
                {"cmd": "policy check-compliance --details", "desc": "Check CostCenter tag-policy compliance"},
                {"cmd": "lifecycle wizard", "desc": "Start the supported lifecycle workflow"},
            ],
        }

        # Define workflow-based suggestions
        self.workflow_suggestions = {
            "initial_setup": [
                "1. Run 'bluearch-aws-tags setup wizard' for complete guided setup",
                "2. Use 'bluearch-aws-tags discover all' to discover AWS resources",
                "3. Check with 'bluearch-aws-tags setup validate' to verify everything works",
                "4. Start with 'bluearch-aws-tags lifecycle wizard'",
            ],
            "daily_operations": [
                "- 'bluearch-aws-tags lifecycle scan' to scan resources",
                "- 'bluearch-aws-tags lifecycle scan --expiring 7' to find expiring resources",
                "- 'bluearch-aws-tags lifecycle review' to review and manage resources",
                "- 'bluearch-aws-tags setup validate' to check system health",
            ],
            "troubleshooting": [
                "- 'bluearch-aws-tags setup validate' for detailed system checks",
                "- 'bluearch-aws-tags setup doctor' for installation diagnostics",
                "- 'bluearch-aws-tags setup aws' to reconfigure AWS access",
                "- 'bluearch-aws-tags update --check' to check for fixes",
            ],
            "automation_setup": [
                "1. 'bluearch-aws-tags lifecycle policies create' to define lifecycle rules",
                "2. 'bluearch-aws-tags lifecycle scan' to find matching resources",
                "3. 'bluearch-aws-tags lifecycle set-ttl --dry-run' to preview changes",
                "4. 'bluearch-aws-tags lifecycle review' to monitor lifecycle state",
            ],
            "compliance_workflow": [
                "1. 'bluearch-aws-tags policy check-compliance --details' to inspect violations",
                "2. 'bluearch-aws-tags lifecycle scan --check-compliance' to correlate lifecycle state",
                "3. 'bluearch-aws-tags lifecycle set-ttl --noncompliant --dry-run' to preview TTL changes",
                "4. 'bluearch-aws-tags policy check-compliance --details' to verify compliance",
            ],
            "cost_optimization": [
                "1. 'bluearch-aws-tags cost report --tag-key CostCenter' to analyze costs",
                "2. 'bluearch-aws-tags cost gaps' to find untagged resource costs",
                "3. 'bluearch-aws-tags cost anomalies detect' to find cost spikes",
                "4. 'bluearch-aws-tags cost trends' for historical cost analysis",
            ],
        }

        # Quick tips pool
        self.quick_tips = {
            "general": [
                "Use 'bluearch-aws-tags interactive' for a guided menu-driven experience",
                "Run 'bluearch-aws-tags setup validate' regularly to check system health",
                "Use 'bluearch-aws-tags --help' for detailed command information",
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
                "Use bluearch-aws-core to run shared local services",
                "Use lifecycle webhook notifications for expiration alerts",
                "Create lifecycle policies for repeatable resource rules",
                "Preview policy-driven TTL changes with --dry-run",
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
                "Check 'bluearch-aws-tags setup validate' output for system issues",
                "Use 'bluearch-aws-tags setup aws' to refresh AWS configuration",
                "Run 'bluearch-aws-tags setup doctor' for installation diagnostics",
                "Check managed dashboard state with 'bluearch-aws-tags web status'",
            ]
        }

    @classmethod
    def _public_command(cls, command: str) -> str:
        """Prefix only command suffixes rooted on the registered public CLI."""
        root = command.split(maxsplit=1)[0] if command.strip() else ""
        if root not in cls.PUBLIC_COMMAND_ROOTS:
            raise ValueError(f"Unregistered public command suggestion: {command}")
        return f"bluearch-aws-tags {command}"

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
                cmd_text = f"[cyan]{self._public_command(suggestion['cmd'])}[/cyan]"
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
                    "cmd": f"lifecycle set-ttl --services {data.get('top_service', 'ec2')} --dry-run",
                    "desc": f"Preview TTL changes for {count} resources (starting with {data.get('top_service', 'ec2')})"
                })
            elif count > 0:
                enhanced.insert(0, {
                    "cmd": "lifecycle wizard",
                    "desc": f"Review the {min(count, 10)} highest-priority resources in the guided workflow"
                })

        elif "workers.discover" in context and data.get("discovered_count", 0) > 0:
            enhanced.insert(0, {
                "cmd": "lifecycle scan",
                "desc": f"Scan the {data.get('discovered_count')} discovered resources for lifecycle state"
            })

        elif "tags.apply" in context and data.get("resources_tagged", 0) > 0:
            enhanced.insert(0, {
                "cmd": "lifecycle review --include-active",
                "desc": f"Review the {data.get('resources_tagged')} resources you just updated"
            })

        elif "system.validate" in context and data.get("failed_checks", []):
            for check in data.get("failed_checks", [])[:1]:  # Show fix for first failed check
                if "AWS" in check:
                    enhanced.insert(0, {
                        "cmd": "setup aws",
                        "desc": "Refresh your AWS configuration"
                    })
                elif "Docker" in check:
                    enhanced.insert(0, {
                        "cmd": "setup doctor",
                        "desc": "Diagnose the local installation"
                    })

        elif "workers.health" in context and data.get("issues_fixed", 0) > 0:
            enhanced.insert(0, {
                "cmd": "setup validate",
                "desc": f"Verify the {data.get('issues_fixed')} issues were resolved"
            })

        elif "update.check" in context and data.get("updates_available", 0) > 0:
            enhanced.insert(0, {
                "cmd": "update --yes",
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
                {"cmd": "setup validate", "desc": "Check AWS configuration"},
                {"cmd": "setup aws", "desc": "Refresh AWS configuration"},
                {"cmd": "setup wizard", "desc": "Reconfigure AWS access"},
            ],
            "database": [
                {"cmd": "setup database", "desc": "Run Core-owned database setup"},
                {"cmd": "setup doctor", "desc": "Check database integration"},
                {"cmd": "setup validate", "desc": "Validate runtime health"},
            ],
            "workers": [
                {"cmd": "setup validate", "desc": "Check service health"},
                {"cmd": "discover all", "desc": "Refresh resource discovery"},
                {"cmd": "lifecycle scan", "desc": "Use synchronous lifecycle scanning"},
            ],
            "docker": [
                {"cmd": "setup doctor", "desc": "Diagnose the local installation"},
                {"cmd": "web status", "desc": "Check the Core-managed dashboard"},
                {"cmd": "setup validate", "desc": "Check all services"},
            ],
            "permission": [
                {"cmd": "setup validate", "desc": "Check permissions"},
                {"cmd": "setup doctor", "desc": "Review installation diagnostics"},
                {"cmd": "setup wizard", "desc": "Reconfigure with correct permissions"},
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
            cmd_text = f"[cyan]{self._public_command(suggestion['cmd'])}[/cyan]"
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
