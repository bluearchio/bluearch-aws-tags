"""Add account_status table for multi-account tracking

Revision ID: 005_add_account_status
Revises: 004_add_execution_id_to_audit_log
Create Date: 2025-11-14 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from datetime import datetime

# revision identifiers, used by Alembic.
revision = '005_add_account_status'
down_revision = '004_add_execution_id_to_audit_log'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create account_status table for tracking multi-account configuration."""

    # Create the account_status table
    op.create_table('account_status',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('account_id', sa.String(12), nullable=False),
        sa.Column('account_name', sa.String(255), nullable=False),
        sa.Column('account_email', sa.String(255), nullable=True),
        sa.Column('organizational_unit_id', sa.String(100), nullable=True),
        sa.Column('organizational_unit_path', sa.String(500), nullable=True),
        sa.Column('status', sa.String(50), nullable=False, server_default='ACTIVE'),
        sa.Column('is_management_account', sa.Boolean(), nullable=True, server_default=sa.false()),
        sa.Column('is_delegated_admin', sa.Boolean(), nullable=True, server_default=sa.false()),
        sa.Column('enabled_for_discovery', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('enabled_for_tagging', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('role_name', sa.String(100), nullable=True, server_default='TagManagerRole'),
        sa.Column('role_arn', sa.String(1024), nullable=True),
        sa.Column('last_access_check', sa.DateTime(timezone=True), nullable=True),
        sa.Column('access_check_status', sa.String(50), nullable=True),
        sa.Column('access_check_error', sa.Text(), nullable=True),
        sa.Column('last_discovery_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('total_resources_discovered', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('last_discovery_duration_seconds', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True, server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.Column('enabled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('disabled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('metadata', sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )

    # Create indexes for the account_status table
    op.create_index('idx_account_id_unique', 'account_status', ['account_id'], unique=True)
    op.create_index('idx_account_status_enabled', 'account_status', ['enabled_for_discovery', 'enabled_for_tagging'])
    op.create_index('idx_account_ou', 'account_status', ['organizational_unit_id', 'enabled_for_discovery'])
    op.create_index('idx_account_status_updated', 'account_status', ['status', 'updated_at'])
    op.create_index('idx_account_last_discovery', 'account_status', ['last_discovery_at'])

    # Check if resources table already has account_id column
    # (It already exists in the model, but we need to ensure it exists in the database)
    connection = op.get_bind()
    inspector = sa.inspect(connection)

    # Check if account_id column exists in resources table
    columns = [col['name'] for col in inspector.get_columns('resources')]

    if 'account_id' not in columns:
        # Add account_id column to resources table if it doesn't exist
        op.add_column('resources', sa.Column('account_id', sa.String(12), nullable=True))

        # Create index on account_id
        op.create_index('idx_resources_account_id', 'resources', ['account_id'])

        # Update existing records to use the current account ID if available
        # This will be a no-op for new installations
        try:
            # Try to get current account ID from AWS
            # This is a best-effort approach - if it fails, we'll just leave NULL
            op.execute(text("""
                UPDATE resources
                SET account_id = SUBSTR(resource_arn,
                    INSTR(resource_arn, ':') + 1,
                    INSTR(SUBSTR(resource_arn, INSTR(resource_arn, ':') + 1), ':') - 1
                )
                WHERE account_id IS NULL AND resource_arn LIKE 'arn:aws:%'
            """))
        except Exception:
            # If the update fails, it's not critical - we can update later
            pass

    print("[OK] Created account_status table for multi-account tracking")
    print("[OK] Added indexes for optimal query performance")


def downgrade() -> None:
    """Remove account_status table and related changes."""

    # Drop indexes
    op.drop_index('idx_account_last_discovery', table_name='account_status')
    op.drop_index('idx_account_status_updated', table_name='account_status')
    op.drop_index('idx_account_ou', table_name='account_status')
    op.drop_index('idx_account_status_enabled', table_name='account_status')
    op.drop_index('idx_account_id_unique', table_name='account_status')

    # Drop the account_status table
    op.drop_table('account_status')

    # Note: We're not removing account_id from resources table on downgrade
    # as it may contain valuable data and doesn't break anything if left

    print("[OK] Removed account_status table")