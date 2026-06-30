"""Add evaluation_tier and evaluation_details to misconfig_findings

Revision ID: 011_add_evaluation_tier
Revises: 010_add_misconfig_tables
Create Date: 2026-02-12 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '011_add_evaluation_tier'
down_revision = '010_add_misconfig_tables'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add evaluation tier columns to misconfig_findings."""
    op.add_column(
        'misconfig_findings',
        sa.Column('evaluation_tier', sa.String(20), nullable=False, server_default='advisory')
    )
    op.add_column(
        'misconfig_findings',
        sa.Column('evaluation_details', sa.Text(), nullable=True)
    )
    op.create_index(
        'idx_misconfig_finding_tier',
        'misconfig_findings',
        ['evaluation_tier']
    )


def downgrade() -> None:
    """Remove evaluation tier columns from misconfig_findings."""
    op.drop_index('idx_misconfig_finding_tier', table_name='misconfig_findings')
    op.drop_column('misconfig_findings', 'evaluation_details')
    op.drop_column('misconfig_findings', 'evaluation_tier')
