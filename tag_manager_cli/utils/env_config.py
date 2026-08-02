"""Environment configuration management for Tag Manager CLI."""

import os
from pathlib import Path
from typing import Any, Optional, Dict, Union

from rich.console import Console

# Create console with proper UTF-8 handling
import sys
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

console = Console()


class EnvironmentConfig:
    """Manages environment variables and .env file loading."""
    
    def __init__(self, env_file: Optional[str] = None):
        self.env_file = env_file or self._find_env_file()
        self._env_vars: Dict[str, str] = {}
        self._load_env_file()
    
    def _find_env_file(self) -> Optional[str]:
        """Find .env file in current directory or project root."""
        current_dir = Path.cwd()
        
        # Check current directory first
        env_path = current_dir / ".env"
        if env_path.exists():
            return str(env_path)
        
        # Check project root (where this file is located)
        project_root = Path(__file__).parent.parent.parent
        env_path = project_root / ".env"
        if env_path.exists():
            return str(env_path)
        
        return None
    
    def _load_env_file(self):
        """Load environment variables from .env file."""
        if not self.env_file or not Path(self.env_file).exists():
            if os.environ.get("TAG_MANAGER_SUPPRESS_STARTUP_STATE") == "1":
                return
            # Only show warning on first run or when debugging
            try:
                from .startup_messages import startup_messages
                if startup_messages.should_show_message('env'):
                    console.print("[yellow]No .env file found. Using system environment variables only.[/yellow]")
            except ImportError:
                # Fallback if startup_messages module not available
                if os.environ.get('TAG_MANAGER_DEBUG', '0') == '1':
                    console.print("[yellow]No .env file found. Using system environment variables only.[/yellow]")
            return
        
        try:
            with open(self.env_file, 'r') as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    
                    # Skip empty lines and comments
                    if not line or line.startswith('#'):
                        continue
                    
                    # Parse key=value pairs
                    if '=' in line:
                        key, value = line.split('=', 1)
                        key = key.strip()
                        value = value.strip()
                        
                        # Remove quotes if present
                        if value.startswith('"') and value.endswith('"'):
                            value = value[1:-1]
                        elif value.startswith("'") and value.endswith("'"):
                            value = value[1:-1]
                        
                        # Only set if not already in environment
                        if key not in os.environ:
                            os.environ[key] = value
                        
                        self._env_vars[key] = value
                    else:
                        console.print(f"[yellow]Warning: Invalid line {line_num} in .env file: {line}[/yellow]")
            
            # Only show startup message on first run or when debugging
            try:
                from .startup_messages import startup_messages
                if startup_messages.should_show_message('env'):
                    console.print(f"[green]OK Loaded environment from {self.env_file}[/green]")
            except ImportError:
                # Fallback if startup_messages module not available
                if os.environ.get('TAG_MANAGER_DEBUG', '0') == '1':
                    console.print(f"[green]OK Loaded environment from {self.env_file}[/green]")
            
        except Exception as e:
            console.print(f"[red]Error loading .env file: {e}[/red]")
    
    def get(self, key: str, default: Any = None, cast_type: type = str) -> Any:
        """Get environment variable with optional type casting."""
        value = os.environ.get(key, default)
        
        if value is None:
            return default
        
        # Type casting
        try:
            if cast_type == bool:
                if isinstance(value, bool):
                    return value
                return str(value).lower() in ('true', '1', 'yes', 'on')
            elif cast_type == int:
                return int(value)
            elif cast_type == float:
                return float(value)
            elif cast_type == list:
                if isinstance(value, list):
                    return value
                if isinstance(value, str):
                    return [item.strip() for item in value.split(',') if item.strip()]
                # If value is neither list nor string, return it as a single-item list
                return [value]
            else:
                return cast_type(value)
        except (ValueError, TypeError) as e:
            console.print(f"[yellow]Warning: Could not cast {key}={value} to {cast_type.__name__}: {e}[/yellow]")
            return default
    
    def get_required(self, key: str, cast_type: type = str) -> Any:
        """Get required environment variable, raise error if not found."""
        value = self.get(key, cast_type=cast_type)
        if value is None:
            raise ValueError(f"Required environment variable '{key}' is not set")
        return value
    
    def set(self, key: str, value: str):
        """Set environment variable."""
        os.environ[key] = str(value)
        self._env_vars[key] = str(value)
    
    def reload(self):
        """Reload environment variables from .env file."""
        self._env_vars.clear()
        self._load_env_file()
    
    @property
    def loaded_vars(self) -> Dict[str, str]:
        """Get all variables loaded from .env file."""
        return self._env_vars.copy()


