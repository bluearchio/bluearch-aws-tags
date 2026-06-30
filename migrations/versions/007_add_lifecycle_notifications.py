"""Add lifecycle notification and decision tables plus enhanced columns

Revision ID: 007_add_lifecycle_notifications
Revises: 006_add_finops_tables
Create Date: 2026-01-12 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '007_add_lifecycle_notifications'
down_revision = '006_add_finops_tables'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add lifecycle notification/decision tables and enhanced resource columns."""

    # Add new columns to resources table
    op.add_column('resources', sa.Column('ttl_source', sa.String(50), nullable=True))
    op.add_column('resources', sa.Column('ttl_tag_key', sa.String(256), nullable=True))
    op.add_column('resources', sa.Column('owner_email', sa.String(256), nullable=True))
    op.add_column('resources', sa.Column('grace_period_ends_at', sa.DateTime(timezone=True), nullable=True))

    # Add indexes for new resource columns
    op.create_index('idx_resource_owner_email', 'resources', ['owner_email'])
    op.create_index('idx_resource_grace_period', 'resources', ['grace_period_ends_at'])

    # Add new columns to resource_lifecycle_policies table
    op.add_column('resource_lifecycle_policies', sa.Column('warning_schedule', sa.JSON(), nullable=True))
    op.add_column('resource_lifecycle_policies', sa.Column('grace_period_days', sa.Integer(), nullable=True, server_default='7'))
    op.add_column('resource_lifecycle_policies', sa.Column('auto_delete_enabled', sa.Boolean(), nullable=True, server_default='0'))

    # Create lifecycle_notifications table
    op.create_table('lifecycle_notifications',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('batch_id', sa.String(36), nullable=True),
        sa.Column('resource_arn', sa.String(1024), nullable=False),
        sa.Column('resource_id', sa.String(36), nullable=True),
        sa.Column('notification_type', sa.String(50), nullable=False),
        sa.Column('channel', sa.String(50), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('message_summary', sa.Text(), nullable=True),
        sa.Column('message_details', sa.JSON(), nullable=True),
        sa.Column('scheduled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('delivery_response', sa.JSON(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('retry_count', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('days_until_expiry', sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['resource_id'], ['resources.id'], ondelete='SET NULL')
    )

    # Create indexes for lifecycle_notifications
    op.create_index('idx_notification_batch', 'lifecycle_notifications', ['batch_id'])
    op.create_index('idx_notification_resource_type', 'lifecycle_notifications', ['resource_arn', 'notification_type'])
    op.create_index('idx_notification_status_channel', 'lifecycle_notifications', ['status', 'channel'])
    op.create_index('idx_notification_created', 'lifecycle_notifications', ['created_at'])
    op.create_index('idx_notification_scheduled', 'lifecycle_notifications', ['scheduled_at', 'status'])

    # Create lifecycle_decisions table
    op.create_table('lifecycle_decisions',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('resource_arn', sa.String(1024), nullable=False),
        sa.Column('resource_id', sa.String(36), nullable=True),
        sa.Column('decision_type', sa.String(50), nullable=False),
        sa.Column('decision_reason', sa.Text(), nullable=True),
        sa.Column('previous_state', sa.String(50), nullable=True),
        sa.Column('new_state', sa.String(50), nullable=True),
        sa.Column('previous_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('new_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('extension_days', sa.Integer(), nullable=True),
        sa.Column('protection_reason', sa.Text(), nullable=True),
        sa.Column('protection_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('decided_by', sa.String(256), nullable=False),
        sa.Column('decided_via', sa.String(50), nullable=True),
        sa.Column('decided_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('notification_id', sa.String(36), nullable=True),
        sa.Column('executed', sa.Boolean(), nullable=True, server_default='0'),
        sa.Column('executed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('execution_error', sa.Text(), nullable=True),
        sa.Column('metadata', sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['resource_id'], ['resources.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['notification_id'], ['lifecycle_notifications.id'], ondelete='SET NULL')
    )

    # Create indexes for lifecycle_decisions
    op.create_index('idx_decision_resource_type', 'lifecycle_decisions', ['resource_arn', 'decision_type'])
    op.create_index('idx_decision_decided_by', 'lifecycle_decisions', ['decided_by', 'decided_at'])
    op.create_index('idx_decision_type_executed', 'lifecycle_decisions', ['decision_type', 'executed'])
    op.create_index('idx_decision_decided_at', 'lifecycle_decisions', ['decided_at'])

    print("[OK] Added ttl_source, ttl_tag_key, owner_email, grace_period_ends_at to resources table")
    print("[OK] Added warning_schedule, grace_period_days, auto_delete_enabled to resource_lifecycle_policies table")
    print("[OK] Created lifecycle_notifications table for tracking notifications")
    print("[OK] Created lifecycle_decisions table for tracking user decisions")


def downgrade() -> None:
    """Remove lifecycle notification/decision tables and columns."""

    # Drop lifecycle_decisions indexes and table
    op.drop_index('idx_decision_decided_at', table_name='lifecycle_decisions')
    op.drop_index('idx_decision_type_executed', table_name='lifecycle_decisions')
    op.drop_index('idx_decision_decided_by', table_name='lifecycle_decisions')
    op.drop_index('idx_decision_resource_type', table_name='lifecycle_decisions')
    op.drop_table('lifecycle_decisions')

    # Drop lifecycle_notifications indexes and table
    op.drop_index('idx_notification_scheduled', table_name='lifecycle_notifications')
    op.drop_index('idx_notification_created', table_name='lifecycle_notifications')
    op.drop_index('idx_notification_status_channel', table_name='lifecycle_notifications')
    op.drop_index('idx_notification_resource_type', table_name='lifecycle_notifications')
    op.drop_index('idx_notification_batch', table_name='lifecycle_notifications')
    op.drop_table('lifecycle_notifications')

    # Drop new columns from resource_lifecycle_policies
    op.drop_column('resource_lifecycle_policies', 'auto_delete_enabled')
    op.drop_column('resource_lifecycle_policies', 'grace_period_days')
    op.drop_column('resource_lifecycle_policies', 'warning_schedule')

    # Drop new resource columns indexes and columns
    op.drop_index('idx_resource_grace_period', table_name='resources')
    op.drop_index('idx_resource_owner_email', table_name='resources')
    op.drop_column('resources', 'grace_period_ends_at')
    op.drop_column('resources', 'owner_email')
    op.drop_column('resources', 'ttl_tag_key')
    op.drop_column('resources', 'ttl_source')

    print("[OK] Removed lifecycle notification and decision tables and columns")
