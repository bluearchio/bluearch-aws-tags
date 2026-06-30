#!/usr/bin/env python3
"""
Standalone launcher for Tag Manager CLI
This file avoids relative import issues when creating binaries
"""

import sys
import os

# Fix encoding for Unicode support
os.environ.setdefault('PYTHONIOENCODING', 'utf-8')

# Ensure UTF-8 encoding for output
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Add the current directory to the Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

# Import and run the main CLI
if __name__ == "__main__":
    try:
        from tag_manager_cli.main import cli
        cli()
    except ImportError as e:
        print(f"Error importing tag_manager_cli: {e}")
        print("Make sure all dependencies are installed.")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nExiting...")
        sys.exit(0)
    except UnicodeEncodeError as e:
        print("Unicode encoding error. Please set PYTHONIOENCODING=utf-8 in your environment.")
        print(f"Details: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}")
        sys.exit(1)