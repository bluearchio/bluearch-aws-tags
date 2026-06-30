"""Example of integrating Tag Manager CLI as a plugin into another CLI."""

import typer
from tag_manager_cli.plugin import register_with_parent_cli, PluginInterface

# Example 1: Simple integration
def simple_integration_example():
    """Simple way to integrate Tag Manager CLI."""
    
    # Create your main CLI application
    main_app = typer.Typer(name="my-aws-tools")
    
    # Add some existing commands
    @main_app.command()
    def deploy():
        """Deploy application to AWS."""
        print("Deploying application...")
    
    @main_app.command()
    def status():
        """Check application status."""
        print("Checking status...")
    
    # Register Tag Manager as a subcommand
    register_with_parent_cli(main_app, "tags")
    
    return main_app


# Example 2: Advanced integration using PluginInterface
def advanced_integration_example():
    """Advanced integration with more control."""
    
    main_app = typer.Typer(name="enterprise-aws-cli")
    
    # Initialize the plugin interface
    tag_manager_plugin = PluginInterface("enterprise-aws-cli")
    
    # Get plugin information
    plugin_info = tag_manager_plugin.get_commands_info()
    print(f"Integrating plugin: {plugin_info['name']} v{plugin_info['version']}")
    
    # Add existing commands
    @main_app.command()
    def info():
        """Show CLI information including plugins."""
        typer.echo("Enterprise AWS CLI")
        typer.echo(f"Plugin: {plugin_info['name']} - {plugin_info['description']}")
        typer.echo("Available modules:")
        for module in plugin_info['modules']:
            typer.echo(f"  - {module}")
    
    # Add the Tag Manager plugin
    tag_manager_plugin.add_to_parent(main_app, "tag-manager")
    
    return main_app


# Example 3: Multiple CLI tools with Tag Manager
def multi_tool_integration_example():
    """Example showing Tag Manager integrated into multiple tools."""
    
    # Tool 1: DevOps CLI
    devops_cli = typer.Typer(name="devops-tools")
    
    @devops_cli.command()
    def ci_cd():
        """CI/CD pipeline management."""
        print("Managing CI/CD...")
    
    register_with_parent_cli(devops_cli, "tags")
    
    # Tool 2: FinOps CLI
    finops_cli = typer.Typer(name="finops-tools")
    
    @finops_cli.command()
    def budget():
        """Budget management."""
        print("Managing budgets...")
    
    register_with_parent_cli(finops_cli, "tag-manager")
    
    return devops_cli, finops_cli


if __name__ == "__main__":
    # Run the simple integration example
    app = simple_integration_example()
    
    # Now you can use commands like:
    # python parent_cli_integration.py deploy
    # python parent_cli_integration.py status
    # python parent_cli_integration.py tags interactive
    # python parent_cli_integration.py cost report --tag-key Environment
    
    app()