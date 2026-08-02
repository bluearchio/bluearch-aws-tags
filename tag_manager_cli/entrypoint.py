"""Side-effect-free public entry point for BlueArch AWS Tags."""

from __future__ import annotations

import re
import sys

from . import __version__


PUBLIC_BINARY_NAME = "bluearch-aws-tags"
_DEVELOPMENT_HASH = re.compile(r"[0-9a-fA-F]{7}")


def is_raw_version_request(arguments: list[str]) -> bool:
    """Return whether ``arguments`` is an exact public version probe."""
    return arguments in (["--version"], ["-V"])


def public_version_line(version: str = __version__) -> str:
    """Return the stable one-line public version identity."""
    is_development = version == "LOCAL" or _DEVELOPMENT_HASH.fullmatch(version) is not None
    channel = "development" if is_development else "production"
    return f"{PUBLIC_BINARY_NAME} {version} ({channel})"


def cli() -> None:
    """Run the stateless version fast path or lazily load the Typer app."""
    if is_raw_version_request(sys.argv[1:]):
        print(public_version_line())
        return

    from .main import app

    app()


if __name__ == "__main__":
    cli()
