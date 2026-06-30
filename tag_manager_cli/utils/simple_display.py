"""Simple ASCII-only display utilities for PyInstaller compatibility."""

import sys
from typing import List, Tuple, Optional, Dict, Any


def print_ascii_table(title: str, headers: List[str], rows: List[List[str]], column_widths: Optional[List[int]] = None):
    """Print a simple ASCII table without Rich dependencies."""
    
    # Calculate column widths if not provided
    if not column_widths:
        column_widths = []
        for i, header in enumerate(headers):
            max_width = len(header)
            for row in rows:
                if i < len(row) and len(str(row[i])) > max_width:
                    max_width = len(str(row[i]))
            column_widths.append(max_width + 2)  # Add padding
    
    # Print title
    total_width = sum(column_widths) + len(headers) - 1
    print(f"\n{title.center(total_width)}")
    print("=" * total_width)
    
    # Print headers
    header_line = ""
    for i, (header, width) in enumerate(zip(headers, column_widths)):
        if i > 0:
            header_line += "|"
        header_line += header.ljust(width)
    print(header_line)
    
    # Print separator
    sep_line = ""
    for i, width in enumerate(column_widths):
        if i > 0:
            sep_line += "+"
        sep_line += "-" * width
    print(sep_line)
    
    # Print rows
    for row in rows:
        row_line = ""
        for i, (cell, width) in enumerate(zip(row + [""] * len(column_widths), column_widths)):
            if i > 0:
                row_line += "|"
            row_line += str(cell).ljust(width)
        print(row_line)
    
    print("")


def display_main_menu_ascii():
    """Display the main menu using ASCII-only table."""
    headers = ["Option", "Feature", "Description"]
    rows = [
        ["1", "FinOps Cost Analysis", "CUR-powered chargeback reports, tagging gaps, anomaly detection"],
        ["2", "Resource Organization", "Organize and categorize AWS resources using tags"],
        ["3", "Development Tools", "Test components, debug workers, development utilities"],
        ["q", "Quit", "Exit the application"]
    ]

    print_ascii_table("AWS Tag Manager - Main Menu", headers, rows, [8, 40, 60])


def display_system_status_ascii(status_data: List[Tuple[str, str, str]]):
    """Display system status using ASCII-only table."""
    headers = ["Component", "Status", "Details"]
    rows = [[component, status, details] for component, status, details in status_data]
    
    print_ascii_table("System Status", headers, rows, [20, 15, 40])


def display_validation_results_ascii(validation_results: List[Tuple[str, bool, str]]):
    """Display validation results using ASCII-only table."""
    headers = ["Component", "Status", "Details"]
    rows = []
    
    for component, passed, details in validation_results:
        status_text = "OK" if passed else "ERROR"
        rows.append([component, status_text, details])
    
    print_ascii_table("Validation Results", headers, rows, [25, 10, 50])


def print_safe_ascii(message: str):
    """Print message safely for packaged binaries."""
    # Remove Rich markup for ASCII-only output
    import re
    clean_message = re.sub(r'\[/?[^\]]*\]', '', message)
    print(clean_message)


def print_error_ascii(message: str):
    """Print error message in ASCII."""
    print(f"ERROR: {message}")


def print_success_ascii(message: str):
    """Print success message in ASCII."""
    print(f"OK: {message}")


def print_warning_ascii(message: str):
    """Print warning message in ASCII."""
    print(f"WARN: {message}")


def print_info_ascii(message: str):
    """Print info message in ASCII."""
    print(f"INFO: {message}")