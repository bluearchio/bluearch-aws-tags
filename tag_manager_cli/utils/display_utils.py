"""Display utilities for package-compatible Rich table rendering."""

import sys
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from typing import List, Tuple, Optional, Dict, Any

# Ensure console can handle UTF-8 characters (like your working BlueArch CLI)
try:
    sys.stdout.reconfigure(encoding='utf-8')
except (AttributeError, Exception):
    pass

# Configure console exactly like your working BlueArch CLI
console = Console()


def create_binary_safe_table(
    title: str,
    headers: List[str],
    rows: List[List[str]],
    header_style: str = "bold magenta",
    show_lines: bool = True,
    column_styles: Optional[List[str]] = None,
    column_widths: Optional[List[int]] = None
) -> Table:
    """
    Create a Rich table using exactly the same pattern as working BlueArch CLI.
    """
    table = Table(
        show_header=True,
        header_style=header_style,
        show_lines=show_lines  # This matches your working CLI exactly
    )
    
    # Add columns with optional styling and widths
    for i, header in enumerate(headers):
        style = column_styles[i] if column_styles and i < len(column_styles) else "dim"
        width = column_widths[i] if column_widths and i < len(column_widths) else None
        table.add_column(header, style=style, width=width)
    
    # Add rows
    for row in rows:
        table.add_row(*row)
    
    # Set title after table is configured (like BlueArch CLI)
    if title:
        table.title = title
    
    return table


def display_main_menu():
    """Display the main menu options using package-compatible table."""
    headers = ["Option", "Feature", "Description"]
    rows = [
        ["1", "FinOps Cost Analysis", "CUR-powered chargeback reports, tagging gaps, anomaly detection"],
        ["2", "Resource Organization", "Organize and categorize AWS resources using tags"],
        ["3", "Development Tools", "Test components, debug workers, development utilities"],
        ["q", "Quit", "Exit the application"]
    ]
    
    column_styles = ["cyan", "white", "dim white"]
    column_widths = [8, 40, None]
    
    table = create_binary_safe_table(
        title="AWS Tag Manager - Main Menu",
        headers=headers,
        rows=rows,
        column_styles=column_styles,
        column_widths=column_widths
    )
    
    console.print(table)
    console.print("\n")


def display_system_status_table(status_data: List[Tuple[str, str, str]]):
    """Display system status using package-compatible table."""
    headers = ["Component", "Status", "Details"]
    rows = [[component, status, details] for component, status, details in status_data]
    
    table = create_binary_safe_table(
        title="System Status",
        headers=headers,
        rows=rows,
        column_styles=["white", "cyan", "dim"],
        column_widths=[20, 15, 30]
    )
    
    console.print(table)


def display_validation_results(validation_results: List[Tuple[str, bool, str]]):
    """Display validation results using package-compatible table."""
    headers = ["Component", "Status", "Details"]
    rows = []
    
    for component, passed, details in validation_results:
        status_icon = "OK" if passed else "ERROR"
        status_color = "green" if passed else "red"
        status_text = f"[{status_color}]{status_icon}[/{status_color}]"
        rows.append([component, status_text, details])
    
    table = create_binary_safe_table(
        title="Validation Results",
        headers=headers,
        rows=rows,
        column_styles=["white", "cyan", "dim"],
        column_widths=[25, 10, 40]
    )
    
    console.print(table)


def display_resource_summary(summary_data: Dict[str, Any]):
    """Display resource summary using package-compatible table."""
    if not summary_data:
        console.print("[yellow]No resources found[/yellow]")
        return
    
    # Resources by service
    if summary_data.get('by_service'):
        headers = ["Service", "Count"]
        rows = [[service.upper(), str(count)] for service, count in summary_data['by_service'].items()]
        
        table = create_binary_safe_table(
            title="Resources by Service",
            headers=headers,
            rows=rows,
            column_styles=["cyan", "white"]
        )
        
        console.print(table)


def display_lifecycle_status(lifecycle_data: List[Dict[str, Any]]):
    """Display resource lifecycle status using package-compatible table."""
    if not lifecycle_data:
        console.print("[yellow]No lifecycle data available[/yellow]")
        return
    
    headers = ["Resource", "State", "Expires", "Warnings"]
    rows = []
    
    for resource in lifecycle_data:
        resource_name = resource.get('resource_name', 'Unknown')
        state = resource.get('lifecycle_state', 'active')
        expires = resource.get('expires_at', 'Never')
        warning_count = str(resource.get('warning_count', 0))
        
        rows.append([resource_name, state, expires, warning_count])
    
    table = create_binary_safe_table(
        title="Resource Lifecycle Status",
        headers=headers,
        rows=rows,
        column_styles=["cyan", "yellow", "dim", "red"]
    )
    
    console.print(table)


def display_safe_panel(content: str, title: str, style: str = "blue"):
    """Display a panel that's compatible with packaged binaries."""
    panel = Panel(
        content,
        title=title,
        border_style=style,
        expand=False
    )
    console.print(panel)


def print_safe(message: str):
    """Print message using the configured console."""
    console.print(message)


def print_error(message: str):
    """Print error message in red."""
    console.print(f"[red]{message}[/red]")


def print_success(message: str):
    """Print success message in green."""
    console.print(f"[green]{message}[/green]")


def print_warning(message: str):
    """Print warning message in yellow."""
    console.print(f"[yellow]{message}[/yellow]")


def print_info(message: str):
    """Print info message in blue."""
    console.print(f"[blue]{message}[/blue]")