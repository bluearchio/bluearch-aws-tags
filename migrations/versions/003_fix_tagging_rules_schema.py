"""Fix tagging_rules schema to match models.py.

Revision ID: 003_fix_tagging_rules
Revises: 002_duration_to_ms
Create Date: 2025-01-05

This migration updates the tagging_rules table to match the current model definition:
- Renames rule_name to name
- Removes obsolete columns (tag_key, tag_value, condition_type, condition_value, created_by, last_applied_at, apply_count)
- Adds new columns (conditions, tag_templates)
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import JSON, String, DateTime, Boolean, Integer, Text


# Revision identifiers
revision = '003_fix_tagging_rules'
down_revision = '002_duration_to_ms'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Fix tagging_rules schema to match models.py."""

    # SQLite doesn't support ALTER COLUMN, so we need to recreate the table

    # Create new table with correct schema matching models.py
    op.create_table('tagging_rules_new',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('name', sa.String(255), nullable=False, unique=True),  # Changed from rule_name
        sa.Column('description', sa.Text),
        sa.Column('resource_types', JSON, nullable=False),
        sa.Column('conditions', JSON, nullable=False),  # New column
        sa.Column('tag_templates', JSON, nullable=False),  # New column
        sa.Column('priority', sa.Integer, default=100),
        sa.Column('enabled', sa.Boolean, default=True, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True))
    )

    # Copy data from old table with schema transformation
    # For existing rows, we'll create default JSON structures for conditions and tag_templates
    op.execute("""
        INSERT INTO tagging_rules_new (
            id, name, description, resource_types, conditions, tag_templates,
            priority, enabled, created_at, updated_at
        )
        SELECT
            id,
            rule_name as name,  -- Rename column
            description,
            resource_types,
            CASE
                WHEN condition_type IS NOT NULL AND condition_value IS NOT NULL
                THEN json_object('type', condition_type, 'value', condition_value)
                ELSE json_object()
            END as conditions,  -- Transform old condition columns to JSON
            CASE
                WHEN tag_key IS NOT NULL AND tag_value IS NOT NULL
                THEN json_array(json_object('key', tag_key, 'value', tag_value))
                ELSE json_array()
            END as tag_templates,  -- Transform old tag columns to JSON
            priority,
            enabled,
            created_at,
            updated_at
        FROM tagging_rules
    """)

    # Drop old table
    op.drop_table('tagging_rules')

    # Rename new table to original name
    op.rename_table('tagging_rules_new', 'tagging_rules')

    # Recreate indexes to match models.py
    op.create_index('idx_tagging_rules_name', 'tagging_rules', ['name'])
    op.create_index('idx_rule_enabled', 'tagging_rules', ['enabled'])
    op.create_index('idx_rule_priority', 'tagging_rules', ['priority'])
    op.create_index('idx_enabled_priority', 'tagging_rules', ['enabled', 'priority'])


def downgrade() -> None:
    """Revert tagging_rules schema back to old format."""

    # Create table with old schema
    op.create_table('tagging_rules_new',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('rule_name', sa.String(256), nullable=False, unique=True),
        sa.Column('description', sa.Text),
        sa.Column('enabled', sa.Boolean, default=True),
        sa.Column('priority', sa.Integer, default=0),
        sa.Column('resource_types', JSON, nullable=False),
        sa.Column('tag_key', sa.String(256), nullable=False),
        sa.Column('tag_value', sa.String(256), nullable=False),
        sa.Column('condition_type', sa.String(50)),
        sa.Column('condition_value', sa.Text),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True)),
        sa.Column('created_by', sa.String(256)),
        sa.Column('last_applied_at', sa.DateTime(timezone=True)),
        sa.Column('apply_count', sa.Integer, default=0)
    )

    # Copy data back with reverse transformation
    op.execute("""
        INSERT INTO tagging_rules_new (
            id, rule_name, description, resource_types, tag_key, tag_value,
            condition_type, condition_value, priority, enabled, created_at, updated_at,
            created_by, last_applied_at, apply_count
        )
        SELECT
            id,
            name as rule_name,
            description,
            resource_types,
            COALESCE(
                json_extract(
                    json_extract(tag_templates, '$[0]'),
                    '$.key'
                ),
                'DefaultKey'
            ) as tag_key,
            COALESCE(
                json_extract(
                    json_extract(tag_templates, '$[0]'),
                    '$.value'
                ),
                'DefaultValue'
            ) as tag_value,
            json_extract(conditions, '$.type') as condition_type,
            json_extract(conditions, '$.value') as condition_value,
            priority,
            enabled,
            created_at,
            updated_at,
            NULL as created_by,
            NULL as last_applied_at,
            0 as apply_count
        FROM tagging_rules
    """)

    # Drop new table
    op.drop_table('tagging_rules')

    # Rename back to original name
    op.rename_table('tagging_rules_new', 'tagging_rules')

    # Recreate old indexes
    op.create_index('idx_rule_enabled', 'tagging_rules', ['enabled'])
    op.create_index('idx_rule_priority', 'tagging_rules', ['priority'])
