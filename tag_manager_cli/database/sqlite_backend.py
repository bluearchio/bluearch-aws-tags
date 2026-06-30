"""SQLite database backend implementation for Tag Manager CLI."""

import os
import sqlite3
from pathlib import Path
from typing import Optional, Dict, Any
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from rich.console import Console

console = Console()


class SQLiteBackend:
    """SQLite-specific database configuration and setup."""

    # Shared database with BlueArch CLI — both CLIs read/write the same DB
    DEFAULT_DB_PATH = "~/.bluearch/data/bluearch.db"

    @staticmethod
    def get_database_url(custom_path: Optional[str] = None) -> str:
        """Get SQLite database URL, creating directories if needed."""
        db_path = custom_path or SQLiteBackend.DEFAULT_DB_PATH
        db_path = os.path.expanduser(db_path)

        # Create directory if it doesn't exist
        db_dir = os.path.dirname(db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, mode=0o755, exist_ok=True)
            console.print(f"[green]Created database directory: {db_dir}[/green]")

        # Return SQLite URL
        return f"sqlite:///{db_path}"

    @staticmethod
    def configure_engine(engine: Engine) -> None:
        """Configure SQLite-specific engine settings."""

        @event.listens_for(engine, "connect")
        def set_sqlite_pragma(dbapi_conn, connection_record):
            """Set SQLite pragmas for better performance and compatibility."""
            if isinstance(dbapi_conn, sqlite3.Connection):
                cursor = dbapi_conn.cursor()

                # Enable foreign keys
                cursor.execute("PRAGMA foreign_keys=ON")

                # Performance optimizations
                cursor.execute("PRAGMA journal_mode=WAL")  # Write-Ahead Logging
                cursor.execute("PRAGMA synchronous=NORMAL")  # Balance safety/speed
                cursor.execute("PRAGMA temp_store=MEMORY")  # Use memory for temp tables
                cursor.execute("PRAGMA mmap_size=30000000000")  # Use memory-mapped I/O

                # Set busy timeout to 30 seconds (avoid locking issues)
                cursor.execute("PRAGMA busy_timeout=30000")

                cursor.close()

    @staticmethod
    def get_connection_args() -> Dict[str, Any]:
        """Get SQLite-specific connection arguments."""
        return {
            "check_same_thread": False,  # Allow multi-threading
            "timeout": 30.0,  # Connection timeout in seconds
            "isolation_level": None,  # Autocommit mode
        }

    @staticmethod
    def check_tables_exist_query() -> str:
        """Get SQLite-specific query to check if tables exist."""
        return """
            SELECT COUNT(*)
            FROM sqlite_master
            WHERE type='table'
            AND name IN ('resources', 'tagging_rules', 'tagging_audit_log', 'system_executions')
        """

    @staticmethod
    def migrate_from_postgresql(pg_url: str, sqlite_url: str) -> bool:
        """Migrate data from PostgreSQL to SQLite.

        Args:
            pg_url: PostgreSQL database URL
            sqlite_url: SQLite database URL

        Returns:
            bool: True if migration successful, False otherwise
        """
        try:
            import psycopg2
            from sqlalchemy import create_engine, MetaData, Table
            from sqlalchemy.orm import sessionmaker

            console.print("[yellow]Starting PostgreSQL to SQLite migration...[/yellow]")

            # Connect to both databases
            pg_engine = create_engine(pg_url)
            sqlite_engine = create_engine(sqlite_url)

            # Get metadata from PostgreSQL
            pg_metadata = MetaData()
            pg_metadata.reflect(bind=pg_engine)

            # Create tables in SQLite
            sqlite_metadata = MetaData()

            # Copy table structures
            for table_name in pg_metadata.tables:
                table = pg_metadata.tables[table_name]
                new_table = table.to_metadata(sqlite_metadata)

            sqlite_metadata.create_all(sqlite_engine)

            # Copy data
            pg_session = sessionmaker(bind=pg_engine)()
            sqlite_session = sessionmaker(bind=sqlite_engine)()

            for table_name in pg_metadata.tables:
                console.print(f"  Migrating table: {table_name}")

                # Read from PostgreSQL
                pg_table = pg_metadata.tables[table_name]
                rows = pg_session.execute(pg_table.select()).fetchall()

                # Write to SQLite
                if rows:
                    sqlite_table = sqlite_metadata.tables[table_name]
                    for row in rows:
                        sqlite_session.execute(sqlite_table.insert().values(**row._asdict()))

                    sqlite_session.commit()
                    console.print(f"    [green]OK[/green] Migrated {len(rows)} rows")

            pg_session.close()
            sqlite_session.close()

            console.print("[green]Migration completed successfully![/green]")
            return True

        except ImportError:
            console.print("[red]ERROR: psycopg2 not installed. Cannot migrate from PostgreSQL.[/red]")
            console.print("[yellow]Install with: pip install psycopg2-binary[/yellow]")
            return False
        except Exception as e:
            console.print(f"[red]Migration failed: {e}[/red]")
            return False

    # Maximum number of backups to keep
    MAX_BACKUPS = 5

    @staticmethod
    def backup_database(db_path: Optional[str] = None, max_backups: int = 5) -> Optional[str]:
        """Create a backup of the SQLite database with automatic rotation.

        Backups are stored in ~/.tag-manager/backups/ and automatically
        rotated to keep only the last max_backups files.

        Args:
            db_path: Path to database to backup (defaults to main database)
            max_backups: Maximum number of backups to keep (default: 5)

        Returns:
            str: Path to backup file if successful, None otherwise
        """
        try:
            import shutil
            import glob
            from datetime import datetime

            if not db_path:
                db_path = os.path.expanduser(SQLiteBackend.DEFAULT_DB_PATH)

            if not os.path.exists(db_path):
                console.print("[yellow]No database to backup[/yellow]")
                return None

            # Use dedicated backups directory
            tag_manager_home = os.path.expanduser("~/.tag-manager")
            backup_dir = os.path.join(tag_manager_home, "backups")
            os.makedirs(backup_dir, exist_ok=True)

            # Create backup filename with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_name = f"tag-manager-backup-{timestamp}.db"
            backup_path = os.path.join(backup_dir, backup_name)

            # Copy database file
            shutil.copy2(db_path, backup_path)

            console.print(f"[green]Database backed up to: {backup_path}[/green]")

            # Cleanup old backups - keep only the last max_backups
            backup_pattern = os.path.join(backup_dir, "tag-manager-backup-*.db")
            existing_backups = sorted(glob.glob(backup_pattern), reverse=True)

            if len(existing_backups) > max_backups:
                console.print(f"[dim]Cleaning up old backups (keeping last {max_backups})...[/dim]")
                for old_backup in existing_backups[max_backups:]:
                    try:
                        os.remove(old_backup)
                    except Exception:
                        pass  # Ignore errors removing old backups
                console.print(f"[dim]Backups: {min(len(existing_backups), max_backups)} files[/dim]")

            return backup_path

        except Exception as e:
            console.print(f"[red]Backup failed: {e}[/red]")
            return None

    @staticmethod
    def list_backups() -> list:
        """List all available database backups.

        Returns:
            list: List of backup file paths, sorted by date (newest first)
        """
        import glob

        tag_manager_home = os.path.expanduser("~/.tag-manager")
        backup_dir = os.path.join(tag_manager_home, "backups")
        backup_pattern = os.path.join(backup_dir, "tag-manager-backup-*.db")

        return sorted(glob.glob(backup_pattern), reverse=True)

    @staticmethod
    def restore_backup(backup_path: str, db_path: Optional[str] = None) -> bool:
        """Restore database from a backup file.

        Args:
            backup_path: Path to the backup file
            db_path: Path to restore to (defaults to main database)

        Returns:
            bool: True if restore successful
        """
        try:
            import shutil

            if not db_path:
                db_path = os.path.expanduser(SQLiteBackend.DEFAULT_DB_PATH)

            if not os.path.exists(backup_path):
                console.print(f"[red]Backup file not found: {backup_path}[/red]")
                return False

            # Create backup of current database before restore
            if os.path.exists(db_path):
                SQLiteBackend.backup_database(db_path, max_backups=10)

            # Restore from backup
            shutil.copy2(backup_path, db_path)
            console.print(f"[green]Database restored from: {backup_path}[/green]")
            return True

        except Exception as e:
            console.print(f"[red]Restore failed: {e}[/red]")
            return False

    @staticmethod
    def optimize_database(engine: Engine) -> bool:
        """Optimize SQLite database (VACUUM and ANALYZE).

        Args:
            engine: SQLAlchemy engine

        Returns:
            bool: True if optimization successful
        """
        try:
            with engine.connect() as conn:
                # VACUUM cannot run inside a transaction
                conn.execute("VACUUM")
                conn.execute("ANALYZE")
                conn.commit()

            console.print("[green]Database optimized successfully[/green]")
            return True

        except Exception as e:
            console.print(f"[red]Optimization failed: {e}[/red]")
            return False


class PostgreSQLBackend:
    """PostgreSQL-specific database configuration for backward compatibility."""

    @staticmethod
    def configure_engine(engine: Engine) -> None:
        """Configure PostgreSQL-specific engine settings."""

        @event.listens_for(engine, "connect")
        def set_postgresql_options(dbapi_connection, connection_record):
            """Set PostgreSQL-specific options on connection."""
            with dbapi_connection.cursor() as cursor:
                cursor.execute("SET timezone = 'UTC'")
                cursor.execute("SET statement_timeout = '30s'")

    @staticmethod
    def get_connection_args() -> Dict[str, Any]:
        """Get PostgreSQL-specific connection arguments."""
        return {
            "application_name": "tag_manager_cli",
            "connect_timeout": 30,
        }

    @staticmethod
    def check_tables_exist_query() -> str:
        """Get PostgreSQL-specific query to check if tables exist."""
        return """
            SELECT COUNT(*)
            FROM information_schema.tables
            WHERE table_schema = 'public'
            AND table_name IN ('resources', 'tagging_rules', 'tagging_audit_log', 'system_executions')
        """