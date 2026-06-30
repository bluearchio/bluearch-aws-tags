"""Update commands for Tag Manager CLI."""

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
    from ..utils.core_client import (
        MINIMUM_CORE_VERSION,
        core_install_url,
        core_version_satisfies,
        get_installed_core_version,
    )
    from .. import __version__
except ImportError:
    # Fall back to absolute imports (direct execution)
    from tag_manager_cli.utils.display_utils import print_safe, print_error
    from tag_manager_cli.utils.version_checker import get_updates
    from tag_manager_cli.utils.core_client import (
        MINIMUM_CORE_VERSION,
        core_install_url,
        core_version_satisfies,
        get_installed_core_version,
    )
    from tag_manager_cli import __version__

console = Console()
app = typer.Typer(
    name="update",
    help="Update Tag Manager CLI to the latest version",
    no_args_is_help=False,
)

# Public package names used when presenting upgrade guidance.
PROD_INSTALL_URL = "brew upgrade bluearchio/tap/bluearch-aws-tags"
DEV_INSTALL_URL = "pipx install -e ../bluearch-aws-tags --force"
CORE_REQUIREMENT_KEYS = (
    "minimum_core_version",
    "minimum_bluearch_core_version",
    "bluearch_core_min_version",
    "required_core_version",
)


def detect_homebrew_installation() -> dict:
    """Detect if tag-manager is installed via Homebrew."""
    from pathlib import Path

    locations = {
        "homebrew_arm": Path("/opt/homebrew/bin/tag-manager"),
        "homebrew_intel": Path("/usr/local/bin/tag-manager"),
    }

    for install_type, path in locations.items():
        if path.exists():
            # For Intel, verify it's a Homebrew symlink (points to Cellar)
            if install_type == "homebrew_intel":
                try:
                    if "Cellar" not in str(path.resolve()):
                        continue
                except Exception:
                    continue

            # Get version
            version = "unknown"
            try:
                result = subprocess.run(
                    [str(path), "--version"], capture_output=True, text=True, timeout=10
                )
                if result.returncode == 0:
                    for line in result.stdout.split("\n"):
                        if "Tag Manager CLI" in line:
                            version = line.strip()
                            break
            except Exception:
                pass

            # Check for curl binary conflict
            curl_binary = Path.home() / ".local" / "bin" / "tag-manager"

            return {
                "installed": True,
                "binary_path": str(path),
                "version": version,
                "install_type": install_type,
                "conflict": curl_binary.exists(),
                "curl_binary_path": str(curl_binary) if curl_binary.exists() else None,
            }

    return {"installed": False}


def perform_homebrew_core_update(required_core_version: str) -> bool:
    """Install or upgrade bluearch-core via Homebrew before product update."""
    print_safe(f"[dim]Ensuring bluearch-core >= {required_core_version}...[/dim]")
    installed = subprocess.run(
        ["brew", "list", "--versions", "bluearch-aws-core"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    command = ["brew", "upgrade", "bluearchio/tap/bluearch-aws-core"] if installed.stdout.strip() else ["brew", "install", "bluearchio/tap/bluearch-aws-core"]
    result = subprocess.run(command, capture_output=False, text=True, timeout=300)
    if result.returncode != 0 and command[1] == "upgrade":
        result = subprocess.run(["brew", "install", "bluearchio/tap/bluearch-aws-core"], capture_output=False, text=True, timeout=300)
    return result.returncode == 0


def perform_homebrew_update(required_core_version: str) -> bool:
    """Perform update via Homebrew. Returns True on success."""
    print_safe("\n[blue]Updating via Homebrew...[/blue]")

    # Update tap
    print_safe("[dim]Updating Homebrew tap...[/dim]")
    subprocess.run(["brew", "update"], capture_output=True, text=True, timeout=120)

    if not perform_homebrew_core_update(required_core_version):
        print_error("bluearch-core update failed. Tag Manager update was not started.")
        return False

    # Upgrade
    print_safe("[dim]Upgrading bluearch-aws-tags...[/dim]")
    result = subprocess.run(
        ["brew", "upgrade", "bluearchio/tap/bluearch-aws-tags"], capture_output=False, text=True, timeout=300
    )
    return result.returncode == 0


def perform_core_install(required_core_version: str, development_channel: bool) -> bool:
    """Install or update bluearch-core through the public install command."""
    install_url = core_install_url(development_channel)
    print_safe(f"\n[blue]Ensuring bluearch-core >= {required_core_version}...[/blue]")
    cmd = install_url
    print_safe(f"[dim]Executing: {cmd}[/dim]")
    result = subprocess.run(cmd.split(), capture_output=False, text=True)
    return result.returncode == 0


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
      - Homebrew: Uses 'brew upgrade bluearchio/tap/bluearch-aws-tags'
      - Source install: reinstall from the local checkout

    Examples:
        tag-manager update              # Update to latest version
        tag-manager update --check      # Check for updates
        tag-manager update --force      # Update without confirmation
        tag-manager update --dev        # Development channel (curl only)
        tag-manager update --yes              # Unattended update (skip if current)
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
        install_url = DEV_INSTALL_URL if development else PROD_INSTALL_URL

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
                    "[dim]  Run 'tag-manager setup doctor' for cleanup guidance.[/dim]"
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
                    result = subprocess.run(
                        ["brew", "outdated", "tag-manager"],
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )
                    if result.stdout.strip():
                        print_safe("[yellow]Update available via Homebrew[/yellow]")
                        print_safe("\nTo update: [cyan]brew upgrade bluearchio/tap/bluearch-aws-core bluearchio/tap/bluearch-aws-tags[/cyan]")
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
                    "(brew upgrade/install bluearch-aws-core, then brew upgrade bluearch-aws-tags)?"
                )
                if not Confirm.ask(
                    prompt, default=True
                ):
                    print_safe(
                        "\n[dim]Update cancelled. To update manually: brew upgrade bluearchio/tap/bluearch-aws-core bluearchio/tap/bluearch-aws-tags[/dim]"
                    )
                    return

            # Perform update
            if perform_homebrew_update(required_core):
                print_safe("\n[green]Update completed successfully![/green]")
                print_safe(
                    "\nRun [cyan]tag-manager --version[/cyan] to verify the new version."
                )
            else:
                print_error(
                    "Homebrew update failed. Try manually: brew upgrade bluearchio/tap/bluearch-aws-core bluearchio/tap/bluearch-aws-tags"
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
                print_safe("\nTo update: [cyan]tag-manager update[/cyan]")
            return

        # Confirmation prompt (unless force or yes is used)
        if not force and not yes:
            print_safe(
                "\n[yellow]This will update Tag Manager CLI to the latest version.[/yellow]"
            )
            print_safe("[dim]This will:[/dim]")
            print_safe(f"[dim]  - Install or update bluearch-core to >= {required_core}[/dim]")
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

        # Execute the installation script
        cmd = install_url

        # Show the command being executed (for transparency)
        print_safe(f"[dim]Executing: {cmd}[/dim]")

        # Run the installation
        result = subprocess.run(
            cmd.split(),
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
                "\nRun [cyan]tag-manager --version[/cyan] to verify the new version."
            )
        else:
            print_error("Update failed. Please check the output above for details.")
            print_error("You can also try running the installation manually:")
            print_error(f"  {cmd}")
            raise typer.Exit(1)

    except KeyboardInterrupt:
        print_safe("\n[yellow]Update cancelled by user.[/yellow]")
        raise typer.Exit(1)
    except Exception as e:
        print_error(f"Update failed: {escape(str(e))}")
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
