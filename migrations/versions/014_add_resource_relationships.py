"""Add resource_relationships table for graph visualization

Revision ID: 014_add_resource_relationships
Revises: 013_add_account_context_and_permissions
Create Date: 2026-03-11 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '014_add_resource_relationships'
down_revision = '013_add_account_context_and_permissions'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create resource_relationships table."""

    op.create_table(
        'resource_relationships',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('source_arn', sa.String(1024), nullable=False),
        sa.Column('target_arn', sa.String(1024), nullable=False),
        sa.Column('relationship_type', sa.String(50), nullable=False),
        sa.Column('source_type', sa.String(100), nullable=False),
        sa.Column('target_type', sa.String(100), nullable=False),
        sa.Column('region', sa.String(50), nullable=False),
        sa.Column('account_id', sa.String(12), nullable=False),
        sa.Column('metadata', sa.JSON(), nullable=True),
        sa.Column('discovered_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('last_seen_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint('source_arn', 'target_arn', 'relationship_type', name='uq_relationship_edge'),
    )

    # Single-column indexes
    op.create_index('ix_resource_relationships_source_arn', 'resource_relationships', ['source_arn'])
    op.create_index('ix_resource_relationships_target_arn', 'resource_relationships', ['target_arn'])
    op.create_index('ix_resource_relationships_relationship_type', 'resource_relationships', ['relationship_type'])
    op.create_index('ix_resource_relationships_region', 'resource_relationships', ['region'])
    op.create_index('ix_resource_relationships_account_id', 'resource_relationships', ['account_id'])

    # Composite indexes
    op.create_index('idx_rel_source_type', 'resource_relationships', ['source_arn', 'relationship_type'])
    op.create_index('idx_rel_target_type', 'resource_relationships', ['target_arn', 'relationship_type'])
    op.create_index('idx_rel_account_region', 'resource_relationships', ['account_id', 'region'])


def downgrade() -> None:
    """Drop resource_relationships table and its indexes."""

    op.drop_index('idx_rel_account_region', table_name='resource_relationships')
    op.drop_index('idx_rel_target_type', table_name='resource_relationships')
    op.drop_index('idx_rel_source_type', table_name='resource_relationships')
    op.drop_index('ix_resource_relationships_account_id', table_name='resource_relationships')
    op.drop_index('ix_resource_relationships_region', table_name='resource_relationships')
    op.drop_index('ix_resource_relationships_relationship_type', table_name='resource_relationships')
    op.drop_index('ix_resource_relationships_target_arn', table_name='resource_relationships')
    op.drop_index('ix_resource_relationships_source_arn', table_name='resource_relationships')
    op.drop_table('resource_relationships')
