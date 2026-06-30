"""Add misconfiguration policy and finding tables

Revision ID: 010_add_misconfig_tables
Revises: 009_add_assume_role_configuration
Create Date: 2026-02-12 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '010_add_misconfig_tables'
down_revision = '009_add_assume_role_configuration'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create misconfig_policies and misconfig_findings tables."""

    # -- misconfig_policies --
    op.create_table(
        'misconfig_policies',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('resource_types', sa.JSON(), nullable=False),
        sa.Column('misconfig_ids', sa.JSON(), nullable=False),
        sa.Column('risk_types', sa.JSON(), nullable=True),
        sa.Column('min_risk_value', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('exclude_patterns', sa.JSON(), nullable=True),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default='1'),
        sa.Column('priority', sa.Integer(), nullable=False, server_default='100'),
        sa.Column('resources_flagged', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('last_scanned_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name')
    )

    op.create_index('idx_misconfig_policy_name', 'misconfig_policies', ['name'])
    op.create_index('idx_misconfig_policy_enabled', 'misconfig_policies', ['enabled'])
    op.create_index('idx_misconfig_policy_enabled_priority', 'misconfig_policies', ['enabled', 'priority'])
    op.create_index('idx_misconfig_policy_updated', 'misconfig_policies', ['updated_at'])

    # -- misconfig_findings --
    op.create_table(
        'misconfig_findings',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('policy_id', sa.String(36), sa.ForeignKey('misconfig_policies.id'), nullable=False),
        sa.Column('resource_id', sa.String(36), sa.ForeignKey('resources.id'), nullable=True),
        sa.Column('misconfig_id', sa.String(36), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='open'),
        sa.Column('risk_type', sa.String(50), nullable=False),
        sa.Column('risk_value', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('scenario', sa.Text(), nullable=True),
        sa.Column('recommendation', sa.Text(), nullable=True),
        sa.Column('resource_arn', sa.String(1024), nullable=True),
        sa.Column('resource_type', sa.String(100), nullable=True),
        sa.Column('service_name', sa.String(50), nullable=True),
        sa.Column('detected_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('acknowledged_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('acknowledged_by', sa.String(255), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )

    op.create_index('idx_misconfig_finding_policy_id', 'misconfig_findings', ['policy_id'])
    op.create_index('idx_misconfig_finding_resource_id', 'misconfig_findings', ['resource_id'])
    op.create_index('idx_misconfig_finding_misconfig_id', 'misconfig_findings', ['misconfig_id'])
    op.create_index('idx_misconfig_finding_status', 'misconfig_findings', ['status'])
    op.create_index('idx_misconfig_finding_policy_status', 'misconfig_findings', ['policy_id', 'status'])
    op.create_index('idx_misconfig_finding_risk', 'misconfig_findings', ['risk_type', 'risk_value'])
    op.create_index('idx_misconfig_finding_resource', 'misconfig_findings', ['resource_id', 'status'])
    op.create_index('idx_misconfig_finding_detected', 'misconfig_findings', ['detected_at'])


def downgrade() -> None:
    """Drop misconfig_findings and misconfig_policies tables."""

    # Drop finding indexes
    op.drop_index('idx_misconfig_finding_detected', table_name='misconfig_findings')
    op.drop_index('idx_misconfig_finding_resource', table_name='misconfig_findings')
    op.drop_index('idx_misconfig_finding_risk', table_name='misconfig_findings')
    op.drop_index('idx_misconfig_finding_policy_status', table_name='misconfig_findings')
    op.drop_index('idx_misconfig_finding_status', table_name='misconfig_findings')
    op.drop_index('idx_misconfig_finding_misconfig_id', table_name='misconfig_findings')
    op.drop_index('idx_misconfig_finding_resource_id', table_name='misconfig_findings')
    op.drop_index('idx_misconfig_finding_policy_id', table_name='misconfig_findings')

    op.drop_table('misconfig_findings')

    # Drop policy indexes
    op.drop_index('idx_misconfig_policy_updated', table_name='misconfig_policies')
    op.drop_index('idx_misconfig_policy_enabled_priority', table_name='misconfig_policies')
    op.drop_index('idx_misconfig_policy_enabled', table_name='misconfig_policies')
    op.drop_index('idx_misconfig_policy_name', table_name='misconfig_policies')

    op.drop_table('misconfig_policies')
