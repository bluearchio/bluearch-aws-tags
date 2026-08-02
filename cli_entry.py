#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Compatibility entry point for standalone CLI builds.

The public entry point handles version probes before importing the stateful
application.
"""

import sys
import os

# Add the project root to Python path
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Import the side-effect-free public launcher. Build tooling is responsible for
# including the package and its dependencies.
from tag_manager_cli.entrypoint import cli

if __name__ == "__main__":
    cli()
