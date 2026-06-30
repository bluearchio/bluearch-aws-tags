"""Rename execution_duration_seconds to execution_duration_ms.

Revision ID: 002_duration_to_ms
Revises: 001_initial_sqlite
Create Date: 2025-01-05

This migration renames the execution_duration_seconds column to execution_duration_ms
and converts the values from seconds to milliseconds for better precision.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import JSON


# Revision identifiers
revision = '002_duration_to_ms'
down_revision = '001_initial_sqlite'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Rename execution_duration_seconds to execution_duration_ms."""

    # SQLite doesn't support ALTER COLUMN, so we need to recreate the table

    # Create new table with correct column name
    op.create_table('system_executions_new',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('task_name', sa.String(256), nullable=False, unique=True),
        sa.Column('task_type', sa.String(100)),
        sa.Column('last_execution_at', sa.DateTime(timezone=True)),
        sa.Column('execution_status', sa.String(50)),
        sa.Column('execution_message', sa.Text),
        sa.Column('execution_duration_ms', sa.Integer),  # Changed from _seconds
        sa.Column('records_processed', sa.Integer),
        sa.Column('error_count', sa.Integer, default=0),
        sa.Column('next_scheduled_at', sa.DateTime(timezone=True)),
        sa.Column('metadata', JSON),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True))
    )

    # Copy data from old table, converting seconds to milliseconds
    op.execute("""
        INSERT INTO system_executions_new (
            id, task_name, task_type, last_execution_at, execution_status,
            execution_message, execution_duration_ms, records_processed,
            error_count, next_scheduled_at, metadata, created_at, updated_at
        )
        SELECT
            id, task_name, task_type, last_execution_at, execution_status,
            execution_message,
            CASE
                WHEN execution_duration_seconds IS NOT NULL
                THEN execution_duration_seconds * 1000  -- Convert seconds to milliseconds
                ELSE NULL
            END as execution_duration_ms,
            records_processed, error_count, next_scheduled_at, metadata,
            created_at, updated_at
        FROM system_executions
    """)

    # Drop old table
    op.drop_table('system_executions')

    # Rename new table to original name
    op.rename_table('system_executions_new', 'system_executions')

    # Recreate indexes
    op.create_index('idx_system_task_name', 'system_executions', ['task_name'])
    op.create_index('idx_system_last_execution', 'system_executions', ['last_execution_at'])
    op.create_index('idx_system_next_scheduled', 'system_executions', ['next_scheduled_at'])


def downgrade() -> None:
    """Revert execution_duration_ms back to execution_duration_seconds."""

    # Create table with old column name
    op.create_table('system_executions_new',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('task_name', sa.String(256), nullable=False, unique=True),
        sa.Column('task_type', sa.String(100)),
        sa.Column('last_execution_at', sa.DateTime(timezone=True)),
        sa.Column('execution_status', sa.String(50)),
        sa.Column('execution_message', sa.Text),
        sa.Column('execution_duration_seconds', sa.Integer),  # Back to _seconds
        sa.Column('records_processed', sa.Integer),
        sa.Column('error_count', sa.Integer, default=0),
        sa.Column('next_scheduled_at', sa.DateTime(timezone=True)),
        sa.Column('metadata', JSON),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True))
    )

    # Copy data back, converting milliseconds to seconds
    op.execute("""
        INSERT INTO system_executions_new (
            id, task_name, task_type, last_execution_at, execution_status,
            execution_message, execution_duration_seconds, records_processed,
            error_count, next_scheduled_at, metadata, created_at, updated_at
        )
        SELECT
            id, task_name, task_type, last_execution_at, execution_status,
            execution_message,
            CASE
                WHEN execution_duration_ms IS NOT NULL
                THEN execution_duration_ms / 1000  -- Convert milliseconds back to seconds
                ELSE NULL
            END as execution_duration_seconds,
            records_processed, error_count, next_scheduled_at, metadata,
            created_at, updated_at
        FROM system_executions
    """)

    # Drop new table
    op.drop_table('system_executions')

    # Rename back to original name
    op.rename_table('system_executions_new', 'system_executions')

    # Recreate indexes
    op.create_index('idx_system_task_name', 'system_executions', ['task_name'])
    op.create_index('idx_system_last_execution', 'system_executions', ['last_execution_at'])
    op.create_index('idx_system_next_scheduled', 'system_executions', ['next_scheduled_at'])
