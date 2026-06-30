"""SQLAlchemy models for Tag Manager CLI database."""

import uuid
from datetime import datetime
from typing import Dict, Any, Optional, List
from sqlalchemy import (
    Column, String, DateTime, Boolean, Integer, Text,
    JSON, ForeignKey, Index, UniqueConstraint, create_engine, MetaData, text, or_, and_
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker
from sqlalchemy.sql import func

# Database-agnostic UUID column type
def UUID_Column(primary_key=False, nullable=True, **kwargs):
    """Create a database-agnostic UUID column.

    For PostgreSQL, this would ideally use UUID(as_uuid=True).
    For SQLite, we use String(36) to store UUID as string.
    """
    if primary_key:
        return Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()), **kwargs)
    else:
        return Column(String(36), nullable=nullable, default=lambda: str(uuid.uuid4()) if not nullable else None, **kwargs)

# Database-agnostic Array column type
def Array_Column(item_type, **kwargs):
    """Create a database-agnostic array column.

    For PostgreSQL, this would use ARRAY.
    For SQLite, we use JSON to store arrays.
    """
    return Column(JSON, **kwargs)

Base = declarative_base()
metadata = MetaData()


class Resource(Base):
    """AWS resources discovered and tracked for tagging."""
    
    __tablename__ = 'resources'
    
    # Primary key
    id = UUID_Column(primary_key=True)
    
    # Resource identification
    resource_arn = Column(String(1024), nullable=False, unique=True, index=True)
    resource_type = Column(String(100), nullable=False, index=True)
    service_name = Column(String(50), nullable=False, index=True)
    region = Column(String(50), nullable=False, index=True)
    account_id = Column(String(12), nullable=False, index=True)
    resource_id = Column(String(256), nullable=False)
    
    # Creator information (from CloudTrail)
    created_by = Column(String(256), index=True)
    created_at = Column(DateTime(timezone=True))
    
    # Discovery metadata
    discovered_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
    last_scanned_at = Column(DateTime(timezone=True), default=func.now())
    
    # Current tags and metadata
    current_tags = Column(JSON)
    metadata_json = Column('metadata', JSON)
    
    # Lifecycle management
    expires_at = Column(DateTime(timezone=True), index=True)  # TTL expiration date
    lifecycle_state = Column(String(50), default='active', index=True)  # active, warned, marked_for_deletion, deleted
    delete_after = Column(DateTime(timezone=True), index=True)  # Scheduled deletion date
    protected = Column(Boolean, default=False, index=True)  # Protection from automated deletion
    
    # Lifecycle tracking
    warned_at = Column(DateTime(timezone=True))  # When first warning was issued
    warning_count = Column(Integer, default=0)  # Number of warnings issued
    lifecycle_policy_id = Column(String(36), ForeignKey('resource_lifecycle_policies.id'), nullable=True)

    # TTL source tracking
    ttl_source = Column(String(50))  # 'tag', 'policy', 'manual' - where TTL came from
    ttl_tag_key = Column(String(256))  # Tag key used if ttl_source='tag'
    owner_email = Column(String(256), index=True)  # Resource owner for notifications
    grace_period_ends_at = Column(DateTime(timezone=True), index=True)  # When grace period expires

    # Policy source tracking (hybrid policy system)
    policy_source = Column(String(50), index=True)  # 'aws_org' or 'local'
    org_policy_id = Column(String(100))  # AWS Org policy ID (if policy_source='aws_org')
    org_policy_name = Column(String(255))  # AWS Org policy name (if policy_source='aws_org')

    # Compliance tracking (for AWS Org Tag Policies)
    compliance_status = Column(String(50), index=True)  # 'compliant', 'noncompliant', 'unknown'
    missing_tags = Column(JSON)  # List of required tags that are missing
    invalid_tags = Column(JSON)  # Tags with invalid values
    last_compliance_check = Column(DateTime(timezone=True))  # When compliance was last checked

    # Relationships
    audit_logs = relationship("TaggingAuditLog", back_populates="resource", cascade="all, delete-orphan")
    lifecycle_policy = relationship("ResourceLifecyclePolicy", back_populates="resources")
    
    # Indexes for performance
    __table_args__ = (
        Index('idx_resource_type_region', 'resource_type', 'region'),
        Index('idx_service_created_at', 'service_name', 'created_at'),
        Index('idx_created_by', 'created_by'),
        Index('idx_last_scanned', 'last_scanned_at'),
        Index('idx_lifecycle_state_expires', 'lifecycle_state', 'expires_at'),
        Index('idx_expires_protected', 'expires_at', 'protected'),
        Index('idx_delete_after_state', 'delete_after', 'lifecycle_state'),
        Index('idx_lifecycle_policy', 'lifecycle_policy_id'),
    )
    
    def __repr__(self):
        return f"<Resource(arn='{self.resource_arn}', type='{self.resource_type}')>"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert resource to dictionary."""
        return {
            'id': str(self.id),
            'resource_arn': self.resource_arn,
            'resource_type': self.resource_type,
            'service_name': self.service_name,
            'region': self.region,
            'account_id': self.account_id,
            'resource_id': self.resource_id,
            'created_by': self.created_by,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'discovered_at': self.discovered_at.isoformat() if self.discovered_at else None,
            'last_scanned_at': self.last_scanned_at.isoformat() if self.last_scanned_at else None,
            'current_tags': self.current_tags,
            'metadata': self.metadata_json,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'lifecycle_state': self.lifecycle_state,
            'delete_after': self.delete_after.isoformat() if self.delete_after else None,
            'protected': self.protected,
            'warned_at': self.warned_at.isoformat() if self.warned_at else None,
            'warning_count': self.warning_count,
            'lifecycle_policy_id': str(self.lifecycle_policy_id) if self.lifecycle_policy_id else None,
            'ttl_source': self.ttl_source,
            'ttl_tag_key': self.ttl_tag_key,
            'owner_email': self.owner_email,
            'grace_period_ends_at': self.grace_period_ends_at.isoformat() if self.grace_period_ends_at else None,
            'policy_source': self.policy_source,
            'org_policy_id': self.org_policy_id,
            'org_policy_name': self.org_policy_name,
            'compliance_status': self.compliance_status,
            'missing_tags': self.missing_tags,
            'invalid_tags': self.invalid_tags,
            'last_compliance_check': self.last_compliance_check.isoformat() if self.last_compliance_check else None
        }


class TaggingRule(Base):
    """Rules for automated resource tagging."""
    
    __tablename__ = 'tagging_rules'
    
    # Primary key
    id = UUID_Column(primary_key=True)
    
    # Rule identification
    name = Column(String(255), nullable=False, unique=True, index=True)
    description = Column(Text)
    
    # Rule configuration
    resource_types = Array_Column(String(100), nullable=False)
    conditions = Column(JSON, nullable=False)
    tag_templates = Column(JSON, nullable=False)
    
    # Rule metadata
    priority = Column(Integer, default=100, index=True)
    enabled = Column(Boolean, default=True, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now())
    
    # Relationships
    audit_logs = relationship("TaggingAuditLog", back_populates="rule")
    
    # Indexes
    __table_args__ = (
        Index('idx_enabled_priority', 'enabled', 'priority'),
        Index('idx_resource_types', 'resource_types'),
    )
    
    def __repr__(self):
        return f"<TaggingRule(name='{self.name}', enabled={self.enabled})>"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert rule to dictionary."""
        return {
            'id': str(self.id),
            'name': self.name,
            'description': self.description,
            'resource_types': self.resource_types,
            'conditions': self.conditions,
            'tag_templates': self.tag_templates,
            'priority': self.priority,
            'enabled': self.enabled,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


class TaggingExecution(Base):
    """Groups related tagging operations for tracking and rollback."""
    
    __tablename__ = 'tagging_executions'
    
    # Primary key
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Execution identification
    execution_type = Column(String(50), nullable=False, index=True)  # manual, automated, bulk, setup, rollback
    description = Column(Text)
    
    # User/principal information
    initiated_by = Column(String(256), nullable=False)
    initiated_via = Column(String(50))  # cli, api, scheduled
    
    # Timing
    started_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
    completed_at = Column(DateTime(timezone=True))
    
    # Status tracking
    status = Column(String(50), nullable=False, default='pending', index=True)  # pending, in_progress, completed, failed, rolled_back, partially_rolled_back
    total_resources = Column(Integer, default=0)
    successful_operations = Column(Integer, default=0)
    failed_operations = Column(Integer, default=0)
    
    # Rollback information
    rollback_enabled = Column(Boolean, default=True, nullable=False)
    rollback_window_hours = Column(Integer, default=24)  # Hours after which rollback is not allowed
    parent_execution_id = Column(Integer, ForeignKey('tagging_executions.id'), nullable=True)  # If this is a rollback, reference to original
    rolled_back_at = Column(DateTime(timezone=True))
    rolled_back_by = Column(String(256))
    
    # Metadata
    metadata_json = Column('metadata', JSON)  # Store additional context (e.g., filter criteria, rule names, etc.)
    
    # Relationships
    audit_logs = relationship("TaggingAuditLog", back_populates="execution", cascade="all, delete-orphan")
    parent_execution = relationship("TaggingExecution", remote_side=[id], backref="rollback_executions")
    
    # Indexes
    __table_args__ = (
        Index('idx_execution_type_status', 'execution_type', 'status'),
        Index('idx_started_at', 'started_at'),
        Index('idx_initiated_by', 'initiated_by'),
        Index('idx_parent_execution', 'parent_execution_id'),
    )
    
    def __repr__(self):
        return f"<TaggingExecution(id='{self.id}', type='{self.execution_type}', status='{self.status}')>"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert execution to dictionary."""
        return {
            'id': self.id,
            'execution_type': self.execution_type,
            'description': self.description,
            'initiated_by': self.initiated_by,
            'initiated_via': self.initiated_via,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'status': self.status,
            'total_resources': self.total_resources,
            'successful_operations': self.successful_operations,
            'failed_operations': self.failed_operations,
            'rollback_enabled': self.rollback_enabled,
            'rollback_window_hours': self.rollback_window_hours,
            'parent_execution_id': self.parent_execution_id,
            'rolled_back_at': self.rolled_back_at.isoformat() if self.rolled_back_at else None,
            'rolled_back_by': self.rolled_back_by,
            'metadata': self.metadata_json
        }
    
    def can_rollback(self) -> tuple[bool, str]:
        """Check if this execution can be rolled back."""
        if not self.rollback_enabled:
            return False, "Rollback is disabled for this execution"
        
        if self.status == 'rolled_back':
            return False, "Execution has already been rolled back"
        
        if self.status == 'partially_rolled_back':
            return False, "Execution has already been partially rolled back"
        
        if self.status not in ['completed', 'failed']:
            return False, f"Cannot rollback execution in status: {self.status}"
        
        if self.rollback_window_hours and self.completed_at:
            from datetime import datetime, timedelta
            rollback_deadline = self.completed_at + timedelta(hours=self.rollback_window_hours)
            if datetime.now(self.completed_at.tzinfo) > rollback_deadline:
                return False, f"Rollback window of {self.rollback_window_hours} hours has expired"
        
        return True, "Execution can be rolled back"


class TaggingAuditLog(Base):
    """Audit log for all tagging operations."""
    
    __tablename__ = 'tagging_audit_log'
    
    # Primary key
    id = UUID_Column(primary_key=True)
    
    # Resource reference
    resource_arn = Column(String(1024), nullable=False, index=True)
    resource_id = Column(String(36), ForeignKey('resources.id'), nullable=True)
    
    # Execution tracking
    execution_id = Column(Integer, ForeignKey('tagging_executions.id'), nullable=True, index=True)
    
    # Operation details
    operation = Column(String(50), nullable=False, index=True)  # TAG_ADDED, TAG_UPDATED, TAG_REMOVED, TAG_ROLLBACK
    rule_id = Column(String(36), ForeignKey('tagging_rules.id'), nullable=True)
    is_rollback = Column(Boolean, default=False, nullable=False)
    
    # Tag changes
    old_tags = Column(JSON)
    new_tags = Column(JSON)
    
    # CloudTrail information
    principal_info = Column(JSON)
    cloudtrail_event_id = Column(String(100), index=True)
    
    # Execution details
    success = Column(Boolean, nullable=False, index=True)
    error_message = Column(Text)
    executed_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
    
    # Relationships
    resource = relationship("Resource", back_populates="audit_logs")
    rule = relationship("TaggingRule", back_populates="audit_logs")
    execution = relationship("TaggingExecution", back_populates="audit_logs")
    
    # Indexes for performance
    __table_args__ = (
        Index('idx_resource_arn_executed_at', 'resource_arn', 'executed_at'),
        Index('idx_rule_executed_at', 'rule_id', 'executed_at'),
        Index('idx_operation_success', 'operation', 'success'),
        Index('idx_cloudtrail_event', 'cloudtrail_event_id'),
        Index('idx_execution_id', 'execution_id'),
        Index('idx_is_rollback', 'is_rollback'),
    )
    
    def __repr__(self):
        return f"<TaggingAuditLog(resource_arn='{self.resource_arn}', operation='{self.operation}', success={self.success})>"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert audit log to dictionary."""
        return {
            'id': str(self.id),
            'resource_arn': self.resource_arn,
            'resource_id': str(self.resource_id) if self.resource_id else None,
            'execution_id': self.execution_id,
            'operation': self.operation,
            'rule_id': str(self.rule_id) if self.rule_id else None,
            'is_rollback': self.is_rollback,
            'old_tags': self.old_tags,
            'new_tags': self.new_tags,
            'principal_info': self.principal_info,
            'cloudtrail_event_id': self.cloudtrail_event_id,
            'success': self.success,
            'error_message': self.error_message,
            'executed_at': self.executed_at.isoformat() if self.executed_at else None
        }


class ResourceMapping(Base):
    """CloudTrail event to resource type mappings."""
    
    __tablename__ = 'resource_mappings'
    
    # Primary key
    id = UUID_Column(primary_key=True)
    
    # Service and resource type
    service_name = Column(String(50), nullable=False, index=True)
    resource_type = Column(String(100), nullable=False, index=True)
    
    # CloudTrail event mapping
    event_name = Column(String(100), nullable=False, index=True)
    event_source = Column(String(100), nullable=False, index=True)
    
    # Resource extraction configuration
    resource_arn_template = Column(String(500))
    resource_id_path = Column(String(200))  # JSONPath to extract resource ID from event
    
    # Configuration metadata
    enabled = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now())
    
    # Indexes
    __table_args__ = (
        Index('idx_event_source_name', 'event_source', 'event_name'),
        Index('idx_service_resource_type', 'service_name', 'resource_type'),
        Index('idx_enabled_service', 'enabled', 'service_name'),
    )
    
    def __repr__(self):
        return f"<ResourceMapping(service='{self.service_name}', event='{self.event_name}')>"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert mapping to dictionary."""
        return {
            'id': str(self.id),
            'service_name': self.service_name,
            'resource_type': self.resource_type,
            'event_name': self.event_name,
            'event_source': self.event_source,
            'resource_arn_template': self.resource_arn_template,
            'resource_id_path': self.resource_id_path,
            'enabled': self.enabled,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


class CacheMetadata(Base):
    """Track cache freshness and invalidation."""
    
    __tablename__ = 'cache_metadata'
    
    # Primary key
    id = UUID_Column(primary_key=True)
    
    # Cache identification
    cache_key = Column(String(500), nullable=False, unique=True, index=True)
    cache_type = Column(String(50), nullable=False, index=True)  # aws_api, cloudtrail, resource_discovery
    
    # Cache metadata
    service_name = Column(String(50), index=True)
    region = Column(String(50), index=True)
    resource_type = Column(String(100), index=True)
    
    # Timing information
    created_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    last_accessed_at = Column(DateTime(timezone=True), default=func.now())
    
    # Cache statistics
    hit_count = Column(Integer, default=0)
    size_bytes = Column(Integer)
    
    # Indexes
    __table_args__ = (
        Index('idx_cache_type_expires', 'cache_type', 'expires_at'),
        Index('idx_service_region_type', 'service_name', 'region', 'resource_type'),
        Index('idx_expires_accessed', 'expires_at', 'last_accessed_at'),
    )
    
    def __repr__(self):
        return f"<CacheMetadata(key='{self.cache_key}', type='{self.cache_type}')>"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert cache metadata to dictionary."""
        return {
            'id': str(self.id),
            'cache_key': self.cache_key,
            'cache_type': self.cache_type,
            'service_name': self.service_name,
            'region': self.region,
            'resource_type': self.resource_type,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'last_accessed_at': self.last_accessed_at.isoformat() if self.last_accessed_at else None,
            'hit_count': self.hit_count,
            'size_bytes': self.size_bytes
        }


