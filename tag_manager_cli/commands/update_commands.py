"""Update commands for Tag Manager CLI."""

import os
import shlex
import typer
import subprocess
from rich.console import Console
from rich.prompt import Confirm
from rich.markup import escape

# Handle both direct execution and module execution for imports
try:
    # Try relative imports first (module execution)
    from ..utils.display_utils import print_safe, print_error
    from ..utils.version_checker import get_updates
    from ..utils.public_executables import (
        PUBLIC_CORE_FORMULA,
        PUBLIC_TAGS_FORMULA,
        probe_public_tags_version,
        resolve_exact_executable,
        resolve_homebrew_executable,
    )
    from ..utils.core_client import (
        CoreRuntimeError,
        MINIMUM_CORE_VERSION,
        core_version_satisfies,
        get_installed_core_version,
        resolve_core_install_command,
    )
    from .. import __version__
except ImportError:
    # Fall back to absolute imports (direct execution)
    from tag_manager_cli.utils.display_utils import print_safe, print_error
    from tag_manager_cli.utils.version_checker import get_updates
    from tag_manager_cli.utils.public_executables import (
        PUBLIC_CORE_FORMULA,
        PUBLIC_TAGS_FORMULA,
        probe_public_tags_version,
        resolve_exact_executable,
        resolve_homebrew_executable,
    )
    from tag_manager_cli.utils.core_client import (
        CoreRuntimeError,
        MINIMUM_CORE_VERSION,
        core_version_satisfies,
        get_installed_core_version,
        resolve_core_install_command,
    )
    from tag_manager_cli import __version__

console = Console()
app = typer.Typer(
    name="update",
    help="Update Tag Manager CLI to the latest version",
    no_args_is_help=False,
)

# Public package names used when presenting upgrade guidance.
DEV_INSTALL_URL = "pipx install -e ../bluearch-aws-tags --force"
CORE_REQUIREMENT_KEYS = (
    "minimum_core_version",
    "minimum_bluearch_core_version",
    "bluearch_core_min_version",
    "required_core_version",
)
ALLOWED_HOMEBREW_FORMULAS = frozenset({PUBLIC_CORE_FORMULA, PUBLIC_TAGS_FORMULA})


def _homebrew_tags_locations() -> dict[str, "Path"]:
    from pathlib import Path

    return {
        "homebrew_arm": Path("/opt/homebrew/bin/bluearch-aws-tags"),
        "homebrew_intel": Path("/usr/local/bin/bluearch-aws-tags"),
    }


def detect_homebrew_installation() -> dict:
    """Detect the public Tags executable installed via Homebrew."""
    from pathlib import Path

    for install_type, path in _homebrew_tags_locations().items():
        probe = probe_public_tags_version(os.fspath(path))
        if probe is not None:
            canonical_path, result = probe
            # For Intel, verify it's a Homebrew symlink (points to Cellar)
            if install_type == "homebrew_intel" and "Cellar" not in canonical_path:
                continue

            # Get version
            version = "unknown"
            if result.returncode == 0:
                for line in result.stdout.split("\n"):
                    if "Tag Manager CLI" in line:
                        version = line.strip()
                        break

            # Check for curl binary conflict
            curl_binary = Path.home() / ".local" / "bin" / "bluearch-aws-tags"

            return {
                "installed": True,
                "binary_path": canonical_path,
                "version": version,
                "install_type": install_type,
                "conflict": curl_binary.exists(),
                "curl_binary_path": str(curl_binary) if curl_binary.exists() else None,
            }

    return {"installed": False}


def _trust_homebrew_formulas(brew: str, formulas: tuple[str, ...]) -> bool:
    """Trust only exact public formulae through a canonical Homebrew executable."""
    canonical_brew = resolve_homebrew_executable(brew)
    if canonical_brew is None:
        print_error("A canonical Homebrew executable could not be resolved.")
        return False
    for formula in formulas:
        if formula not in ALLOWED_HOMEBREW_FORMULAS:
            print_error(f"Refusing to trust unsupported Homebrew formula: {formula}")
            return False
        try:
            result = subprocess.run(
                [canonical_brew, "trust", "--formula", formula],
                capture_output=True,
                text=True,
                timeout=60,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            print_error(f"Homebrew formula trust failed for {formula}: {exc}")
            return False
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "unknown error").strip()
            print_error(f"Homebrew formula trust failed for {formula}: {detail}")
            return False
    return True


