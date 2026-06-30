"""Rich-formatted output for AI assistant responses."""

import re
from typing import List, Dict, Any, Optional
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.markdown import Markdown
from rich.syntax import Syntax
from rich.text import Text


class AIOutputFormatter:
    """Formats AI assistant responses with Rich components."""

    def __init__(self, console: Optional[Console] = None):
        """Initialize formatter with optional console."""
        self.console = console or Console()

    def format_and_print(self, text: str, streaming: bool = False):
        """
        Parse and format AI response text with Rich components.

        Args:
            text: Raw text from AI response
            streaming: If True, use simpler formatting for streaming output
        """
        if streaming:
            # For streaming, just apply basic Rich markup
            self._print_streaming(text)
        else:
            # For complete responses, parse and format with tables/panels
            self._print_formatted(text)

    def _print_streaming(self, text: str):
        """Print text with basic Rich markup for streaming output."""
        # Apply basic syntax highlighting for streaming
        if text.strip():
            self.console.print(text, end="", markup=True)

    def _print_formatted(self, text: str):
        """Parse and print formatted output with tables, panels, etc."""
        # Split text into sections
        sections = self._split_into_sections(text)

        for section in sections:
            section_type = section.get('type')
            content = section.get('content', '')

            if section_type == 'table':
                self._render_table(section)
            elif section_type == 'code':
                self._render_code(content, section.get('language', 'bash'))
            elif section_type == 'list':
                self._render_list(content)
            elif section_type == 'heading':
                self._render_heading(content)
            else:
                # Regular text - use Markdown for rich formatting
                if content.strip():
                    self.console.print(Markdown(content))

    def _split_into_sections(self, text: str) -> List[Dict[str, Any]]:
        """Split text into structured sections (tables, code blocks, lists, etc.)."""
        sections = []
        lines = text.split('\n')
        i = 0

        while i < len(lines):
            line = lines[i]

            # Detect table
            if self._is_table_row(line):
                table_lines, i = self._extract_table(lines, i)
                sections.append({
                    'type': 'table',
                    'lines': table_lines
                })
                continue

            # Detect code block
            if line.strip().startswith('```'):
                code_block, language, i = self._extract_code_block(lines, i)
                sections.append({
                    'type': 'code',
                    'content': code_block,
                    'language': language
                })
                continue

            # Detect heading
            if line.strip().startswith('#'):
                sections.append({
                    'type': 'heading',
                    'content': line
                })
                i += 1
                continue

            # Detect list
            if self._is_list_item(line):
                list_lines, i = self._extract_list(lines, i)
                sections.append({
                    'type': 'list',
                    'content': '\n'.join(list_lines)
                })
                continue

            # Regular text - accumulate until next special section
            text_lines = []
            while i < len(lines):
                current = lines[i]
                if (self._is_table_row(current) or
                    current.strip().startswith('```') or
                    current.strip().startswith('#') or
                    self._is_list_item(current)):
                    break
                text_lines.append(current)
                i += 1

            if text_lines:
                sections.append({
                    'type': 'text',
                    'content': '\n'.join(text_lines)
                })

        return sections

    def _is_table_row(self, line: str) -> bool:
        """Check if line is a markdown table row."""
        # Markdown tables have | separators
        stripped = line.strip()
        return stripped.startswith('|') and stripped.endswith('|') and stripped.count('|') >= 2

    def _is_list_item(self, line: str) -> bool:
        """Check if line is a list item."""
        stripped = line.strip()
        # Numbered list: 1. 2. etc.
        if re.match(r'^\d+\.\s+', stripped):
            return True
        # Bullet list: - * +
        if stripped.startswith(('- ', '* ', '+ ')):
            return True
        return False

    def _extract_table(self, lines: List[str], start_idx: int) -> tuple:
        """Extract all consecutive table rows."""
        table_lines = []
        i = start_idx

        while i < len(lines) and self._is_table_row(lines[i]):
            table_lines.append(lines[i])
            i += 1

        return table_lines, i

    def _extract_code_block(self, lines: List[str], start_idx: int) -> tuple:
        """Extract code block and language."""
        # First line: ```language
        first_line = lines[start_idx].strip()
        language = first_line[3:].strip() or 'text'

        code_lines = []
        i = start_idx + 1

        # Extract until closing ```
        while i < len(lines):
            if lines[i].strip().startswith('```'):
                i += 1
                break
            code_lines.append(lines[i])
            i += 1

        return '\n'.join(code_lines), language, i

    def _extract_list(self, lines: List[str], start_idx: int) -> tuple:
        """Extract all consecutive list items."""
        list_lines = []
        i = start_idx

        while i < len(lines):
            line = lines[i]
            if self._is_list_item(line):
                list_lines.append(line)
                i += 1
            elif line.strip() == '':
                # Empty line might be part of list
                i += 1
            else:
                break

        return list_lines, i

    def _render_table(self, section: Dict[str, Any]):
        """Render a markdown table as Rich Table."""
        lines = section['lines']
        if len(lines) < 2:
            return

        # Parse header row
        header_row = lines[0].strip('|').split('|')
        headers = [h.strip() for h in header_row]

        # Create Rich table
        table = Table(show_header=True, header_style="bold cyan")
        for header in headers:
            table.add_column(header)

        # Skip separator row (line 1)
        # Parse data rows (lines 2+)
        for line in lines[2:]:
            if not line.strip():
                continue
            cells = line.strip('|').split('|')
            cells = [c.strip() for c in cells]

            # Ensure we have the right number of cells
            while len(cells) < len(headers):
                cells.append('')

            table.add_row(*cells[:len(headers)])

        self.console.print(table)
        self.console.print()  # Add spacing

    def _render_code(self, code: str, language: str):
        """Render code block with syntax highlighting (no box for easy copy/paste)."""
        syntax = Syntax(code, language, theme="monokai", line_numbers=False, word_wrap=True)
        self.console.print(syntax)
        self.console.print()

    def _render_list(self, content: str):
        """Render list with Rich formatting."""
        # Use Markdown for list rendering
        self.console.print(Markdown(content))
        self.console.print()

    def _render_heading(self, content: str):
        """Render heading with emphasis."""
        # Count # symbols
        level = len(content) - len(content.lstrip('#'))
        text = content.lstrip('#').strip()

        if level == 1:
            self.console.print(f"\n[bold cyan]{text}[/bold cyan]")
        elif level == 2:
            self.console.print(f"\n[bold]{text}[/bold]")
        else:
            self.console.print(f"\n[bold dim]{text}[/bold dim]")
        self.console.print()

    def print_tool_call(self, tool_name: str, tool_input: Dict[str, Any]):
        """Format and print tool call information."""
        # Create a compact representation
        input_str = ', '.join(f"{k}={v}" for k, v in tool_input.items() if v)

        if input_str:
            self.console.print(f"[dim]Calling tool: {tool_name}({input_str})[/dim]")
        else:
            self.console.print(f"[dim]Calling tool: {tool_name}[/dim]")

    def print_tool_result_summary(self, tool_name: str, success: bool, summary: str = ""):
        """Print summary of tool execution result."""
        if success:
            status = "[green]OK[/green]"
        else:
            status = "[red]FAILED[/red]"

        message = f"[dim]Tool {tool_name}: {status}"
        if summary:
            message += f" - {summary}"
        message += "[/dim]"

        self.console.print(message)

    def print_section_panel(self, title: str, content: str, style: str = "cyan"):
        """Print content in a panel with title."""
        panel = Panel(
            Markdown(content),
            title=f"[bold]{title}[/bold]",
            border_style=style,
            padding=(1, 2)
        )
        self.console.print(panel)

    def print_error(self, message: str):
        """Print error message."""
        self.console.print(f"[red]Error:[/red] {message}")

    def print_warning(self, message: str):
        """Print warning message."""
        self.console.print(f"[yellow]Warning:[/yellow] {message}")

    def print_success(self, message: str):
        """Print success message."""
        self.console.print(f"[green]{message}[/green]")