class WorkerStatus(Base):
    """Track worker process status and health."""
    
    __tablename__ = 'worker_status'
    
    # Primary key
    id = UUID_Column(primary_key=True)
    
    # Worker identification
    worker_id = Column(String(100), nullable=False, unique=True, index=True)
    worker_type = Column(String(50), nullable=False, index=True)  # discovery, tagging, scheduler
    hostname = Column(String(100), nullable=False)
    
    # Status information
    status = Column(String(20), nullable=False, index=True)  # active, idle, busy, stopped, error
    current_task = Column(String(200))
    last_heartbeat = Column(DateTime(timezone=True), nullable=False, default=func.now())
    
    # Performance metrics
    tasks_processed = Column(Integer, default=0)
    tasks_failed = Column(Integer, default=0)
    avg_task_duration = Column(Integer)  # seconds
    
    # Process information
    started_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
    process_id = Column(Integer)
    memory_usage_mb = Column(Integer)
    cpu_usage_percent = Column(Integer)
    
    # Indexes
    __table_args__ = (
        Index('idx_worker_type_status', 'worker_type', 'status'),
        Index('idx_last_heartbeat', 'last_heartbeat'),
        Index('idx_status_heartbeat', 'status', 'last_heartbeat'),
    )
    
    def __repr__(self):
        return f"<WorkerStatus(worker_id='{self.worker_id}', status='{self.status}')>"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert worker status to dictionary."""
        return {
            'id': str(self.id),
            'worker_id': self.worker_id,
            'worker_type': self.worker_type,
            'hostname': self.hostname,
            'status': self.status,
            'current_task': self.current_task,
            'last_heartbeat': self.last_heartbeat.isoformat() if self.last_heartbeat else None,
            'tasks_processed': self.tasks_processed,
            'tasks_failed': self.tasks_failed,
            'avg_task_duration': self.avg_task_duration,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'process_id': self.process_id,
            'memory_usage_mb': self.memory_usage_mb,
            'cpu_usage_percent': self.cpu_usage_percent
        }


class ResourceLifecyclePolicy(Base):
    """Policies for automated resource lifecycle management and cleanup."""
    
    __tablename__ = 'resource_lifecycle_policies'
    
    # Primary key
    id = UUID_Column(primary_key=True)
    
    # Policy identification
    name = Column(String(255), nullable=False, unique=True, index=True)
    description = Column(Text)
    
    # Policy configuration
    resource_types = Array_Column(String(100), nullable=False)  # Resource types this policy applies to
    conditions = Column(JSON, nullable=False)  # Conditions for policy application
    
    # Lifecycle settings
    ttl_days = Column(Integer, nullable=False)  # Time to live in days
    warning_days_before = Column(Integer, default=7)  # Days before expiration to warn
    actions = Column(JSON, nullable=False)  # Actions to take (warn, delete, etc.)
    
    # Policy metadata
    priority = Column(Integer, default=100, index=True)  # Lower number = higher priority
    enabled = Column(Boolean, default=True, nullable=False, index=True)
    
    # Automatic application settings
    auto_apply = Column(Boolean, default=True)  # Automatically apply to matching resources
    require_confirmation = Column(Boolean, default=True)  # Require confirmation before deletion
    
    # Safety settings
    max_deletions_per_day = Column(Integer, default=50)  # Maximum resources to delete per day
    exclude_patterns = Column(JSON)  # Resource name/tag patterns to exclude

    # Enhanced lifecycle settings
    warning_schedule = Column(JSON, default=[7, 3, 1])  # Days before expiry to send warnings
    grace_period_days = Column(Integer, default=7)  # Days after expiry before deletion
    auto_delete_enabled = Column(Boolean, default=False)  # Enable automatic deletion
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now())
    last_applied_at = Column(DateTime(timezone=True))
    
    # Statistics
    resources_affected = Column(Integer, default=0)
    warnings_sent = Column(Integer, default=0)
    deletions_performed = Column(Integer, default=0)
    
    # Relationships
    resources = relationship("Resource", back_populates="lifecycle_policy")
    
    # Indexes
    __table_args__ = (
        Index('idx_policy_enabled_priority', 'enabled', 'priority'),
        Index('idx_policy_resource_types', 'resource_types'),
        Index('idx_policy_auto_apply', 'auto_apply', 'enabled'),
        Index('idx_policy_updated', 'updated_at'),
    )
    
    def __repr__(self):
        return f"<ResourceLifecyclePolicy(name='{self.name}', ttl_days={self.ttl_days})>"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert lifecycle policy to dictionary."""
        return {
            'id': str(self.id),
            'name': self.name,
            'description': self.description,
            'resource_types': self.resource_types,
            'conditions': self.conditions,
            'ttl_days': self.ttl_days,
            'warning_days_before': self.warning_days_before,
            'actions': self.actions,
            'priority': self.priority,
            'enabled': self.enabled,
            'auto_apply': self.auto_apply,
            'require_confirmation': self.require_confirmation,
            'max_deletions_per_day': self.max_deletions_per_day,
            'exclude_patterns': self.exclude_patterns,
            'warning_schedule': self.warning_schedule,
            'grace_period_days': self.grace_period_days,
            'auto_delete_enabled': self.auto_delete_enabled,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'last_applied_at': self.last_applied_at.isoformat() if self.last_applied_at else None,
            'resources_affected': self.resources_affected,
            'warnings_sent': self.warnings_sent,
            'deletions_performed': self.deletions_performed
        }
    
    # Mapping from CloudFormation resource types to simple policy types
    RESOURCE_TYPE_MAPPING = {
        'AWS::Lambda::Function': 'lambda_function',
        'AWS::Lambda::LayerVersion': 'lambda_layer',
        'AWS::EC2::Instance': 'ec2_instance',
        'AWS::EC2::Volume': 'ec2_volume',
        'AWS::EC2::Snapshot': 'ec2_snapshot',
        'AWS::EC2::Image': 'ec2_ami',
        'AWS::EC2::EIP': 'ec2_eip',
        'AWS::S3::Bucket': 's3_bucket',
        'AWS::RDS::DBInstance': 'rds_instance',
        'AWS::RDS::DBCluster': 'rds_cluster',
        'AWS::RDS::DBSnapshot': 'rds_snapshot',
        'AWS::DynamoDB::Table': 'dynamodb_table',
        'AWS::ElastiCache::CacheCluster': 'elasticache_cluster',
        'AWS::ECS::Cluster': 'ecs_cluster',
        'AWS::ECS::Service': 'ecs_service',
        'AWS::ECS::TaskDefinition': 'ecs_task_definition',
        'AWS::EKS::Cluster': 'eks_cluster',
        'AWS::SNS::Topic': 'sns_topic',
        'AWS::SQS::Queue': 'sqs_queue',
        'AWS::CloudWatch::Alarm': 'cloudwatch_alarm',
        'AWS::Logs::LogGroup': 'cloudwatch_log_group',
        'AWS::SecretsManager::Secret': 'secretsmanager_secret',
        'AWS::KMS::Key': 'kms_key',
        'AWS::EC2::VPC': 'ec2_vpc',
        'AWS::EC2::Subnet': 'ec2_subnet',
        'AWS::EC2::SecurityGroup': 'ec2_security_group',
        'AWS::IAM::Role': 'iam_role',
    }

    def is_applicable_to_resource(self, resource: 'Resource') -> bool:
        """Check if this policy applies to the given resource."""
        # Normalize resource type (CloudFormation style -> simple style)
        resource_type = resource.resource_type
        normalized_type = self.RESOURCE_TYPE_MAPPING.get(resource_type, resource_type.lower())

        # Check resource type (empty list = match all types)
        if self.resource_types and normalized_type not in self.resource_types:
            return False
        
        # Check exclude patterns
        if self.exclude_patterns:
            import re
            resource_name = resource.resource_id.lower()
            for pattern in self.exclude_patterns.get('resource_names', []):
                # Convert glob-style wildcards to regex (e.g. "*test*" -> ".*test.*")
                p = pattern.lower()
                if '*' in p or '?' in p:
                    p = re.escape(p).replace(r'\*', '.*').replace(r'\?', '.')
                try:
                    if re.search(p, resource_name):
                        return False
                except re.error:
                    # Fall back to simple substring match on invalid regex
                    if pattern.lower() in resource_name:
                        return False
            
            # Check tag exclusions
            # Handle current_tags - could be dict or JSON string
            raw_tags = resource.current_tags
            if isinstance(raw_tags, str):
                import json
                try:
                    current_tags = json.loads(raw_tags)
                except (json.JSONDecodeError, TypeError):
                    current_tags = {}
            else:
                current_tags = raw_tags or {}
            for tag_exclusion in self.exclude_patterns.get('tags', []):
                tag_key = tag_exclusion.get('key')
                tag_value = tag_exclusion.get('value')
                if tag_key in current_tags:
                    if not tag_value or current_tags[tag_key] == tag_value:
                        return False
        
        # Check conditions (similar to tagging rules)
        # Conditions can be stored as {'tags': [...]} or as a list directly
        conditions_list = self.conditions.get('tags', []) if isinstance(self.conditions, dict) else self.conditions
        # Handle current_tags - could be dict or JSON string
        raw_tags = resource.current_tags
        if isinstance(raw_tags, str):
            import json
            try:
                current_tags = json.loads(raw_tags)
            except (json.JSONDecodeError, TypeError):
                current_tags = {}
        else:
            current_tags = raw_tags or {}
        for condition in conditions_list:
            field = condition.get('field', '')
            operator = condition.get('operator', 'equals')
            value = condition.get('value')

            # Extract field value from resource
            if field.startswith('resource.'):
                field_name = field.replace('resource.', '')
                resource_value = getattr(resource, field_name, None)
            elif field.startswith('tags.'):
                tag_name = field.replace('tags.', '')
                resource_value = current_tags.get(tag_name)
            else:
                continue
            
            # Apply condition
            if operator == 'equals' and resource_value != value:
                return False
            elif operator == 'not_equals' and resource_value == value:
                return False
            elif operator == 'contains' and (not resource_value or value not in str(resource_value)):
                return False
            elif operator == 'exists' and not resource_value:
                return False
            elif operator == 'not_exists' and resource_value:
                return False
        
        return True


