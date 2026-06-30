"""Add policy source and compliance tracking fields to resources

Revision ID: 008_add_policy_source_tracking
Revises: 007_add_lifecycle_notifications
Create Date: 2026-01-13 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '008_add_policy_source_tracking'
down_revision = '007_add_lifecycle_notifications'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add policy source tracking and compliance fields to resources table."""

    # Policy source tracking columns (hybrid policy system)
    op.add_column('resources', sa.Column('policy_source', sa.String(50), nullable=True))
    op.add_column('resources', sa.Column('org_policy_id', sa.String(100), nullable=True))
    op.add_column('resources', sa.Column('org_policy_name', sa.String(255), nullable=True))

    # Compliance tracking columns (for AWS Org Tag Policies)
    op.add_column('resources', sa.Column('compliance_status', sa.String(50), nullable=True))
    op.add_column('resources', sa.Column('missing_tags', sa.JSON(), nullable=True))
    op.add_column('resources', sa.Column('invalid_tags', sa.JSON(), nullable=True))
    op.add_column('resources', sa.Column('last_compliance_check', sa.DateTime(timezone=True), nullable=True))

    # Create indexes for new columns
    op.create_index('idx_policy_source', 'resources', ['policy_source'])
    op.create_index('idx_compliance_status', 'resources', ['compliance_status'])


def downgrade() -> None:
    """Remove policy source tracking and compliance fields from resources table."""

    # Drop indexes
    op.drop_index('idx_policy_source', table_name='resources')
    op.drop_index('idx_compliance_status', table_name='resources')

    # Drop columns
    op.drop_column('resources', 'last_compliance_check')
    op.drop_column('resources', 'invalid_tags')
    op.drop_column('resources', 'missing_tags')
    op.drop_column('resources', 'compliance_status')
    op.drop_column('resources', 'org_policy_name')
    op.drop_column('resources', 'org_policy_id')
    op.drop_column('resources', 'policy_source')
