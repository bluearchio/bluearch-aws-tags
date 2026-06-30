"""Initial SQLite schema for container-free deployment.

Revision ID: 001_initial_sqlite
Revises:
Create Date: 2025-01-04

This migration creates the initial database schema for SQLite,
replacing the PostgreSQL-specific migrations with SQLite-compatible versions.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import JSON, String, DateTime, Boolean, Integer, Text, Index


# Revision identifiers
revision = '001_initial_sqlite'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create initial SQLite schema."""

    # Create resources table
    op.create_table('resources',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('resource_arn', sa.String(1024), nullable=False, unique=True),
        sa.Column('resource_type', sa.String(100), nullable=False),
        sa.Column('service_name', sa.String(50), nullable=False),
        sa.Column('region', sa.String(50), nullable=False),
        sa.Column('account_id', sa.String(12), nullable=False),
        sa.Column('resource_id', sa.String(256), nullable=False),
        sa.Column('created_by', sa.String(256)),
        sa.Column('created_at', sa.DateTime(timezone=True)),
        sa.Column('discovered_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_scanned_at', sa.DateTime(timezone=True)),
        sa.Column('current_tags', JSON),
        sa.Column('metadata', JSON),
        sa.Column('expires_at', sa.DateTime(timezone=True)),
        sa.Column('lifecycle_state', sa.String(50), default='active'),
        sa.Column('delete_after', sa.DateTime(timezone=True)),
        sa.Column('protected', sa.Boolean, default=False),
        sa.Column('warned_at', sa.DateTime(timezone=True)),
        sa.Column('warning_count', sa.Integer, default=0),
        sa.Column('lifecycle_policy_id', sa.String(36))
    )

    # Create indexes for resources
    op.create_index('idx_resource_arn', 'resources', ['resource_arn'])
    op.create_index('idx_resource_type', 'resources', ['resource_type'])
    op.create_index('idx_service_name', 'resources', ['service_name'])
    op.create_index('idx_region', 'resources', ['region'])
    op.create_index('idx_account_id', 'resources', ['account_id'])
    op.create_index('idx_created_by', 'resources', ['created_by'])
    op.create_index('idx_lifecycle_state', 'resources', ['lifecycle_state'])
    op.create_index('idx_expires_at', 'resources', ['expires_at'])
    op.create_index('idx_resource_type_region', 'resources', ['resource_type', 'region'])
    op.create_index('idx_service_created_at', 'resources', ['service_name', 'created_at'])
    op.create_index('idx_lifecycle_state_expires', 'resources', ['lifecycle_state', 'expires_at'])

    # Create tagging_rules table
    op.create_table('tagging_rules',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('rule_name', sa.String(256), nullable=False, unique=True),
        sa.Column('description', sa.Text),
        sa.Column('enabled', sa.Boolean, default=True),
        sa.Column('priority', sa.Integer, default=0),
        sa.Column('resource_types', JSON, nullable=False),  # Array stored as JSON
        sa.Column('tag_key', sa.String(256), nullable=False),
        sa.Column('tag_value', sa.String(256), nullable=False),
        sa.Column('condition_type', sa.String(50)),
        sa.Column('condition_value', sa.Text),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True)),
        sa.Column('created_by', sa.String(256)),
        sa.Column('last_applied_at', sa.DateTime(timezone=True)),
        sa.Column('apply_count', sa.Integer, default=0)
    )

    op.create_index('idx_rule_enabled', 'tagging_rules', ['enabled'])
    op.create_index('idx_rule_priority', 'tagging_rules', ['priority'])

    # Create tagging_audit_log table
    op.create_table('tagging_audit_log',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('resource_id', sa.String(36)),
        sa.Column('resource_arn', sa.String(1024)),
        sa.Column('action', sa.String(50), nullable=False),
        sa.Column('rule_id', sa.String(36)),
        sa.Column('rule_name', sa.String(256)),
        sa.Column('tags_before', JSON),
        sa.Column('tags_after', JSON),
        sa.Column('executed_by', sa.String(256)),
        sa.Column('execution_source', sa.String(50)),
        sa.Column('executed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('success', sa.Boolean, default=True),
        sa.Column('error_message', sa.Text),
        sa.Column('execution_time_ms', sa.Integer),
        sa.Column('dry_run', sa.Boolean, default=False)
    )

    op.create_index('idx_audit_resource_id', 'tagging_audit_log', ['resource_id'])
    op.create_index('idx_audit_action', 'tagging_audit_log', ['action'])
    op.create_index('idx_audit_executed_at', 'tagging_audit_log', ['executed_at'])
    op.create_index('idx_audit_executed_by', 'tagging_audit_log', ['executed_by'])

    # Create system_executions table
    op.create_table('system_executions',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('task_name', sa.String(256), nullable=False, unique=True),
        sa.Column('task_type', sa.String(100)),
        sa.Column('last_execution_at', sa.DateTime(timezone=True)),
        sa.Column('execution_status', sa.String(50)),
        sa.Column('execution_message', sa.Text),
        sa.Column('execution_duration_seconds', sa.Integer),
        sa.Column('records_processed', sa.Integer),
        sa.Column('error_count', sa.Integer, default=0),
        sa.Column('next_scheduled_at', sa.DateTime(timezone=True)),
        sa.Column('metadata', JSON),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True))
    )

    op.create_index('idx_system_task_name', 'system_executions', ['task_name'])
    op.create_index('idx_system_last_execution', 'system_executions', ['last_execution_at'])
    op.create_index('idx_system_next_scheduled', 'system_executions', ['next_scheduled_at'])

    # Create resource_lifecycle_policies table
    op.create_table('resource_lifecycle_policies',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('policy_name', sa.String(256), nullable=False, unique=True),
        sa.Column('description', sa.Text),
        sa.Column('enabled', sa.Boolean, default=True),
        sa.Column('resource_types', JSON, nullable=False),
        sa.Column('ttl_days', sa.Integer),
        sa.Column('warning_days', sa.Integer, default=7),
        sa.Column('action', sa.String(50), default='delete'),
        sa.Column('tag_conditions', JSON),
        sa.Column('metadata_conditions', JSON),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True)),
        sa.Column('created_by', sa.String(256)),
        sa.Column('last_applied_at', sa.DateTime(timezone=True)),
        sa.Column('resources_affected', sa.Integer, default=0)
    )

    op.create_index('idx_lifecycle_enabled', 'resource_lifecycle_policies', ['enabled'])
    op.create_index('idx_lifecycle_last_applied', 'resource_lifecycle_policies', ['last_applied_at'])

    # Create worker_registry table
    op.create_table('worker_registry',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('worker_name', sa.String(256), nullable=False, unique=True),
        sa.Column('worker_type', sa.String(100)),
        sa.Column('hostname', sa.String(256)),
        sa.Column('process_id', sa.Integer),
        sa.Column('status', sa.String(50), default='unknown'),
        sa.Column('last_heartbeat', sa.DateTime(timezone=True)),
        sa.Column('started_at', sa.DateTime(timezone=True)),
        sa.Column('tasks_processed', sa.Integer, default=0),
        sa.Column('tasks_failed', sa.Integer, default=0),
        sa.Column('current_task', sa.String(256)),
        sa.Column('metadata', JSON),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True))
    )

    op.create_index('idx_worker_name', 'worker_registry', ['worker_name'])
    op.create_index('idx_worker_status', 'worker_registry', ['status'])
    op.create_index('idx_worker_heartbeat', 'worker_registry', ['last_heartbeat'])

    # Create cache_metadata table
    op.create_table('cache_metadata',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('cache_key', sa.String(512), nullable=False, unique=True),
        sa.Column('cache_type', sa.String(50)),
        sa.Column('service', sa.String(50)),
        sa.Column('operation', sa.String(100)),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True)),
        sa.Column('hit_count', sa.Integer, default=0),
        sa.Column('last_accessed_at', sa.DateTime(timezone=True)),
        sa.Column('size_bytes', sa.Integer),
        sa.Column('metadata', JSON)
    )

    op.create_index('idx_cache_key', 'cache_metadata', ['cache_key'])
    op.create_index('idx_cache_expires', 'cache_metadata', ['expires_at'])
    op.create_index('idx_cache_service', 'cache_metadata', ['service'])


def downgrade() -> None:
    """Drop all tables."""
    op.drop_table('cache_metadata')
    op.drop_table('worker_registry')
    op.drop_table('resource_lifecycle_policies')
    op.drop_table('system_executions')
    op.drop_table('tagging_audit_log')
    op.drop_table('tagging_rules')
    op.drop_table('resources')