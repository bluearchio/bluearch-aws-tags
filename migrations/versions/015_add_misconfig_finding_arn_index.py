"""Add index on misconfig_findings.resource_arn for graph overlay queries.

Revision ID: 015_add_misconfig_finding_arn_index
Revises: 014_add_resource_relationships
Create Date: 2026-03-17 00:00:00.000000
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = '015_add_misconfig_finding_arn_index'
down_revision = '014_add_resource_relationships'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add index on misconfig_findings.resource_arn."""
    op.create_index(
        'idx_misconfig_finding_resource_arn',
        'misconfig_findings',
        ['resource_arn'],
    )


def downgrade() -> None:
    """Drop index on misconfig_findings.resource_arn."""
    op.drop_index('idx_misconfig_finding_resource_arn', table_name='misconfig_findings')
