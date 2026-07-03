import os
import sys
from rich import console
from rich.prompt import Prompt
from .. import __version__

console = console.Console()

import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

def is_dev_version(version: str) -> bool:
    """
    Detect if a version string represents a development build.

    Development versions are:
    - 'LOCAL' (source/unbuilt)
    - 7-character hex strings (commit hashes from dev builds)

    Production versions are semantic versioning strings like 'v0.1.0' or '0.1.0'.
    """
    if version == "LOCAL":
        return True
    # Dev versions are 7-char hex strings (commit hashes)
    if len(version) == 7:
        try:
            int(version, 16)  # Check if it's a valid hex string
            return True
        except ValueError:
            pass
    return False


class ShellRCManager:
    def __init__(self):
        self.default_shell = os.path.basename(os.environ.get("SHELL", "/bin/bash"))
        self.home_dir = os.path.expanduser("~")
        self.shell_rc_file = self._get_shell_rc_file()
        self.auto_update_command = "tag-manager --version-silent"

    def _get_shell_rc_file(self):
        if self.default_shell == "zsh":
            return os.path.join(self.home_dir, ".zshrc")
        elif self.default_shell == "bash":
            return os.path.join(self.home_dir, ".bashrc")
        else:
            raise ValueError(f"Unsupported shell: {self.default_shell}")

    def check_command_in_shell_rc(self, command):
        with open(self.shell_rc_file, "r", encoding='utf-8') as f:
            return command in f.read()

    def add_command_to_shell_rc(self):
        if self.check_command_in_shell_rc(self.auto_update_command):
            console.print(f"The command [bold cyan]'{self.auto_update_command}'[/bold cyan] already exists in {self.shell_rc_file}.")
            console.print("[yellow]Auto-update already enabled![/yellow]")
            return False
        
        with open(self.shell_rc_file, "a", encoding='utf-8') as f:
            f.write(f"\n{self.auto_update_command}\n")
        console.print(f"Added [bold cyan]'{self.auto_update_command}'[/bold cyan] to [bold cyan]{self.shell_rc_file}[/bold cyan] file")
        console.print("[green]Auto-update enabled![/green]")
        return True

    def remove_command_from_shell_rc(self):
        with open(self.shell_rc_file, "r", encoding='utf-8') as f:
            lines = f.readlines()
        
        with open(self.shell_rc_file, "w", encoding='utf-8') as f:
            for line in lines:
                if line.strip() != self.auto_update_command:
                    f.write(line)
        
        console.print("[yellow]Auto-update removed![/yellow]")

def ask_for_enable_auto_update():
    shell_rc_manager = ShellRCManager()
    if not shell_rc_manager.check_command_in_shell_rc(shell_rc_manager.auto_update_command):
        if Prompt.ask("[blue]Do you want to enable auto-update for Tag Manager CLI?[/blue]", choices=["yes", "no"], default="no") == "yes":
            shell_rc_manager.add_command_to_shell_rc()

def delete_auto_update_command():
    shell_rc_manager = ShellRCManager()
    if shell_rc_manager.check_command_in_shell_rc(shell_rc_manager.auto_update_command):
        shell_rc_manager.remove_command_from_shell_rc()

def get_updates(force_development: bool = False):
    """Return available updates.

    Public builds do not call BlueArch-hosted release APIs. Distribution is
    handled through GitHub Releases and Homebrew.
    """
    return []
