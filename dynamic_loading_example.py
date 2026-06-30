#!/usr/bin/env python3
"""
Dynamic Command Loading Example for Typer
Demonstrates how to implement lazy/dynamic loading of commands to improve CLI startup performance.
"""

import importlib
import sys
from typing import Optional, Any
import typer
from pathlib import Path

# Main app - lightweight initialization
app = typer.Typer()

# Command registry - maps command names to module paths
COMMAND_REGISTRY = {
    'tags': {
        'module': 'tag_manager_cli.commands.unified_tags',
        'app_name': 'tags_app',
        'help': 'Complete tag management (scan, apply, automate, report)'
    },
    'discover': {
        'module': 'tag_manager_cli.commands.discovery_commands',
        'app_name': 'discover_app',
        'help': 'Discover and analyze AWS resources'
    },
    'policy': {
        'module': 'tag_manager_cli.commands.policy_commands',
        'app_name': 'app',
        'help': 'AWS Organizations tag policy management'
    },
    'ai': {
        'module': 'tag_manager_cli.commands.ai_commands',
        'app_name': 'app',
        'help': 'AI-powered AWS assistant'
    },
    'setup': {
        'module': 'tag_manager_cli.commands.setup_commands',
        'app_name': 'setup_app',
        'help': 'Setup wizard and configuration'
    },
    'dev': {
        'module': 'tag_manager_cli.commands.dev_commands',
        'app_name': 'dev_app',
        'help': 'Development tools and utilities'
    },
    'tasks': {
        'module': 'tag_manager_cli.commands.task_commands',
        'app_name': 'task_app',
        'help': 'Task management and scheduling'
    },
    'update': {
        'module': 'tag_manager_cli.commands.update_commands',
        'app_name': 'app',
        'help': 'Update Tag Manager CLI'
    }
}

# Lazy loading cache
_loaded_commands = {}


def load_command_app(command_name: str) -> Optional[typer.Typer]:
    """Dynamically load a command module and return its Typer app."""
    if command_name in _loaded_commands:
        return _loaded_commands[command_name]

    if command_name not in COMMAND_REGISTRY:
        return None

    cmd_info = COMMAND_REGISTRY[command_name]

    try:
        # Dynamically import the module
        module = importlib.import_module(cmd_info['module'])
        # Get the Typer app from the module
        command_app = getattr(module, cmd_info['app_name'])

        # Cache for future use
        _loaded_commands[command_name] = command_app

        return command_app
    except (ImportError, AttributeError) as e:
        typer.echo(f"Error loading command '{command_name}': {e}", err=True)
        return None


def create_dynamic_command(cmd_name: str, cmd_info: dict):
    """Create a dynamic command that loads its implementation on demand."""

    def dynamic_callback(ctx: typer.Context):
        """Dynamically load and execute the actual command."""
        # Load the command module
        command_app = load_command_app(cmd_name)

        if command_app:
            # Get the remaining arguments after the command name
            args = ctx.args

            # Invoke the loaded command app with the arguments
            # This is a simplified approach - in production, you'd need more robust argument handling
            try:
                # Create a new context for the subcommand
                command_app(args, standalone_mode=False)
            except Exception as e:
                typer.echo(f"Error executing command '{cmd_name}': {e}", err=True)
                raise typer.Exit(1)
        else:
            typer.echo(f"Command '{cmd_name}' could not be loaded.", err=True)
            raise typer.Exit(1)

    # Set the help text from registry
    dynamic_callback.__doc__ = cmd_info.get('help', f"Execute {cmd_name} command")

    return dynamic_callback


# Alternative Approach: Lazy Registration with Callback
@app.callback()
def main(
    ctx: typer.Context,
    version: bool = typer.Option(False, "--version", "-V", help="Show version"),
):
    """AWS Tag Manager CLI - Dynamic Loading Example"""

    if version:
        # Only import version when needed
        typer.echo("AWS Tag Manager CLI v1.0.0 (Dynamic Loading)")
        raise typer.Exit()

    # Check if a command was invoked
    if ctx.invoked_subcommand is None and ctx.args:
        # Try to load the command dynamically
        command_name = ctx.args[0] if ctx.args else None

        if command_name and command_name in COMMAND_REGISTRY:
            # Load and register the command on-demand
            command_app = load_command_app(command_name)
            if command_app:
                # Add the command to the main app
                app.add_typer(command_app, name=command_name)
                # Re-invoke with the loaded command
                ctx.invoke(command_app)


# Most Efficient Approach: Override invoke() method
class DynamicTyper(typer.Typer):
    """Custom Typer class that supports dynamic command loading."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._dynamic_commands = {}

    def add_dynamic_command(self, name: str, module: str, app_name: str, help_text: str = None):
        """Register a command for dynamic loading."""
        self._dynamic_commands[name] = {
            'module': module,
            'app_name': app_name,
            'help': help_text
        }

    def invoke(self, ctx):
        """Override invoke to handle dynamic command loading."""
        # Check if we need to load a command
        if ctx.protected and ctx.protected.get('args'):
            cmd_name = ctx.protected['args'][0] if ctx.protected['args'] else None

            if cmd_name in self._dynamic_commands and cmd_name not in self.registered_commands:
                # Load the command dynamically
                cmd_info = self._dynamic_commands[cmd_name]
                try:
                    module = importlib.import_module(cmd_info['module'])
                    command_app = getattr(module, cmd_info['app_name'])

                    # Register the command
                    self.add_typer(command_app, name=cmd_name)
                except (ImportError, AttributeError) as e:
                    typer.echo(f"Error loading command '{cmd_name}': {e}", err=True)

        # Call the parent invoke
        return super().invoke(ctx)


# Example Usage: Production-Ready Dynamic Loading
def create_optimized_cli():
    """Create an optimized CLI with dynamic command loading."""

    # Use custom Typer class
    app = DynamicTyper(
        help="AWS Tag Manager CLI - Optimized with Dynamic Loading"
    )

    # Register commands for dynamic loading (no imports!)
    for cmd_name, cmd_info in COMMAND_REGISTRY.items():
        app.add_dynamic_command(
            name=cmd_name,
            module=cmd_info['module'],
            app_name=cmd_info['app_name'],
            help_text=cmd_info['help']
        )

    @app.callback()
    def callback(
        version: bool = typer.Option(False, "--version", "-V", help="Show version"),
    ):
        """AWS Tag Manager CLI - Performance Optimized"""
        if version:
            typer.echo("AWS Tag Manager CLI v1.0.0")
            raise typer.Exit()

    return app


# Simplest Working Approach: Conditional Import in Commands
def create_simple_dynamic_cli():
    """Simplest approach using conditional imports."""

    app = typer.Typer()

    @app.command()
    def tags(ctx: typer.Context):
        """Tag management commands."""
        # Import only when this command is invoked
        from tag_manager_cli.commands.unified_tags import tags_app
        # Pass control to the actual command
        return tags_app(ctx.args)

    @app.command()
    def discover(ctx: typer.Context):
        """Discover AWS resources."""
        # Import only when this command is invoked
        from tag_manager_cli.commands.discovery_commands import discover_app
        return discover_app(ctx.args)

    # ... repeat for other commands

    return app


if __name__ == "__main__":
    # Choose your approach:

    # Approach 1: Simple conditional imports
    # app = create_simple_dynamic_cli()

    # Approach 2: Custom Typer class (most elegant)
    app = create_optimized_cli()

    # Run the app
    app()