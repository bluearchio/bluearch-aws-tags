"""Add execution_id column to tagging_audit_log

Revision ID: 004
Revises: 003
Create Date: 2025-01-06 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '004'
down_revision = '003'
branch_labels = None
depends_on = None


def upgrade():
    """Add execution_id column to tagging_audit_log table."""
    # Check if column already exists (for idempotency)
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [col['name'] for col in inspector.get_columns('tagging_audit_log')]

    if 'execution_id' not in columns:
        # Add execution_id column
        op.add_column('tagging_audit_log',
            sa.Column('execution_id', sa.Integer(), nullable=True)
        )

        # Create index on execution_id
        op.create_index(
            'idx_audit_execution_id',
            'tagging_audit_log',
            ['execution_id'],
            unique=False
        )


def downgrade():
    """Remove execution_id column from tagging_audit_log table."""
    # Drop index first
    op.drop_index('idx_audit_execution_id', table_name='tagging_audit_log')

    # Drop column
    op.drop_column('tagging_audit_log', 'execution_id')
