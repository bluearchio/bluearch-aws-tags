"""Add assume role configuration table

Revision ID: 009_add_assume_role_configuration
Revises: 008_add_policy_source_tracking
Create Date: 2026-01-20 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '009_add_assume_role_configuration'
down_revision = '008_add_policy_source_tracking'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create assume_role_configurations table for storing assume-role settings."""

    op.create_table(
        'assume_role_configurations',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('account_id', sa.String(12), nullable=False),
        sa.Column('role_arn', sa.String(2048), nullable=False),
        sa.Column('role_name', sa.String(64), nullable=False, server_default='TagManagerCLIRole'),
        sa.Column('external_id', sa.String(256), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='0'),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default='1'),
        sa.Column('alias', sa.String(64), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )

    # Create indexes for performance
    op.create_index('idx_assume_role_account_id', 'assume_role_configurations', ['account_id'])
    op.create_index('idx_assume_role_is_active', 'assume_role_configurations', ['is_active'])
    op.create_index('idx_assume_role_account_active', 'assume_role_configurations', ['account_id', 'is_active'])
    op.create_index('idx_assume_role_active_enabled', 'assume_role_configurations', ['is_active', 'enabled'])


def downgrade() -> None:
    """Drop assume_role_configurations table."""

    # Drop indexes
    op.drop_index('idx_assume_role_active_enabled', table_name='assume_role_configurations')
    op.drop_index('idx_assume_role_account_active', table_name='assume_role_configurations')
    op.drop_index('idx_assume_role_is_active', table_name='assume_role_configurations')
    op.drop_index('idx_assume_role_account_id', table_name='assume_role_configurations')

    # Drop table
    op.drop_table('assume_role_configurations')