def _prepare_homebrew(formulas: tuple[str, ...]) -> str | None:
    brew = resolve_homebrew_executable()
    if brew is None:
        print_error("Homebrew executable was not found or did not resolve to canonical brew.")
        return None
    return brew if _trust_homebrew_formulas(brew, formulas) else None


def _perform_homebrew_core_update(brew: str, required_core_version: str) -> bool:
    print_safe(f"[dim]Ensuring bluearch-aws-core >= {required_core_version}...[/dim]")
    installed = subprocess.run(
        [brew, "list", "--versions", PUBLIC_CORE_FORMULA],
        capture_output=True,
        text=True,
        timeout=30,
    )
    command = (
        [brew, "upgrade", PUBLIC_CORE_FORMULA]
        if installed.stdout.strip()
        else [brew, "install", PUBLIC_CORE_FORMULA]
    )
    result = subprocess.run(command, capture_output=False, text=True, timeout=300)
    if result.returncode != 0 and command[1] == "upgrade":
        result = subprocess.run(
            [brew, "install", PUBLIC_CORE_FORMULA],
            capture_output=False,
            text=True,
            timeout=300,
        )
    return result.returncode == 0


def perform_homebrew_core_update(required_core_version: str) -> bool:
    """Trust, then install or upgrade Core through canonical Homebrew."""
    brew = _prepare_homebrew((PUBLIC_CORE_FORMULA,))
    if brew is None:
        return False
    try:
        return _perform_homebrew_core_update(brew, required_core_version)
    except (OSError, subprocess.SubprocessError) as exc:
        print_error(f"bluearch-aws-core Homebrew update failed: {exc}")
        return False


def perform_homebrew_update(required_core_version: str) -> bool:
    """Perform update via Homebrew. Returns True on success."""
    print_safe("\n[blue]Updating via Homebrew...[/blue]")

    brew = _prepare_homebrew((PUBLIC_CORE_FORMULA, PUBLIC_TAGS_FORMULA))
    if brew is None:
        return False

    try:
        print_safe("[dim]Updating Homebrew tap...[/dim]")
        subprocess.run([brew, "update"], capture_output=True, text=True, timeout=120)

        if not _perform_homebrew_core_update(brew, required_core_version):
            print_error("bluearch-aws-core update failed. Tags update was not started.")
            return False

        print_safe("[dim]Upgrading bluearch-aws-tags...[/dim]")
        result = subprocess.run(
            [brew, "upgrade", PUBLIC_TAGS_FORMULA],
            capture_output=False,
            text=True,
            timeout=300,
        )
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError) as exc:
        print_error(f"Homebrew update failed: {exc}")
        return False


def perform_core_install(required_core_version: str, development_channel: bool) -> bool:
    """Install or update bluearch-core through the public install command."""
    print_safe(f"\n[blue]Ensuring bluearch-aws-core >= {required_core_version}...[/blue]")
    try:
        command = resolve_core_install_command(development_channel)
    except CoreRuntimeError as exc:
        print_error(str(exc))
        return False
    if not development_channel and not _trust_homebrew_formulas(
        command[0],
        (PUBLIC_CORE_FORMULA,),
    ):
        return False
    print_safe(f"[dim]Executing: {' '.join(command)}[/dim]")
    result = subprocess.run(command, capture_output=False, text=True)
    return result.returncode == 0


def homebrew_update_remediation() -> str:
    """Return trust-first, exact-formula manual update guidance."""
    return "\n".join(
        (
            f"brew trust --formula {PUBLIC_CORE_FORMULA}",
            f"brew trust --formula {PUBLIC_TAGS_FORMULA}",
            f"brew upgrade {PUBLIC_CORE_FORMULA} {PUBLIC_TAGS_FORMULA}",
        )
    )


def _prepare_product_update_command(development: bool) -> list[str] | None:
    """Build one canonical, exact-form product update command."""
    if development:
        command = shlex.split(DEV_INSTALL_URL)
        if command != ["pipx", "install", "-e", "../bluearch-aws-tags", "--force"]:
            print_error("Unsupported development update command.")
            return None
        pipx = resolve_exact_executable(command[0], "pipx")
        if pipx is None:
            print_error("A canonical pipx executable could not be resolved.")
            return None
        return [pipx, *command[1:]]

    brew = _prepare_homebrew((PUBLIC_TAGS_FORMULA,))
    if brew is None:
        return None
    return [brew, "upgrade", PUBLIC_TAGS_FORMULA]


def required_core_version(update_info: dict | None) -> str:
    """Resolve the core version required by the target product release."""
    if update_info:
        for key in CORE_REQUIREMENT_KEYS:
            value = update_info.get(key)
            if value:
                return str(value).lstrip("v")
    return MINIMUM_CORE_VERSION


