"""Plugin integration system for Tag Manager CLI."""

import typer
from typing import Optional
from .main import app as tag_manager_app


def create_plugin_app() -> typer.Typer:
    """Create a plugin-compatible version of the Tag Manager CLI.
    
    This function returns a Typer app that can be integrated
    into another CLI as a subcommand.
    """
    plugin_app = typer.Typer(
        name="tag-manager",
        help="AWS Tag Manager - Manage AWS tags and related functionality",
        no_args_is_help=False
    )
    
    # Add all commands from the main app
    for command_name, command_info in tag_manager_app.registered_commands.items():
        plugin_app.registered_commands[command_name] = command_info
    
    # Add all groups from the main app
    for group_name, group_info in tag_manager_app.registered_groups.items():
        plugin_app.registered_groups[group_name] = group_info
    
    return plugin_app


def register_with_parent_cli(parent_app: typer.Typer, command_name: str = "tag-manager"):
    """Register Tag Manager as a subcommand of another CLI.
    
    Args:
        parent_app: The parent Typer application
        command_name: The name to use for the subcommand (default: "tag-manager")
    
    Example:
        from tag_manager_cli.plugin import register_with_parent_cli
        import typer
        
        main_app = typer.Typer()
        register_with_parent_cli(main_app, "tags")
        
        # Now 'tags' command will be available in main_app
    """
    plugin_app = create_plugin_app()
    parent_app.add_typer(plugin_app, name=command_name)


class PluginInterface:
    """Interface for integrating Tag Manager CLI as a plugin."""
    
    def __init__(self, parent_cli_name: str = "main-cli"):
        self.parent_cli_name = parent_cli_name
        self.plugin_app = create_plugin_app()
    
    def get_app(self) -> typer.Typer:
        """Get the plugin app instance."""
        return self.plugin_app
    
    def add_to_parent(self, parent_app: typer.Typer, command_name: str = "tag-manager"):
        """Add this plugin to a parent CLI application."""
        parent_app.add_typer(self.plugin_app, name=command_name)
    
    def get_commands_info(self) -> dict:
        """Get information about available commands."""
        return {
            "name": "tag-manager",
            "description": "AWS Tag Manager CLI",
            "version": "LOCAL",
            "commands": [
                {
                    "name": "interactive",
                    "description": "Start interactive Tag Manager CLI"
                },
                {
                    "name": "cost",
                    "description": "FinOps cost analysis (CUR-powered chargeback, gaps, anomalies)"
                },
                {
                    "name": "version",
                    "description": "Show version information"
                }
            ],
            "modules": [
                "FinOps Cost Analysis (CUR-powered)",
                "Resource Organization",
                "Automation & Operations",
                "Access Control (IAM Conditions)",
                "Monitoring & Alerting",
                "Security & Compliance",
                "Governance & Policy Enforcement"
            ]
        }


# Example integration function for common parent CLIs
def integrate_with_aws_cli():
    """Example integration with AWS CLI (conceptual)."""
    # This would be used if integrating with the official AWS CLI
    # Implementation would depend on the specific parent CLI architecture
    pass


def integrate_with_custom_cli(parent_app: typer.Typer):
    """Integrate with a custom CLI application."""
    register_with_parent_cli(parent_app, "tag-manager")
    return parent_app


# Export the main functions for external use
__all__ = [
    'create_plugin_app',
    'register_with_parent_cli',
    'PluginInterface',
    'integrate_with_custom_cli'
]