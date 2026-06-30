"""Add event sync configuration table

Revision ID: 012_add_event_sync_configuration
Revises: 011_add_evaluation_tier
Create Date: 2026-02-20 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '012_add_event_sync_configuration'
down_revision = '011_add_evaluation_tier'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create event_sync_configuration table for event-driven resource sync."""

    op.create_table(
        'event_sync_configuration',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('account_id', sa.String(20), nullable=False),
        sa.Column('region', sa.String(30), nullable=False),
        sa.Column('queue_url', sa.String(512), nullable=False),
        sa.Column('queue_arn', sa.String(512), nullable=False),
        sa.Column('stack_name', sa.String(256), nullable=False),
        sa.Column('stack_id', sa.String(512), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='deploying'),
        sa.Column('deployed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_polled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_event_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('messages_processed', sa.Integer(), server_default='0'),
        sa.Column('events_today', sa.Integer(), server_default='0'),
        sa.Column('events_today_reset_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('account_id', 'region', name='uq_event_sync_account_region'),
    )

    # Create indexes for performance
    op.create_index('idx_event_sync_status', 'event_sync_configuration', ['status'])
    op.create_index('idx_event_sync_account_region', 'event_sync_configuration', ['account_id', 'region'])
    op.create_index('idx_event_sync_last_polled', 'event_sync_configuration', ['last_polled_at'])


def downgrade() -> None:
    """Drop event_sync_configuration table."""

    # Drop indexes
    op.drop_index('idx_event_sync_last_polled', table_name='event_sync_configuration')
    op.drop_index('idx_event_sync_account_region', table_name='event_sync_configuration')
    op.drop_index('idx_event_sync_status', table_name='event_sync_configuration')

    # Drop table
    op.drop_table('event_sync_configuration')
