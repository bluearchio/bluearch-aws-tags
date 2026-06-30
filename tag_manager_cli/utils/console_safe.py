"""Safe console utilities that work in both development and binary environments."""

import sys
from rich.console import Console


def is_binary_environment():
    """Detect if we're running in a PyInstaller/packaged binary."""
    is_binary = (
        getattr(sys, 'frozen', False) or  # PyInstaller
        hasattr(sys, '_MEIPASS') or      # PyInstaller
        '__compiled__' in globals()       # PyInstaller
    )
    return is_binary


class SafeConsole:
    """A console wrapper that handles Unicode safely in binary environments."""
    
    def __init__(self):
        # Always use Rich Console - it handles encoding properly
        # Ensure UTF-8 encoding for output
        if hasattr(sys.stdout, 'reconfigure'):
            try:
                sys.stdout.reconfigure(encoding='utf-8')
                sys.stderr.reconfigure(encoding='utf-8')
            except Exception:
                pass
        self._console = Console()
    
    def print(self, *args, **kwargs):
        """Print method that uses Rich console with proper UTF-8 handling."""
        if is_binary_environment():
            # In binary mode, ensure we have good fallbacks but still use Rich
            try:
                self._console.print(*args, **kwargs)
            except (UnicodeEncodeError, UnicodeDecodeError):
                # Only fallback to plain text if there's an actual Unicode error
                import re
                message = ' '.join(str(arg) for arg in args)
                # Remove Rich markup as fallback
                message = re.sub(r'\[/?[^\]]*\]', '', message)
                print(message)
            except Exception:
                # Last resort fallback
                try:
                    message = ' '.join(str(arg) for arg in args)
                    print(message)
                except:
                    print("Error displaying message")
        else:
            # Use Rich console in development
            self._console.print(*args, **kwargs)


def create_safe_console():
    """Create a console instance that works in binary environments."""
    return SafeConsole()


def safe_print(message: str, style: str = ""):
    """Print a message using Rich console with proper UTF-8 handling."""
    console = create_safe_console()
    if style:
        console.print(f"[{style}]{message}[/{style}]")
    else:
        console.print(message)


# Global safe console instance
safe_console = create_safe_console()