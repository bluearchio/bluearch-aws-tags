"""Add FinOps tables for CUR integration and cost analysis

Revision ID: 006_add_finops_tables
Revises: 005_add_account_status
Create Date: 2025-12-12 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '006_add_finops_tables'
down_revision = '005_add_account_status'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create FinOps tables for CUR configuration, cost baselines, and anomaly alerts."""

    # Create cur_configurations table
    op.create_table('cur_configurations',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('account_id', sa.String(12), nullable=False),
        sa.Column('report_name', sa.String(255), nullable=False),
        sa.Column('s3_bucket', sa.String(255), nullable=False),
        sa.Column('s3_prefix', sa.String(500), nullable=True),
        sa.Column('athena_database', sa.String(255), nullable=False),
        sa.Column('athena_table', sa.String(255), nullable=False),
        sa.Column('athena_workgroup', sa.String(255), nullable=True, server_default='primary'),
        sa.Column('region', sa.String(50), nullable=False, server_default='us-east-1'),
        sa.Column('status', sa.String(50), nullable=True, server_default='active'),
        sa.Column('last_data_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('setup_stack_id', sa.String(500), nullable=True),
        sa.Column('setup_error', sa.Text(), nullable=True),
        sa.Column('last_validated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('validation_status', sa.String(50), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True, server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.PrimaryKeyConstraint('id')
    )

    # Create indexes for cur_configurations
    op.create_index('idx_cur_account_status', 'cur_configurations', ['account_id', 'status'])
    op.create_index('idx_cur_updated', 'cur_configurations', ['updated_at'])

    # Create cost_baselines table
    op.create_table('cost_baselines',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('account_id', sa.String(12), nullable=False),
        sa.Column('tag_key', sa.String(255), nullable=False),
        sa.Column('tag_value', sa.String(255), nullable=False),
        sa.Column('period_type', sa.String(20), nullable=False),
        sa.Column('period_start', sa.DateTime(timezone=True), nullable=False),
        sa.Column('period_end', sa.DateTime(timezone=True), nullable=False),
        sa.Column('total_cost', sa.String(50), nullable=False),
        sa.Column('blended_cost', sa.String(50), nullable=True),
        sa.Column('unblended_cost', sa.String(50), nullable=True),
        sa.Column('resource_count', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('service_breakdown', sa.JSON(), nullable=True),
        sa.Column('average_cost', sa.String(50), nullable=True),
        sa.Column('std_deviation', sa.String(50), nullable=True),
        sa.Column('min_cost', sa.String(50), nullable=True),
        sa.Column('max_cost', sa.String(50), nullable=True),
        sa.Column('data_source', sa.String(20), nullable=True, server_default='cur'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id')
    )

    # Create indexes for cost_baselines
    op.create_index('idx_baseline_tag_period', 'cost_baselines', ['tag_key', 'tag_value', 'period_start'])
    op.create_index('idx_baseline_account_period', 'cost_baselines', ['account_id', 'period_start'])
    op.create_index('idx_baseline_period_type', 'cost_baselines', ['period_type', 'period_start'])

    # Create cost_anomaly_alerts table
    op.create_table('cost_anomaly_alerts',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('account_id', sa.String(12), nullable=False),
        sa.Column('tag_key', sa.String(255), nullable=False),
        sa.Column('tag_value', sa.String(255), nullable=False),
        sa.Column('detected_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('anomaly_type', sa.String(50), nullable=False),
        sa.Column('severity', sa.String(20), nullable=True, server_default='medium'),
        sa.Column('current_cost', sa.String(50), nullable=False),
        sa.Column('baseline_cost', sa.String(50), nullable=False),
        sa.Column('absolute_change', sa.String(50), nullable=False),
        sa.Column('percent_change', sa.String(50), nullable=False),
        sa.Column('threshold_type', sa.String(50), nullable=True),
        sa.Column('period', sa.String(50), nullable=True),
        sa.Column('period_start', sa.DateTime(timezone=True), nullable=True),
        sa.Column('period_end', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sa.String(20), nullable=True, server_default='new'),
        sa.Column('acknowledged_by', sa.String(256), nullable=True),
        sa.Column('acknowledged_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('resolution_notes', sa.Text(), nullable=True),
        sa.Column('details', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True, server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.PrimaryKeyConstraint('id')
    )

    # Create indexes for cost_anomaly_alerts
    op.create_index('idx_anomaly_status_severity', 'cost_anomaly_alerts', ['status', 'severity'])
    op.create_index('idx_anomaly_tag_detected', 'cost_anomaly_alerts', ['tag_key', 'tag_value', 'detected_at'])
    op.create_index('idx_anomaly_account_detected', 'cost_anomaly_alerts', ['account_id', 'detected_at'])
    op.create_index('idx_anomaly_type_status', 'cost_anomaly_alerts', ['anomaly_type', 'status'])

    print("[OK] Created cur_configurations table for CUR access configuration")
    print("[OK] Created cost_baselines table for anomaly detection baselines")
    print("[OK] Created cost_anomaly_alerts table for cost anomaly tracking")
    print("[OK] Added indexes for optimal query performance")


def downgrade() -> None:
    """Remove FinOps tables."""

    # Drop cost_anomaly_alerts indexes and table
    op.drop_index('idx_anomaly_type_status', table_name='cost_anomaly_alerts')
    op.drop_index('idx_anomaly_account_detected', table_name='cost_anomaly_alerts')
    op.drop_index('idx_anomaly_tag_detected', table_name='cost_anomaly_alerts')
    op.drop_index('idx_anomaly_status_severity', table_name='cost_anomaly_alerts')
    op.drop_table('cost_anomaly_alerts')

    # Drop cost_baselines indexes and table
    op.drop_index('idx_baseline_period_type', table_name='cost_baselines')
    op.drop_index('idx_baseline_account_period', table_name='cost_baselines')
    op.drop_index('idx_baseline_tag_period', table_name='cost_baselines')
    op.drop_table('cost_baselines')

    # Drop cur_configurations indexes and table
    op.drop_index('idx_cur_updated', table_name='cur_configurations')
    op.drop_index('idx_cur_account_status', table_name='cur_configurations')
    op.drop_table('cur_configurations')

    print("[OK] Removed FinOps tables")