class ConfigSettings:
    """Centralized configuration settings for the Tag Manager CLI."""
    
    def __init__(self, env_config: Optional[EnvironmentConfig] = None):
        self.env = env_config or EnvironmentConfig()
    
    # AWS Configuration
    @property
    def aws_profile(self) -> str:
        return self.env.get('AWS_PROFILE', 'default')
    
    @property
    def aws_region(self) -> str:
        return self.env.get('AWS_REGION', 'us-east-1')
    
    @property
    def aws_default_region(self) -> str:
        return self.env.get('AWS_DEFAULT_REGION', self.aws_region)
    
    @property
    def aws_regions(self) -> list:
        return self.env.get('AWS_REGIONS', [self.aws_region], cast_type=list)
    
    # Database Configuration
    @property
    def database_url(self) -> str:
        # Always use local SQLite database for container-free operation
        # This avoids conflicts with DATABASE_URL used by other applications
        import os

        db_path = os.path.expanduser(
            self.env.get('BLUEARCH_CORE_DB_PATH', '~/.bluearch-core/data/core.db')
        )
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        return f'sqlite:///{db_path}'
    
    @property
    def postgres_db(self) -> str:
        return self.env.get('POSTGRES_DB', 'tag_manager')
    
    @property
    def postgres_user(self) -> str:
        return self.env.get('POSTGRES_USER', 'tag_manager')
    
    @property
    def postgres_password(self) -> str:
        return self.env.get('POSTGRES_PASSWORD', 'tag_manager_dev_password')
    
    # Redis Configuration (DEPRECATED - replaced with local cache)
    @property
    def redis_url(self) -> str:
        # Deprecated: Redis replaced with local file-based cache
        return self.env.get('REDIS_URL', 'redis://localhost:6379/0')

    @property
    def redis_host(self) -> str:
        # Deprecated: Redis replaced with local file-based cache
        return self.env.get('REDIS_HOST', 'localhost')

    @property
    def redis_port(self) -> int:
        # Deprecated: Redis replaced with local file-based cache
        return self.env.get('REDIS_PORT', 6379, cast_type=int)

    @property
    def redis_db(self) -> int:
        # Deprecated: Redis replaced with local file-based cache
        return self.env.get('REDIS_DB', 0, cast_type=int)
    
    # Celery Configuration (DEPRECATED - replaced with synchronous execution)
    @property
    def celery_broker_url(self) -> str:
        # Deprecated: Celery replaced with synchronous execution
        return self.env.get('CELERY_BROKER_URL', 'redis://localhost:6379/1')

    @property
    def celery_result_backend(self) -> str:
        # Deprecated: Celery replaced with synchronous execution
        return self.env.get('CELERY_RESULT_BACKEND', 'redis://localhost:6379/2')

    @property
    def celery_worker_concurrency(self) -> int:
        # Deprecated: Celery replaced with synchronous execution
        return self.env.get('CELERY_WORKER_CONCURRENCY', 4, cast_type=int)

    @property
    def celery_task_time_limit(self) -> int:
        # Deprecated: Celery replaced with synchronous execution
        return self.env.get('CELERY_TASK_TIME_LIMIT', 3600, cast_type=int)

    @property
    def celery_task_soft_time_limit(self) -> int:
        # Deprecated: Celery replaced with synchronous execution
        return self.env.get('CELERY_TASK_SOFT_TIME_LIMIT', 3000, cast_type=int)
    
    # Application Configuration
    @property
    def debug(self) -> bool:
        return self.env.get('TAG_MANAGER_DEBUG', False, cast_type=bool)

    @property
    def quiet(self) -> bool:
        """Suppress info messages (event notice, database connection, etc.).

        Default is True (quiet mode). Set TAG_MANAGER_DEBUG=1 to show messages.
        """
        return not self.debug

    @property
    def log_level(self) -> str:
        return self.env.get('TAG_MANAGER_LOG_LEVEL', 'INFO').upper()
    
    # Automated Tagging Configuration
    @property
    def auto_tagging_enabled(self) -> bool:
        return self.env.get('AUTO_TAGGING_ENABLED', True, cast_type=bool)
    
    @property
    def auto_tagging_schedule_minutes(self) -> int:
        return self.env.get('AUTO_TAGGING_SCHEDULE_MINUTES', 30, cast_type=int)
    
    @property
    def auto_tagging_max_resources_per_scan(self) -> int:
        return self.env.get('AUTO_TAGGING_MAX_RESOURCES_PER_SCAN', 1000, cast_type=int)
    
    @property
    def auto_tagging_cloudtrail_lookback_hours(self) -> int:
        return self.env.get('AUTO_TAGGING_CLOUDTRAIL_LOOKBACK_HOURS', 24, cast_type=int)
    
    @property
    def cloudtrail_lookback_minutes(self) -> int:
        return self.env.get('CLOUDTRAIL_LOOKBACK_MINUTES', 30, cast_type=int)
    
    # Rate Limiting
    @property
    def aws_api_rate_limit_per_second(self) -> int:
        return self.env.get('AWS_API_RATE_LIMIT_PER_SECOND', 10, cast_type=int)
    
    @property
    def cloudtrail_api_rate_limit_per_second(self) -> int:
        return self.env.get('CLOUDTRAIL_API_RATE_LIMIT_PER_SECOND', 5, cast_type=int)
    
    # Cache Configuration
    @property
    def cache_ttl_resources(self) -> int:
        return self.env.get('CACHE_TTL_RESOURCES', 300, cast_type=int)
    
    @property
    def cache_ttl_cloudtrail(self) -> int:
        return self.env.get('CACHE_TTL_CLOUDTRAIL', 1800, cast_type=int)
    
    @property
    def cache_ttl_tagging_rules(self) -> int:
        return self.env.get('CACHE_TTL_TAGGING_RULES', 3600, cast_type=int)
    
    # Docker Configuration
    @property
    def docker_dev_mode(self) -> bool:
        return self.env.get('DOCKER_DEV_MODE', False, cast_type=bool)
    
    def validate_required_settings(self):
        """Validate that all required settings are present."""
        required_checks = [
            ('AWS_PROFILE', self.aws_profile),
            ('AWS_REGION', self.aws_region),
        ]
        
        missing = []
        for name, value in required_checks:
            if not value:
                missing.append(name)
        
        if missing:
            raise ValueError(f"Missing required environment variables: {', '.join(missing)}")
    
    def print_config_summary(self):
        """Print a summary of current configuration."""
        from rich.table import Table
        
        table = Table(title="Configuration Summary", show_header=True, header_style="bold magenta")
        table.add_column("Setting", style="cyan", width=30)
        table.add_column("Value", style="white")
        
        config_items = [
            ("AWS Profile", self.aws_profile),
            ("AWS Region", self.aws_region),
            ("Database URL", self.database_url),
            ("Cache", "Local file-based (diskcache)"),
            ("Debug Mode", str(self.debug)),
            ("Log Level", self.log_level),
            ("Auto Tagging", str(self.auto_tagging_enabled)),
        ]
        
        for setting, value in config_items:
            # Mask sensitive values
            if 'password' in setting.lower() or 'url' in setting.lower():
                if '://' in value:
                    # Mask password in URL
                    parts = value.split('://', 1)
                    if '@' in parts[1]:
                        auth_part, host_part = parts[1].split('@', 1)
                        if ':' in auth_part:
                            user, _ = auth_part.split(':', 1)
                            value = f"{parts[0]}://{user}:***@{host_part}"
                else:
                    value = "***"
            
            table.add_row(setting, value)
        
        console.print(table)


# Global configuration instance
settings = ConfigSettings()
