#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Entry point script for PyInstaller to build the tag-manager CLI binary.
This script imports and runs the main CLI application.
"""

import sys
import os

# Add the project root to Python path
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Pre-import optional dependencies to ensure they're included in the binary
# These imports ensure PyInstaller packages them even if they're conditionally imported
try:
    # Core dependencies that need explicit packaging
    import sqlalchemy
    import alembic
    import diskcache

    # Optional features (can be removed if not using these features)
    import slack_sdk  # Keep if Slack integration is needed
    import psutil     # Keep if health monitoring is needed
except ImportError as e:
    # It's OK if some packages are missing in development
    # but they should all be present when building the binary
    pass

# Import and run the main CLI
from tag_manager_cli.main import cli

if __name__ == "__main__":
    cli()