class LifecycleAuditLog(Base):
    """Audit log for lifecycle management operations."""
    
    __tablename__ = 'lifecycle_audit_log'
    
    # Primary key
    id = UUID_Column(primary_key=True)
    
    # Resource and policy references
    resource_arn = Column(String(1024), nullable=False, index=True)
    resource_id = Column(String(36), ForeignKey('resources.id'), nullable=True)
    policy_id = Column(String(36), ForeignKey('resource_lifecycle_policies.id'), nullable=True)
    
    # Operation details
    operation = Column(String(50), nullable=False, index=True)  # TTL_SET, WARNING_SENT, DELETION_SCHEDULED, DELETED, PROTECTED
    operation_details = Column(JSON)  # Additional context about the operation
    
    # State changes
    old_state = Column(String(50))
    new_state = Column(String(50))
    old_expires_at = Column(DateTime(timezone=True))
    new_expires_at = Column(DateTime(timezone=True))
    
    # Execution details
    success = Column(Boolean, nullable=False, index=True)
    error_message = Column(Text)
    executed_by = Column(String(256))  # User or system that performed the operation
    executed_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
    
    # Indexes for performance
    __table_args__ = (
        Index('idx_lifecycle_resource_executed', 'resource_arn', 'executed_at'),
        Index('idx_lifecycle_policy_executed', 'policy_id', 'executed_at'),
        Index('idx_lifecycle_operation_success', 'operation', 'success'),
        Index('idx_lifecycle_executed_at', 'executed_at'),
    )
    
    def __repr__(self):
        return f"<LifecycleAuditLog(resource_arn='{self.resource_arn}', operation='{self.operation}', success={self.success})>"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert lifecycle audit log to dictionary."""
        return {
            'id': str(self.id),
            'resource_arn': self.resource_arn,
            'resource_id': str(self.resource_id) if self.resource_id else None,
            'policy_id': str(self.policy_id) if self.policy_id else None,
            'operation': self.operation,
            'operation_details': self.operation_details,
            'old_state': self.old_state,
            'new_state': self.new_state,
            'old_expires_at': self.old_expires_at.isoformat() if self.old_expires_at else None,
            'new_expires_at': self.new_expires_at.isoformat() if self.new_expires_at else None,
            'success': self.success,
            'error_message': self.error_message,
            'executed_by': self.executed_by,
            'executed_at': self.executed_at.isoformat() if self.executed_at else None
        }


# === JSON Query Helper Functions ===
# These functions help handle PostgreSQL JSON field comparisons safely

def is_tags_empty_condition(model):
    """Create a safe condition to check if tags field is empty."""
    empty_json = "{}"
    table_name = model.__table__.name
    return or_(
        model.current_tags == None,
        text(f"{table_name}.current_tags::text = '{empty_json}' OR {table_name}.current_tags::text = 'null'")
    )

def is_tags_not_empty_condition(model):
    """Create a safe condition to check if tags field is not empty."""
    empty_json = "{}"
    table_name = model.__table__.name
    return and_(
        model.current_tags != None,
        text(f"{table_name}.current_tags::text != '{empty_json}' AND {table_name}.current_tags::text != 'null'")
    )


class AccountStatus(Base):
    """Track AWS account status and configuration for multi-account operations."""

    __tablename__ = 'account_status'

    # Primary key
    id = UUID_Column(primary_key=True)

    # Account identification
    account_id = Column(String(12), nullable=False, unique=True, index=True)
    account_name = Column(String(255), nullable=False)
    account_email = Column(String(255))
    organizational_unit_id = Column(String(100), index=True)
    organizational_unit_path = Column(String(500))

    # Account status
    status = Column(String(50), nullable=False, default='ACTIVE', index=True)  # ACTIVE, SUSPENDED, CLOSED
    is_management_account = Column(Boolean, default=False)
    is_delegated_admin = Column(Boolean, default=False)

    # Multi-account configuration
    enabled_for_discovery = Column(Boolean, default=False, nullable=False, index=True)
    enabled_for_tagging = Column(Boolean, default=False, nullable=False, index=True)
    role_name = Column(String(100), default='BlueArchRole')
    role_arn = Column(String(1024))

    # Access validation
    last_access_check = Column(DateTime(timezone=True))
    access_check_status = Column(String(50))  # SUCCESS, FAILED, NOT_TESTED
    access_check_error = Column(Text)

    # Discovery statistics
    last_discovery_at = Column(DateTime(timezone=True))
    total_resources_discovered = Column(Integer, default=0)
    last_discovery_duration_seconds = Column(Integer)

    # Timestamps
    created_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now())
    enabled_at = Column(DateTime(timezone=True))  # When account was enabled for operations
    disabled_at = Column(DateTime(timezone=True))  # When account was disabled

    # Metadata
    metadata_json = Column('metadata', JSON)  # Store additional account configuration

    # Indexes for performance
    __table_args__ = (
        Index('idx_account_status_enabled', 'enabled_for_discovery', 'enabled_for_tagging'),
        Index('idx_account_ou', 'organizational_unit_id', 'enabled_for_discovery'),
        Index('idx_account_status_updated', 'status', 'updated_at'),
        Index('idx_account_last_discovery', 'last_discovery_at'),
    )

    def __repr__(self):
        return f"<AccountStatus(account_id='{self.account_id}', name='{self.account_name}', enabled={self.enabled_for_discovery})>"

    def to_dict(self) -> Dict[str, Any]:
        """Convert account status to dictionary."""
        return {
            'id': str(self.id),
            'account_id': self.account_id,
            'account_name': self.account_name,
            'account_email': self.account_email,
            'organizational_unit_id': self.organizational_unit_id,
            'organizational_unit_path': self.organizational_unit_path,
            'status': self.status,
            'is_management_account': self.is_management_account,
            'is_delegated_admin': self.is_delegated_admin,
            'enabled_for_discovery': self.enabled_for_discovery,
            'enabled_for_tagging': self.enabled_for_tagging,
            'role_name': self.role_name,
            'role_arn': self.role_arn,
            'last_access_check': self.last_access_check.isoformat() if self.last_access_check else None,
            'access_check_status': self.access_check_status,
            'access_check_error': self.access_check_error,
            'last_discovery_at': self.last_discovery_at.isoformat() if self.last_discovery_at else None,
            'total_resources_discovered': self.total_resources_discovered,
            'last_discovery_duration_seconds': self.last_discovery_duration_seconds,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'enabled_at': self.enabled_at.isoformat() if self.enabled_at else None,
            'disabled_at': self.disabled_at.isoformat() if self.disabled_at else None,
            'metadata': self.metadata_json
        }


class SystemExecution(Base):
    """Track system execution times for automated tasks."""

    __tablename__ = 'system_executions'

    # Primary key
    id = UUID_Column(primary_key=True)

    # Execution identification
    task_name = Column(String(100), nullable=False, index=True)  # e.g., 'worker_discovery', 'slack_health_check'
    task_type = Column(String(50), nullable=False, index=True)   # e.g., 'discovery', 'health_check', 'maintenance'

    # Execution tracking
    last_execution_at = Column(DateTime(timezone=True), nullable=False, default=func.now(), index=True)
    execution_status = Column(String(20), nullable=False, default='success', index=True)  # success, failed, running
    execution_duration_ms = Column(Integer)  # Duration in milliseconds

    # Result tracking
    execution_details = Column(JSON)  # Store detailed results
    error_message = Column(Text)
    resources_processed = Column(Integer, default=0)

    # Metadata
    triggered_by = Column(String(100))  # 'auto', 'manual', 'installation'
    execution_context = Column(JSON)   # Additional context data

    # Indexes for performance
    __table_args__ = (
        Index('idx_task_name_execution', 'task_name', 'last_execution_at'),
        Index('idx_task_type_status', 'task_type', 'execution_status'),
        Index('idx_execution_status_time', 'execution_status', 'last_execution_at'),
    )

    def __repr__(self):
        return f"<SystemExecution(task_name='{self.task_name}', status='{self.execution_status}', last_execution='{self.last_execution_at}')>"

    def to_dict(self) -> Dict[str, Any]:
        """Convert system execution to dictionary."""
        return {
            'id': str(self.id),
            'task_name': self.task_name,
            'task_type': self.task_type,
            'last_execution_at': self.last_execution_at.isoformat() if self.last_execution_at else None,
            'execution_status': self.execution_status,
            'execution_duration_ms': self.execution_duration_ms,
            'execution_details': self.execution_details,
            'error_message': self.error_message,
            'resources_processed': self.resources_processed,
            'triggered_by': self.triggered_by,
            'execution_context': self.execution_context
        }

    @classmethod
    def get_last_execution(cls, session, task_name: str) -> Optional['SystemExecution']:
        """Get the last execution record for a task."""
        return session.query(cls).filter(
            cls.task_name == task_name
        ).order_by(cls.last_execution_at.desc()).first()

    @classmethod
    def is_execution_stale(cls, session, task_name: str, hours: int = 24) -> bool:
        """Check if a task execution is stale (older than specified hours)."""
        from datetime import timedelta, timezone
        last_execution = cls.get_last_execution(session, task_name)
        if not last_execution:
            return True  # Never executed

        # Use timezone-aware datetime for comparison
        threshold = datetime.now(timezone.utc) - timedelta(hours=hours)
        return last_execution.last_execution_at < threshold


class CloudWatchAlarm(Base):
    """CloudWatch alarms created and tracked by tag-manager-cli."""

    __tablename__ = 'cloudwatch_alarms'

    # Primary key
    id = UUID_Column(primary_key=True)

    # Alarm identification
    alarm_name = Column(String(255), nullable=False, index=True)
    alarm_arn = Column(String(1024), unique=True, index=True)

    # Target resource information
    target_resource_arn = Column(String(1024), nullable=False, index=True)
    target_resource_type = Column(String(100), nullable=False, index=True)
    target_service = Column(String(50), nullable=False, index=True)

    # AWS Location
    region = Column(String(50), nullable=False, index=True)
    account_id = Column(String(12), nullable=False, index=True)

    # Alarm configuration
    alarm_type = Column(String(50), nullable=False, index=True)
    metric_name = Column(String(255), nullable=False)
    namespace = Column(String(255), nullable=False)
    statistic = Column(String(50), nullable=False)
    period = Column(Integer, nullable=False)
    evaluation_periods = Column(Integer, nullable=False)
    threshold = Column(String(50), nullable=False)
    comparison_operator = Column(String(50), nullable=False)
    treat_missing_data = Column(String(50), default='missing')

    # Alarm actions
    alarm_actions = Column(JSON)
    ok_actions = Column(JSON)
    insufficient_data_actions = Column(JSON)

    # Status tracking
    current_state = Column(String(50), default='UNKNOWN', index=True)
    state_reason = Column(Text)
    state_updated_at = Column(DateTime(timezone=True))

    # Tags applied to alarm
    alarm_tags = Column(JSON)

    # Management metadata
    created_by = Column(String(256), nullable=False)
    created_via = Column(String(50), default='cli')
    created_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now())

    # Sync status
    synced_with_aws = Column(Boolean, default=True)
    last_synced_at = Column(DateTime(timezone=True))
    aws_exists = Column(Boolean, default=True)

    # Relationships
    audit_logs = relationship("AlarmAuditLog", back_populates="alarm", cascade="all, delete-orphan")

    __table_args__ = (
        Index('idx_alarm_target_resource', 'target_resource_arn'),
        Index('idx_alarm_type_service', 'alarm_type', 'target_service'),
        Index('idx_alarm_region_account', 'region', 'account_id'),
        Index('idx_alarm_state', 'current_state'),
        Index('idx_alarm_created_by', 'created_by'),
        Index('idx_alarm_aws_exists', 'aws_exists'),
    )

    def __repr__(self):
        return f"<CloudWatchAlarm(name='{self.alarm_name}', target='{self.target_resource_arn}')>"

    def to_dict(self) -> Dict[str, Any]:
        """Convert alarm to dictionary."""
        return {
            'id': str(self.id),
            'alarm_name': self.alarm_name,
            'alarm_arn': self.alarm_arn,
            'target_resource_arn': self.target_resource_arn,
            'target_resource_type': self.target_resource_type,
            'target_service': self.target_service,
            'region': self.region,
            'account_id': self.account_id,
            'alarm_type': self.alarm_type,
            'metric_name': self.metric_name,
            'namespace': self.namespace,
            'statistic': self.statistic,
            'period': self.period,
            'evaluation_periods': self.evaluation_periods,
            'threshold': self.threshold,
            'comparison_operator': self.comparison_operator,
            'treat_missing_data': self.treat_missing_data,
            'alarm_actions': self.alarm_actions,
            'ok_actions': self.ok_actions,
            'insufficient_data_actions': self.insufficient_data_actions,
            'current_state': self.current_state,
            'state_reason': self.state_reason,
            'state_updated_at': self.state_updated_at.isoformat() if self.state_updated_at else None,
            'alarm_tags': self.alarm_tags,
            'created_by': self.created_by,
            'created_via': self.created_via,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'synced_with_aws': self.synced_with_aws,
            'last_synced_at': self.last_synced_at.isoformat() if self.last_synced_at else None,
            'aws_exists': self.aws_exists
        }


class AlarmAuditLog(Base):
    """Audit log for CloudWatch alarm operations."""

    __tablename__ = 'alarm_audit_log'

    id = UUID_Column(primary_key=True)

    # Alarm reference
    alarm_id = Column(String(36), ForeignKey('cloudwatch_alarms.id'), nullable=True)
    alarm_name = Column(String(255), nullable=False, index=True)
    alarm_arn = Column(String(1024), index=True)

    # Operation details
    operation = Column(String(50), nullable=False, index=True)
    operation_details = Column(JSON)

    # Before/After state for updates
    old_configuration = Column(JSON)
    new_configuration = Column(JSON)

    # Execution details
    success = Column(Boolean, nullable=False)
    error_message = Column(Text)
    executed_by = Column(String(256), nullable=False)
    executed_via = Column(String(50))
    executed_at = Column(DateTime(timezone=True), nullable=False, default=func.now())

    # Relationships
    alarm = relationship("CloudWatchAlarm", back_populates="audit_logs")

    __table_args__ = (
        Index('idx_alarm_audit_operation', 'operation', 'executed_at'),
        Index('idx_alarm_audit_executed_by', 'executed_by'),
        Index('idx_alarm_audit_alarm_name', 'alarm_name'),
    )

    def __repr__(self):
        return f"<AlarmAuditLog(alarm='{self.alarm_name}', operation='{self.operation}')>"

    def to_dict(self) -> Dict[str, Any]:
        """Convert audit log to dictionary."""
        return {
            'id': str(self.id),
            'alarm_id': self.alarm_id,
            'alarm_name': self.alarm_name,
            'alarm_arn': self.alarm_arn,
            'operation': self.operation,
            'operation_details': self.operation_details,
            'old_configuration': self.old_configuration,
            'new_configuration': self.new_configuration,
            'success': self.success,
            'error_message': self.error_message,
            'executed_by': self.executed_by,
            'executed_via': self.executed_via,
            'executed_at': self.executed_at.isoformat() if self.executed_at else None
        }


# === FinOps Models ===


class CURConfiguration(Base):
    """Configuration for AWS Cost and Usage Reports access."""

    __tablename__ = 'cur_configurations'

    # Primary key
    id = UUID_Column(primary_key=True)

    # Account identification
    account_id = Column(String(12), nullable=False, index=True)

    # CUR Report details
    report_name = Column(String(255), nullable=False)
    s3_bucket = Column(String(255), nullable=False)
    s3_prefix = Column(String(500))

    # Athena configuration
    athena_database = Column(String(255), nullable=False)
    athena_table = Column(String(255), nullable=False)
    athena_workgroup = Column(String(255), default='primary')
    region = Column(String(50), nullable=False, default='us-east-1')

    # Status tracking
    status = Column(String(50), default='active', index=True)  # active, setup_pending, error
    last_data_date = Column(DateTime(timezone=True))  # Most recent data available

    # Setup tracking
    setup_stack_id = Column(String(500))  # CloudFormation stack ARN if we created it
    setup_error = Column(Text)  # Error message if setup failed

    # Validation
    last_validated_at = Column(DateTime(timezone=True))
    validation_status = Column(String(50))  # success, failed, pending

    # Timestamps
    created_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now())

    # Indexes
    __table_args__ = (
        Index('idx_cur_account_status', 'account_id', 'status'),
        Index('idx_cur_updated', 'updated_at'),
    )

    def __repr__(self):
        return f"<CURConfiguration(account_id='{self.account_id}', database='{self.athena_database}', status='{self.status}')>"

    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary."""
        return {
            'id': str(self.id),
            'account_id': self.account_id,
            'report_name': self.report_name,
            's3_bucket': self.s3_bucket,
            's3_prefix': self.s3_prefix,
            'athena_database': self.athena_database,
            'athena_table': self.athena_table,
            'athena_workgroup': self.athena_workgroup,
            'region': self.region,
            'status': self.status,
            'last_data_date': self.last_data_date.isoformat() if self.last_data_date else None,
            'setup_stack_id': self.setup_stack_id,
            'setup_error': self.setup_error,
            'last_validated_at': self.last_validated_at.isoformat() if self.last_validated_at else None,
            'validation_status': self.validation_status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


class CostBaseline(Base):
    """Historical cost baselines for anomaly detection."""

    __tablename__ = 'cost_baselines'

    # Primary key
    id = UUID_Column(primary_key=True)

    # Account and tag identification
    account_id = Column(String(12), nullable=False, index=True)
    tag_key = Column(String(255), nullable=False, index=True)
    tag_value = Column(String(255), nullable=False, index=True)

    # Period information
    period_type = Column(String(20), nullable=False)  # daily, weekly, monthly
    period_start = Column(DateTime(timezone=True), nullable=False)
    period_end = Column(DateTime(timezone=True), nullable=False)

    # Cost metrics
    total_cost = Column(String(50), nullable=False)  # Stored as string for precision
    blended_cost = Column(String(50))
    unblended_cost = Column(String(50))

    # Statistics
    resource_count = Column(Integer, default=0)
    service_breakdown = Column(JSON)  # {"EC2": "100.50", "S3": "25.00", ...}

    # Calculated statistics for anomaly detection
    average_cost = Column(String(50))
    std_deviation = Column(String(50))
    min_cost = Column(String(50))
    max_cost = Column(String(50))

    # Metadata
    data_source = Column(String(20), default='cur')  # cur, cost_explorer
    created_at = Column(DateTime(timezone=True), nullable=False, default=func.now())

    # Indexes for performance
    __table_args__ = (
        Index('idx_baseline_tag_period', 'tag_key', 'tag_value', 'period_start'),
        Index('idx_baseline_account_period', 'account_id', 'period_start'),
        Index('idx_baseline_period_type', 'period_type', 'period_start'),
    )

    def __repr__(self):
        return f"<CostBaseline(tag={self.tag_key}={self.tag_value}, period={self.period_start})>"

    def to_dict(self) -> Dict[str, Any]:
        """Convert baseline to dictionary."""
        return {
            'id': str(self.id),
            'account_id': self.account_id,
            'tag_key': self.tag_key,
            'tag_value': self.tag_value,
            'period_type': self.period_type,
            'period_start': self.period_start.isoformat() if self.period_start else None,
            'period_end': self.period_end.isoformat() if self.period_end else None,
            'total_cost': self.total_cost,
            'blended_cost': self.blended_cost,
            'unblended_cost': self.unblended_cost,
            'resource_count': self.resource_count,
            'service_breakdown': self.service_breakdown,
            'average_cost': self.average_cost,
            'std_deviation': self.std_deviation,
            'min_cost': self.min_cost,
            'max_cost': self.max_cost,
            'data_source': self.data_source,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class LifecycleNotification(Base):
    """Track lifecycle notifications sent to users (Slack, email, etc.)."""

    __tablename__ = 'lifecycle_notifications'

    # Primary key
    id = UUID_Column(primary_key=True)

    # Batch tracking (group related notifications)
    batch_id = Column(String(36), index=True)

    # Resource reference
    resource_arn = Column(String(1024), nullable=False, index=True)
    resource_id = Column(String(36), ForeignKey('resources.id'), nullable=True)

    # Notification details
    notification_type = Column(String(50), nullable=False, index=True)  # warning_7d, warning_3d, warning_1d, final, expired
    channel = Column(String(50), nullable=False, index=True)  # slack, cli, email
    status = Column(String(20), nullable=False, default='pending', index=True)  # pending, sent, failed, skipped

    # Message content
    message_summary = Column(Text)  # Short summary of notification
    message_details = Column(JSON)  # Full message details

    # Timing
    scheduled_at = Column(DateTime(timezone=True))  # When notification was scheduled
    sent_at = Column(DateTime(timezone=True))  # When notification was actually sent
    created_at = Column(DateTime(timezone=True), nullable=False, default=func.now())

    # Delivery details
    delivery_response = Column(JSON)  # Response from notification service
    error_message = Column(Text)  # Error if failed
    retry_count = Column(Integer, default=0)

    # Context
    expires_at = Column(DateTime(timezone=True))  # Resource expiration at time of notification
    days_until_expiry = Column(Integer)  # Days until expiry at time of notification

    # Indexes for performance
    __table_args__ = (
        Index('idx_notification_batch', 'batch_id'),
        Index('idx_notification_resource_type', 'resource_arn', 'notification_type'),
        Index('idx_notification_status_channel', 'status', 'channel'),
        Index('idx_notification_created', 'created_at'),
        Index('idx_notification_scheduled', 'scheduled_at', 'status'),
    )

    def __repr__(self):
        return f"<LifecycleNotification(resource='{self.resource_arn}', type='{self.notification_type}', status='{self.status}')>"

    def to_dict(self) -> Dict[str, Any]:
        """Convert notification to dictionary."""
        return {
            'id': str(self.id),
            'batch_id': self.batch_id,
            'resource_arn': self.resource_arn,
            'resource_id': str(self.resource_id) if self.resource_id else None,
            'notification_type': self.notification_type,
            'channel': self.channel,
            'status': self.status,
            'message_summary': self.message_summary,
            'message_details': self.message_details,
            'scheduled_at': self.scheduled_at.isoformat() if self.scheduled_at else None,
            'sent_at': self.sent_at.isoformat() if self.sent_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'delivery_response': self.delivery_response,
            'error_message': self.error_message,
            'retry_count': self.retry_count,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'days_until_expiry': self.days_until_expiry
        }


class NotificationEvent(Base):
    """Audit trail for product notifications sent by local CLI services."""

    __tablename__ = 'notification_events'

    id = UUID_Column(primary_key=True)
    source = Column(String(100), nullable=False, index=True)
    event_key = Column(String(255), nullable=False)
    severity = Column(String(50), nullable=False, default='warning', index=True)
    title = Column(String(255), nullable=False)
    message = Column(Text)
    payload = Column(JSON)
    notification_sent = Column(Boolean, default=False)
    notification_error = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
    sent_at = Column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint('source', 'event_key', name='uq_notification_event_source_key'),
        Index('idx_notification_events_source_created', 'source', 'created_at'),
    )


class LifecycleDecision(Base):
    """Track user decisions on lifecycle actions (extend, protect, terminate, skip)."""

    __tablename__ = 'lifecycle_decisions'

    # Primary key
    id = UUID_Column(primary_key=True)

    # Resource reference
    resource_arn = Column(String(1024), nullable=False, index=True)
    resource_id = Column(String(36), ForeignKey('resources.id'), nullable=True)

    # Decision details
    decision_type = Column(String(50), nullable=False, index=True)  # extend, protect, unprotect, terminate, skip, defer
    decision_reason = Column(Text)  # User-provided reason for decision

    # State changes
    previous_state = Column(String(50))  # Lifecycle state before decision
    new_state = Column(String(50))  # Lifecycle state after decision
    previous_expires_at = Column(DateTime(timezone=True))
    new_expires_at = Column(DateTime(timezone=True))

    # Extension details (if decision_type is 'extend')
    extension_days = Column(Integer)  # Days extended by

    # Protection details (if decision_type is 'protect')
    protection_reason = Column(Text)  # Why resource is protected
    protection_expires_at = Column(DateTime(timezone=True))  # Optional: protection expiration

    # Decision context
    decided_by = Column(String(256), nullable=False, index=True)  # User who made decision
    decided_via = Column(String(50))  # cli, slack, api
    decided_at = Column(DateTime(timezone=True), nullable=False, default=func.now())

    # Notification reference (if decision was made in response to notification)
    notification_id = Column(String(36), ForeignKey('lifecycle_notifications.id'), nullable=True)

    # Execution tracking
    executed = Column(Boolean, default=False)  # Whether decision has been executed
    executed_at = Column(DateTime(timezone=True))
    execution_error = Column(Text)

    # Metadata
    metadata_json = Column('metadata', JSON)

    # Indexes for performance
    __table_args__ = (
        Index('idx_decision_resource_type', 'resource_arn', 'decision_type'),
        Index('idx_decision_decided_by', 'decided_by', 'decided_at'),
        Index('idx_decision_type_executed', 'decision_type', 'executed'),
        Index('idx_decision_decided_at', 'decided_at'),
    )

    def __repr__(self):
        return f"<LifecycleDecision(resource='{self.resource_arn}', type='{self.decision_type}', by='{self.decided_by}')>"

    def to_dict(self) -> Dict[str, Any]:
        """Convert decision to dictionary."""
        return {
            'id': str(self.id),
            'resource_arn': self.resource_arn,
            'resource_id': str(self.resource_id) if self.resource_id else None,
            'decision_type': self.decision_type,
            'decision_reason': self.decision_reason,
            'previous_state': self.previous_state,
            'new_state': self.new_state,
            'previous_expires_at': self.previous_expires_at.isoformat() if self.previous_expires_at else None,
            'new_expires_at': self.new_expires_at.isoformat() if self.new_expires_at else None,
            'extension_days': self.extension_days,
            'protection_reason': self.protection_reason,
            'protection_expires_at': self.protection_expires_at.isoformat() if self.protection_expires_at else None,
            'decided_by': self.decided_by,
            'decided_via': self.decided_via,
            'decided_at': self.decided_at.isoformat() if self.decided_at else None,
            'notification_id': str(self.notification_id) if self.notification_id else None,
            'executed': self.executed,
            'executed_at': self.executed_at.isoformat() if self.executed_at else None,
            'execution_error': self.execution_error,
            'metadata': self.metadata_json
        }


class CostAnomalyAlert(Base):
    """Detected cost anomalies for tracking and alerting."""

    __tablename__ = 'cost_anomaly_alerts'

    # Primary key
    id = UUID_Column(primary_key=True)

    # Account and tag identification
    account_id = Column(String(12), nullable=False, index=True)
    tag_key = Column(String(255), nullable=False, index=True)
    tag_value = Column(String(255), nullable=False)

    # Detection timestamp
    detected_at = Column(DateTime(timezone=True), nullable=False, default=func.now())

    # Anomaly classification
    anomaly_type = Column(String(50), nullable=False, index=True)  # spike, drop, trend_change, new_cost
    severity = Column(String(20), default='medium', index=True)  # low, medium, high, critical

    # Cost details
    current_cost = Column(String(50), nullable=False)
    baseline_cost = Column(String(50), nullable=False)
    absolute_change = Column(String(50), nullable=False)
    percent_change = Column(String(50), nullable=False)

    # Threshold that was exceeded
    threshold_type = Column(String(50))  # percent_threshold, absolute_threshold, std_deviation

    # Period information
    period = Column(String(50))  # e.g., "2024-01"
    period_start = Column(DateTime(timezone=True))
    period_end = Column(DateTime(timezone=True))

    # Status tracking
    status = Column(String(20), default='new', index=True)  # new, acknowledged, resolved, ignored
    acknowledged_by = Column(String(256))
    acknowledged_at = Column(DateTime(timezone=True))
    resolved_at = Column(DateTime(timezone=True))
    resolution_notes = Column(Text)

    # Additional context
    details = Column(JSON)  # Additional anomaly context

    # Timestamps
    created_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now())

    # Indexes for performance
    __table_args__ = (
        Index('idx_anomaly_status_severity', 'status', 'severity'),
        Index('idx_anomaly_tag_detected', 'tag_key', 'tag_value', 'detected_at'),
        Index('idx_anomaly_account_detected', 'account_id', 'detected_at'),
        Index('idx_anomaly_type_status', 'anomaly_type', 'status'),
    )

    def __repr__(self):
        return f"<CostAnomalyAlert(tag={self.tag_key}={self.tag_value}, type={self.anomaly_type}, severity={self.severity})>"

    def to_dict(self) -> Dict[str, Any]:
        """Convert anomaly alert to dictionary."""
        return {
            'id': str(self.id),
            'account_id': self.account_id,
            'tag_key': self.tag_key,
            'tag_value': self.tag_value,
            'detected_at': self.detected_at.isoformat() if self.detected_at else None,
            'anomaly_type': self.anomaly_type,
            'severity': self.severity,
            'current_cost': self.current_cost,
            'baseline_cost': self.baseline_cost,
            'absolute_change': self.absolute_change,
            'percent_change': self.percent_change,
            'threshold_type': self.threshold_type,
            'period': self.period,
            'period_start': self.period_start.isoformat() if self.period_start else None,
            'period_end': self.period_end.isoformat() if self.period_end else None,
            'status': self.status,
            'acknowledged_by': self.acknowledged_by,
            'acknowledged_at': self.acknowledged_at.isoformat() if self.acknowledged_at else None,
            'resolved_at': self.resolved_at.isoformat() if self.resolved_at else None,
            'resolution_notes': self.resolution_notes,
            'details': self.details,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


class ScanJob(Base):
    """Scan job progress tracked in the shared DB.

    Both BlueArch and Tag Manager CLIs read/write this table so a scan
    started in one app shows progress in both dashboards.
    """

    __tablename__ = "scan_jobs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    source = Column(String(32), nullable=False, default="tag-manager", index=True)
    status = Column(String(20), nullable=False, default="pending", index=True)
    progress = Column(Integer, default=0)
    progress_message = Column(Text)
    progress_data = Column(JSON)
    message = Column(Text)
    result = Column(JSON)
    error = Column(Text)
    services = Column(JSON)
    regions = Column(JSON)
    created_at = Column(DateTime(timezone=True), nullable=False, default=func.now(), index=True)
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))

    __table_args__ = (
        Index("idx_scan_job_status_created", "status", "created_at"),
    )


