"""Web server configuration."""

import os


class WebConfig:
    """Configuration for the web dashboard server."""

    host: str = os.environ.get("TAG_MANAGER_WEB_HOST", "127.0.0.1")
    port: int = int(os.environ.get("TAG_MANAGER_WEB_PORT", "8096"))
    reload: bool = os.environ.get("TAG_MANAGER_WEB_RELOAD", "").lower() == "true"
    log_level: str = os.environ.get("TAG_MANAGER_WEB_LOG_LEVEL", "info")


web_config = WebConfig()