def print_core_requirement(required_version: str) -> None:
    installed = get_installed_core_version()
    installed_label = installed or "not installed"
    status = "ok" if core_version_satisfies(installed, required_version) else "update required"
    print_safe(f"[blue]Required BlueArch Core:[/blue] >= {required_version}")
    print_safe(f"[blue]Installed BlueArch Core:[/blue] {installed_label} ({status})")


def core_update_required(required_version: str) -> bool:
    return not core_version_satisfies(get_installed_core_version(), required_version)


@app.callback(invoke_without_command=True)
def update_main(
    ctx: typer.Context,
    check: bool = typer.Option(
        False, "--check", help="Check for updates without installing"
    ),
    force: bool = typer.Option(
        False, "--force", "-f", help="Force update without confirmation"
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Auto-confirm update if a newer version is available"
    ),
    development: bool = typer.Option(
        False,
        "--development",
        "--dev",
        help="Download from development channel instead of production",
    ),
    help: bool = typer.Option(
        False, "--help", "-h", help="Show this message and exit."
    ),
):
    """
    Update Tag Manager CLI to the latest version.

    The update method is automatically detected based on your installation:
      - Homebrew: Trusts exact Core/Tags formulae, then upgrades them
      - Source install: reinstall from the local checkout

    Examples:
        bluearch-aws-tags update              # Update to latest version
        bluearch-aws-tags update --check      # Check for updates
        bluearch-aws-tags update --force      # Update without confirmation
        bluearch-aws-tags update --dev        # Development channel (curl only)
        bluearch-aws-tags update --yes        # Unattended update (skip if current)
    """
    # Show help if requested
    if help:
        ctx.get_help()
        raise typer.Exit()

    # If a subcommand is being invoked, let it handle
    if ctx.invoked_subcommand is not None:
        return

    try:
        # Determine channel and install URL
        channel = "development" if development else "production"

        # Show current version and channel
        print_safe(f"[blue]Current version:[/blue] {__version__}")
        print_safe(f"[blue]Update channel:[/blue] {channel}")

        updates = None
        try:
            updates = get_updates(force_development=development)
        except Exception as e:
            print_safe(f"[yellow]Could not check release metadata: {escape(str(e))}[/yellow]")
        latest_update = updates[0] if updates else None
        required_core = required_core_version(latest_update)
        print_core_requirement(required_core)

        # Check for Homebrew installation BEFORE running curl script
        homebrew = detect_homebrew_installation()
        if homebrew["installed"]:
            print_safe(
                "\n[yellow][NOTICE] Tag Manager is installed via Homebrew[/yellow]"
            )
            if homebrew.get("binary_path"):
                print_safe(f"[dim]  Binary: {homebrew['binary_path']}[/dim]")
            if homebrew.get("version"):
                print_safe(f"[dim]  Version: {homebrew['version']}[/dim]")

            # Warn about conflict
            if homebrew.get("conflict"):
                print_safe(
                    "\n[yellow][WARNING] Multiple installations detected![/yellow]"
                )
                print_safe(
                    f"[dim]  Curl binary also exists at: {homebrew['curl_binary_path']}[/dim]"
                )
                print_safe(
                    "[dim]  Run 'bluearch-aws-tags setup doctor' for cleanup guidance.[/dim]"
                )

            # Dev channel not available via Homebrew
            if development:
                print_safe(
                    "\n[yellow][WARNING] Development channel not available via Homebrew[/yellow]"
                )
                print_safe("[dim]Homebrew only tracks production releases.[/dim]")
                print_safe("[dim]To use dev versions:[/dim]")
                print_safe("[dim]  brew uninstall bluearchio/tap/bluearch-aws-tags[/dim]")
                print_safe(
                    f"[dim]  {DEV_INSTALL_URL}[/dim]"
                )
                return

            # Check-only mode for Homebrew
            if check:
                print_safe("\n[blue]Checking for Homebrew updates...[/blue]")
                try:
                    brew = _prepare_homebrew((PUBLIC_TAGS_FORMULA,))
                    if brew is None:
                        raise typer.Exit(1)
                    result = subprocess.run(
                        [brew, "outdated", PUBLIC_TAGS_FORMULA],
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )
                    if result.stdout.strip():
                        print_safe("[yellow]Update available via Homebrew[/yellow]")
                        print_safe(f"\nTo update safely:\n[cyan]{homebrew_update_remediation()}[/cyan]")
                    else:
                        print_safe("[green]Already on latest Homebrew version![/green]")
                except Exception as e:
                    print_safe(f"[dim]Could not check: {e}[/dim]")
                return

            print_safe(
                "\n[blue]Homebrew is the recommended update method for your installation.[/blue]"
            )

            # Confirm update
            if not force and not yes:
                prompt = (
                    "\nUpdate BlueArch Core and Tag Manager via Homebrew "
                    "(trust the exact Core and Tags formulae, then upgrade them)?"
                )
                if not Confirm.ask(
                    prompt, default=True
                ):
                    print_safe(
                        f"\n[dim]Update cancelled. To update manually:\n{homebrew_update_remediation()}[/dim]"
                    )
                    return

            # Perform update
            if perform_homebrew_update(required_core):
                print_safe("\n[green]Update completed successfully![/green]")
                print_safe(
                    "\nRun [cyan]bluearch-aws-tags --version[/cyan] to verify the new version."
                )
            else:
                print_error(
                    f"Homebrew update failed. Try manually:\n{homebrew_update_remediation()}"
                )
                raise typer.Exit(1)
            return

        if not updates:
            print_safe("[green]You are already up to date![/green]")
            if check:
                return
            if core_update_required(required_core):
                if force or yes or Confirm.ask("BlueArch Core must be updated for this Tag Manager version. Update core now?", default=True):
                    if not perform_core_install(required_core, development):
                        print_error("BlueArch Core update failed.")
                        raise typer.Exit(1)
                return
            if yes:
                return
            if not force and not check:
                if not Confirm.ask("Continue with installation anyway?"):
                    print_safe("Update cancelled.")
                    return
        elif updates:
            latest = updates[0]
            print_safe(
                f"\n[yellow]Latest version available:[/yellow] [green]{latest['version']}[/green] ({latest['date']})"
            )
            if latest["message"].strip():
                message = latest["message"].replace("\\n", "\n").strip('"').strip()
                if message:
                    print_safe(f"[dim]{message}[/dim]")

        # If check-only mode, exit here
        if check:
            if updates:
                print_safe("\nTo update: [cyan]bluearch-aws-tags update[/cyan]")
            return

        # Confirmation prompt (unless force or yes is used)
        if not force and not yes:
            print_safe(
                "\n[yellow]This will update Tag Manager CLI to the latest version.[/yellow]"
            )
            print_safe("[dim]This will:[/dim]")
            print_safe(f"[dim]  - Install or update bluearch-aws-core to >= {required_core}[/dim]")
            print_safe("[dim]  - Download and install the latest binary[/dim]")
            print_safe("[dim]  - Clean up old Docker containers and files[/dim]")
            print_safe("[dim]  - Preserve your database (automatic backup)[/dim]")
            print_safe("[dim]  - Run any necessary database migrations[/dim]")
            print_safe("")
            if not Confirm.ask("Continue with update?", default=True):
                print_safe("Update cancelled.")
                return

        if not perform_core_install(required_core, development):
            print_error("BlueArch Core update failed. Tag Manager update was not started.")
            raise typer.Exit(1)

        print_safe(
            f"\n[blue]Downloading and installing latest {channel} version...[/blue]"
        )

        command = _prepare_product_update_command(development)
        if command is None:
            print_error("Product update was not started.")
            raise typer.Exit(1)
        cmd = shlex.join(command)

        # Show the command being executed (for transparency)
        print_safe(f"[dim]Executing: {cmd}[/dim]")

        # Run the installation
        result = subprocess.run(
            command,
            capture_output=False,  # Let output stream directly to user
            text=True,
        )

        if result.returncode == 0:
            print_safe("\n[green]Update completed successfully![/green]")
            print_safe(
                "\n[dim]Database migrations are handled automatically during installation.[/dim]"
            )
            print_safe(
                "\nYou may need to restart your terminal or run "
                "[cyan]source ~/.bashrc[/cyan] (or [cyan]source ~/.zshrc[/cyan])"
            )
            print_safe(
                "\nRun [cyan]bluearch-aws-tags --version[/cyan] to verify the new version."
            )
        else:
            print_error("Update failed. Please check the output above for details.")
            print_error("You can also try running the installation manually:")
            if development:
                print_error(f"  {cmd}")
            else:
                print_error(homebrew_update_remediation())
            raise typer.Exit(1)

    except KeyboardInterrupt:
        print_safe("\n[yellow]Update cancelled by user.[/yellow]")
        raise typer.Exit(1)
    except Exception as e:
        print_error(f"Update failed: {escape(str(e))}")
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
