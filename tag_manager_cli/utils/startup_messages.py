"""Manage startup message visibility to reduce noise after first run."""

import os
import time
import hashlib
from typing import Optional
from datetime import datetime, timedelta
from pathlib import Path


class StartupMessageManager:
    """Controls visibility of startup messages based on execution history."""

    def __init__(self):
        self.show_messages = False
        self._session_key = None
        self._init_session()

    def _init_session(self):
        """Initialize session tracking using file-based storage."""
        if os.environ.get("TAG_MANAGER_SUPPRESS_STARTUP_STATE") == "1":
            self.show_messages = False
            return
        try:
            # Generate session key based on user and terminal
            user = os.environ.get('USER', 'unknown')
            tty = os.environ.get('SSH_TTY', os.environ.get('TTY', 'console'))
            session_id = f"{user}_{tty}"
            session_hash = hashlib.md5(session_id.encode()).hexdigest()

            # Use local file for tracking instead of Redis
            cache_dir = Path.home() / '.tag-manager' / 'cache'
            cache_dir.mkdir(parents=True, exist_ok=True)

            self._session_file = cache_dir / f'.startup_shown_{session_hash}'

            # Check if we've shown messages recently (within 24 hours)
            if self._session_file.exists():
                file_age = time.time() - self._session_file.stat().st_mtime
                if file_age < 86400:  # 24 hours
                    # Messages were shown recently, suppress them
                    self.show_messages = False
                else:
                    # File is old, show messages and update timestamp
                    self.show_messages = True
                    self._session_file.touch()
            else:
                # First time, show messages and create marker file
                self.show_messages = True
                self._session_file.touch()

        except Exception:
            # Any error, use environment variable fallback
            self._use_env_fallback()

    def _use_env_fallback(self):
        """Fallback to environment variable when file tracking fails."""
        # Check if user explicitly wants to see startup messages
        show_startup = os.environ.get('TAG_MANAGER_SHOW_STARTUP', None)
        if show_startup is not None:
            self.show_messages = show_startup.lower() in ('true', '1', 'yes')
        else:
            # Check if this is the first run in this shell session
            marker = os.environ.get('TAG_MANAGER_STARTUP_SHOWN', None)
            if marker:
                self.show_messages = False
            else:
                self.show_messages = True
                # Set marker for this shell session
                os.environ['TAG_MANAGER_STARTUP_SHOWN'] = '1'

    def should_show_message(self, message_type: str = 'all') -> bool:
        """
        Check if a startup message should be shown.

        Args:
            message_type: Type of message ('env', 'cache', 'all')

        Returns:
            True if message should be shown, False otherwise
        """
        # Allow override via environment variable for debugging
        if os.environ.get('TAG_MANAGER_DEBUG', '0') == '1':
            return True

        # Check verbosity level
        verbose = os.environ.get('TAG_MANAGER_VERBOSE', '0')
        if verbose == '1':
            return True

        return self.show_messages

    def reset_visibility(self):
        """Reset visibility tracking to show messages again."""
        if hasattr(self, '_session_file') and self._session_file and self._session_file.exists():
            self._session_file.unlink()
        if 'TAG_MANAGER_STARTUP_SHOWN' in os.environ:
            del os.environ['TAG_MANAGER_STARTUP_SHOWN']
        self.show_messages = True

    def suppress_for_session(self):
        """Suppress messages for the current session."""
        self.show_messages = False
        if hasattr(self, '_session_file') and self._session_file:
            self._session_file.touch()
        os.environ['TAG_MANAGER_STARTUP_SHOWN'] = '1'


# Global instance
startup_messages = StartupMessageManager()
