"""Add account context and permission cache tables

Revision ID: 013_add_account_context_and_permissions
Revises: 012_add_event_sync_configuration
Create Date: 2026-02-20 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '013_add_account_context_and_permissions'
down_revision = '012_add_event_sync_configuration'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create account_context, permission_cache, and permission_tier tables."""

    op.create_table(
        'account_context',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('account_id', sa.String(12), nullable=False),
        sa.Column('account_alias', sa.String(256), nullable=True),
        sa.Column('aws_profile', sa.String(256), nullable=True),
        sa.Column('region', sa.String(50), nullable=True),
        sa.Column('user_arn', sa.String(256), nullable=True),
        sa.Column('is_current', sa.Boolean(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint('account_id', name='uq_account_context_account_id'),
    )
    op.create_index('idx_account_context_current', 'account_context', ['is_current'])
    op.create_index('idx_account_context_account_id', 'account_context', ['account_id'])

    op.create_table(
        'permission_cache',
        sa.Column('account_id', sa.String(12), nullable=False),
        sa.Column('user_arn', sa.String(256), nullable=False),
        sa.Column('action', sa.String(128), nullable=False),
        sa.Column('granted', sa.Boolean(), nullable=False),
        sa.Column('checked_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('account_id', 'user_arn', 'action'),
    )

    op.create_table(
        'permission_tier',
        sa.Column('account_id', sa.String(12), nullable=False),
        sa.Column('user_arn', sa.String(256), nullable=False),
        sa.Column('tier', sa.String(20), nullable=False),
        sa.Column('features_json', sa.JSON(), nullable=False),
        sa.Column('checked_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('account_id', 'user_arn'),
    )


def downgrade() -> None:
    """Drop permission_tier, permission_cache, and account_context tables."""

    op.drop_table('permission_tier')
    op.drop_table('permission_cache')
    op.drop_index('idx_account_context_account_id', table_name='account_context')
    op.drop_index('idx_account_context_current', table_name='account_context')
    op.drop_table('account_context')