class AssumeRoleConfiguration(Base):
    """Store assume role configuration for the CLI.

    This table stores configurations for assume-role based authentication.
    When enabled, the CLI will automatically assume the configured role
    instead of using direct credentials.

    Designed to support multiple accounts in the future.
    Currently, only one account is active at a time.
    """
    __tablename__ = 'assume_role_configurations'

    # Primary key
    id = UUID_Column(primary_key=True)

    # Account and role identification
    account_id = Column(String(12), nullable=False, index=True)
    role_arn = Column(String(2048), nullable=False)
    role_name = Column(String(64), nullable=False, default='BlueArchCLIRole')

    # Security configuration
    external_id = Column(String(256), nullable=True)  # Optional external ID for role assumption

    # Status flags
    is_active = Column(Boolean, default=False, nullable=False, index=True)  # Only one can be active at a time
    enabled = Column(Boolean, default=True, nullable=False)  # Can be temporarily disabled without deleting

    # Optional friendly name for multi-account support
    alias = Column(String(64), nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    last_used_at = Column(DateTime(timezone=True), nullable=True)

    # Indexes for performance
    __table_args__ = (
        Index('idx_assume_role_account_active', 'account_id', 'is_active'),
        Index('idx_assume_role_active_enabled', 'is_active', 'enabled'),
    )

    def __repr__(self):
        return f"<AssumeRoleConfiguration(account={self.account_id}, role={self.role_name}, active={self.is_active})>"

    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary."""
        return {
            'id': str(self.id),
            'account_id': self.account_id,
            'role_arn': self.role_arn,
            'role_name': self.role_name,
            'external_id': '***' if self.external_id else None,  # Mask external ID
            'is_active': self.is_active,
            'enabled': self.enabled,
            'alias': self.alias,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'last_used_at': self.last_used_at.isoformat() if self.last_used_at else None
        }


class ChatConversation(Base):
    """AI chat conversation session."""

    __tablename__ = 'chat_conversations'

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title = Column(String(256), nullable=False)
    model = Column(String(20), default='auto')
    message_count = Column(Integer, default=0)
    total_input_tokens = Column(Integer, default=0)
    total_output_tokens = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, default=func.now())

    def __repr__(self):
        return f"<ChatConversation(id={self.id}, title={self.title[:30]})>"


class ChatMessage(Base):
    """Individual message in a chat conversation."""

    __tablename__ = 'chat_messages'

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    conversation_id = Column(String(36), ForeignKey('chat_conversations.id'), nullable=False, index=True)
    role = Column(String(10), nullable=False)  # 'user' or 'assistant'
    content = Column(Text, nullable=False)
    tool_calls = Column(Text, nullable=True)  # JSON array of tool call records
    tokens = Column(Text, nullable=True)  # JSON {input, output}
    created_at = Column(DateTime(timezone=True), nullable=False, default=func.now())

    def __repr__(self):
        return f"<ChatMessage(id={self.id}, role={self.role}, conv={self.conversation_id})>"


# === Event-Driven Sync Models ===


class EventSyncConfiguration(Base):
    """Configuration for event-driven resource sync queues (Pro feature).

    Each record represents a deployed event-tracking stack in a specific
    account-region pair.  The EventSyncService polls SQS queues referenced
    here to keep the resource database synchronised in near-real-time.
    """

    __tablename__ = 'event_sync_configuration'

    # Primary key
    id = Column(Integer, primary_key=True, autoincrement=True)

    # Account and region identification
    account_id = Column(String(20), nullable=False, index=True)
    region = Column(String(30), nullable=False)

    # SQS queue details (populated from stack outputs after deployment)
    queue_url = Column(String(512), nullable=False)
    queue_arn = Column(String(512), nullable=False)

    # CloudFormation stack tracking
    stack_name = Column(String(256), nullable=False)
    stack_id = Column(String(512))

    # Deployment status: deploying, active, paused, failed, removing
    status = Column(String(20), nullable=False, default='deploying', index=True)

    # Timestamps
    deployed_at = Column(DateTime(timezone=True))
    last_polled_at = Column(DateTime(timezone=True))
    last_event_at = Column(DateTime(timezone=True))

    # Counters
    messages_processed = Column(Integer, default=0)
    events_today = Column(Integer, default=0)
    events_today_reset_at = Column(DateTime(timezone=True))

    # Error tracking
    error_message = Column(Text, nullable=True)

    # Standard timestamps
    created_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, default=func.now(), onupdate=func.now())

    # Constraints and indexes
    __table_args__ = (
        UniqueConstraint('account_id', 'region', name='uq_event_sync_account_region'),
        Index('idx_event_sync_status', 'status'),
        Index('idx_event_sync_account_region', 'account_id', 'region'),
        Index('idx_event_sync_last_polled', 'last_polled_at'),
    )

    def __repr__(self):
        return f"<EventSyncConfiguration(account={self.account_id}, region={self.region}, status={self.status})>"

    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary."""
        return {
            'id': self.id,
            'account_id': self.account_id,
            'region': self.region,
            'queue_url': self.queue_url,
            'queue_arn': self.queue_arn,
            'stack_name': self.stack_name,
            'stack_id': self.stack_id,
            'status': self.status,
            'deployed_at': self.deployed_at.isoformat() if self.deployed_at else None,
            'last_polled_at': self.last_polled_at.isoformat() if self.last_polled_at else None,
            'last_event_at': self.last_event_at.isoformat() if self.last_event_at else None,
            'messages_processed': self.messages_processed,
            'events_today': self.events_today,
            'events_today_reset_at': self.events_today_reset_at.isoformat() if self.events_today_reset_at else None,
            'error_message': self.error_message,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class AccountContext(Base):
    """Registered AWS account contexts for multi-account isolation."""

    __tablename__ = 'account_context'

    id = UUID_Column(primary_key=True)
    account_id = Column(String(12), nullable=False, unique=True, index=True)
    account_alias = Column(String(256), nullable=True)
    aws_profile = Column(String(256), nullable=True)
    region = Column(String(50), nullable=True)
    user_arn = Column(String(256), nullable=True)
    is_current = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
    last_used_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index('idx_account_context_current', 'is_current'),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': str(self.id),
            'account_id': self.account_id,
            'account_alias': self.account_alias,
            'aws_profile': self.aws_profile,
            'region': self.region,
            'user_arn': self.user_arn,
            'is_current': self.is_current,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_used_at': self.last_used_at.isoformat() if self.last_used_at else None,
        }


class PermissionCache(Base):
    """Cached IAM permission simulation results per account/principal."""

    __tablename__ = 'permission_cache'

    account_id = Column(String(12), nullable=False, primary_key=True)
    user_arn = Column(String(256), nullable=False, primary_key=True)
    action = Column(String(128), nullable=False, primary_key=True)
    granted = Column(Boolean, nullable=False)
    checked_at = Column(DateTime(timezone=True), nullable=False, default=func.now())


class PermissionTier(Base):
    """Computed permission tier and feature availability per account/principal."""

    __tablename__ = 'permission_tier'

    account_id = Column(String(12), nullable=False, primary_key=True)
    user_arn = Column(String(256), nullable=False, primary_key=True)
    tier = Column(String(20), nullable=False)
    features_json = Column(JSON, nullable=False)
    checked_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=False)


class ResourceRelationship(Base):
    """Tracks relationships between AWS resources for graph visualization."""

    __tablename__ = 'resource_relationships'

    id = UUID_Column(primary_key=True)
    source_arn = Column(String(1024), nullable=False, index=True)
    target_arn = Column(String(1024), nullable=False, index=True)
    relationship_type = Column(String(50), nullable=False, index=True)
    source_type = Column(String(100), nullable=False)
    target_type = Column(String(100), nullable=False)
    region = Column(String(50), nullable=False, index=True)
    account_id = Column(String(12), nullable=False, index=True)
    metadata_json = Column('metadata', JSON)
    discovered_at = Column(DateTime(timezone=True), default=func.now())
    last_seen_at = Column(DateTime(timezone=True), default=func.now())

    __table_args__ = (
        UniqueConstraint('source_arn', 'target_arn', 'relationship_type', name='uq_relationship_edge'),
        Index('idx_rel_source_type', 'source_arn', 'relationship_type'),
        Index('idx_rel_target_type', 'target_arn', 'relationship_type'),
        Index('idx_rel_account_region', 'account_id', 'region'),
    )
