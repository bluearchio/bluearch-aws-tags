"""EventSyncService compatibility wrapper for bluearch-core event tracking.

The product no longer polls SQS or mutates resource rows directly. Core owns
queue polling and resource updates; this module keeps old imports/call sites
working by delegating status and poll calls to bluearch-core.
"""

import importlib.util
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

from ..utils.core_client import request_core


def _load_event_processor():
    """Load the lambda/event_processor.py module dynamically.

    The lambda/ directory is not a Python package (it deploys standalone).
    We load it by path so we can reuse ACTION_MAP, extract_arns, extract_tags.
    """
    # Try multiple paths: dev (project root) and bundled (PyInstaller)
    candidates = [
        Path(__file__).parent.parent.parent / "lambda" / "event_processor.py",
    ]
    meipass = getattr(importlib.util, "__spec__", None)
    import sys
    if getattr(sys, "_MEIPASS", None):
        candidates.insert(0, Path(sys._MEIPASS) / "lambda" / "event_processor.py")

    for path in candidates:
        if path.exists():
            spec = importlib.util.spec_from_file_location("event_processor", path)
            mod = importlib.util.module_from_spec(spec)
            # Provide dummy env vars the Lambda module expects at import time.
            # AWS_DEFAULT_REGION is needed because the Lambda creates
            # boto3 clients at module level (no region in Lambda = env var).
            _orig_queue = os.environ.get("SQS_QUEUE_URL")
            _orig_region = os.environ.get("AWS_DEFAULT_REGION")
            os.environ.setdefault("SQS_QUEUE_URL", "dummy://not-used")
            os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
            try:
                spec.loader.exec_module(mod)
            finally:
                if _orig_queue is None:
                    os.environ.pop("SQS_QUEUE_URL", None)
                else:
                    os.environ["SQS_QUEUE_URL"] = _orig_queue
                if _orig_region is None:
                    os.environ.pop("AWS_DEFAULT_REGION", None)
                else:
                    os.environ["AWS_DEFAULT_REGION"] = _orig_region
            return mod

    return None


_event_processor = None
_event_processor_failed = False


def _get_event_processor():
    """Lazy-load the event processor module on first use."""
    global _event_processor, _event_processor_failed
    if _event_processor is None and not _event_processor_failed:
        try:
            _event_processor = _load_event_processor()
        except Exception:
            _event_processor_failed = True
            logging.getLogger(__name__).warning(
                "Failed to load event_processor module, event normalisation disabled"
            )
    return _event_processor

logger = logging.getLogger(__name__)

# Map CloudTrail event source to our CFN-style resource_type.
#
# Must match the values emitted by the resource collectors (discovery.py and
# the ops collectors implementation) so the shared SQLite DB
# has a single canonical shape for every AWS resource type. Writing
# short-form here (the previous "ec2_instance" form) caused duplicate /
# invisible rows depending on which CLI last touched the row.
SERVICE_TYPE_MAP: Dict[str, Dict[str, str]] = {
    "ec2": {
        "RunInstances": "AWS::EC2::Instance",
        "CreateVolume": "AWS::EC2::Volume",
        "CreateSnapshot": "AWS::EC2::Snapshot",
        "RegisterImage": "AWS::EC2::Image",
        "AllocateAddress": "AWS::EC2::EIP",
        "TerminateInstances": "AWS::EC2::Instance",
        "DeleteVolume": "AWS::EC2::Volume",
        "DeleteSnapshot": "AWS::EC2::Snapshot",
        "DeregisterImage": "AWS::EC2::Image",
        "ReleaseAddress": "AWS::EC2::EIP",
    },
    "s3": {
        "CreateBucket": "AWS::S3::Bucket",
        "DeleteBucket": "AWS::S3::Bucket",
    },
    "lambda": {
        "CreateFunction20150331": "AWS::Lambda::Function",
        "DeleteFunction20150331": "AWS::Lambda::Function",
    },
    "rds": {
        "CreateDBInstance": "AWS::RDS::DBInstance",
        "CreateDBCluster": "AWS::RDS::DBCluster",
        "DeleteDBInstance": "AWS::RDS::DBInstance",
        "DeleteDBCluster": "AWS::RDS::DBCluster",
    },
    "dynamodb": {
        "CreateTable": "AWS::DynamoDB::Table",
        "DeleteTable": "AWS::DynamoDB::Table",
    },
    "ecs": {
        "CreateCluster": "AWS::ECS::Cluster",
        "CreateService": "AWS::ECS::Service",
        "RegisterTaskDefinition": "AWS::ECS::TaskDefinition",
        "DeleteCluster": "AWS::ECS::Cluster",
        "DeleteService": "AWS::ECS::Service",
        "DeregisterTaskDefinition": "AWS::ECS::TaskDefinition",
    },
    "elasticloadbalancing": {
        # Modern ELB v2 (ALB/NLB). Classic ELBv1 is essentially retired and
        # produces the same event source, so we default to the v2 CFN type.
        "CreateLoadBalancer": "AWS::ElasticLoadBalancingV2::LoadBalancer",
        "CreateTargetGroup": "AWS::ElasticLoadBalancingV2::TargetGroup",
        "DeleteLoadBalancer": "AWS::ElasticLoadBalancingV2::LoadBalancer",
        "DeleteTargetGroup": "AWS::ElasticLoadBalancingV2::TargetGroup",
    },
    "sns": {
        "CreateTopic": "AWS::SNS::Topic",
        "DeleteTopic": "AWS::SNS::Topic",
    },
    "sqs": {
        "CreateQueue": "AWS::SQS::Queue",
        "DeleteQueue": "AWS::SQS::Queue",
    },
    "monitoring": {
        "PutMetricAlarm": "AWS::CloudWatch::Alarm",
        "DeleteAlarms": "AWS::CloudWatch::Alarm",
    },
    "eks": {
        "CreateNodegroup": "AWS::EKS::Cluster",
        "DeleteNodegroup": "AWS::EKS::Cluster",
    },
    "elasticache": {
        "CreateCacheCluster": "AWS::ElastiCache::CacheCluster",
        "CreateReplicationGroup": "AWS::ElastiCache::CacheCluster",
        "DeleteCacheCluster": "AWS::ElastiCache::CacheCluster",
        "DeleteReplicationGroup": "AWS::ElastiCache::CacheCluster",
    },
}


def _resource_type_for_event(service_name: str, event_name: str) -> str:
    """Determine the CFN-style resource_type for a given service + event."""
    svc_map = SERVICE_TYPE_MAP.get(service_name, {})
    rtype = svc_map.get(event_name)
    if rtype:
        return rtype
    # Fallback for unmapped services: keep the old short-form so downstream
    # de-dup by resource_arn still works.
    return f"{service_name}_resource"


# ---------------------------------------------------------------------------
# Metadata extraction from CloudTrail requestParameters / responseElements
# ---------------------------------------------------------------------------
#
# Collector-shaped metadata means future recommendation rules can match
# resources created via events without waiting for the next scan.
# Each extractor below returns a dict of keys identical to what the resource
# collectors emit, with None for anything the event payload doesn't carry
# (the next scan fills them in).


def _meta_ec2_instance(detail: dict) -> Dict[str, Any]:
    req = detail.get("requestParameters") or {}
    resp = detail.get("responseElements") or {}
    items = ((resp.get("instancesSet") or {}).get("items") or [])
    item = items[0] if items else {}
    state = (item.get("instanceState") or {}).get("name")
    return {
        "instance_type": item.get("instanceType") or req.get("instanceType"),
        "state": state,
        "vpc_id": item.get("vpcId"),
        "subnet_id": item.get("subnetId") or req.get("subnetId"),
        "public_ip": item.get("ipAddress") or item.get("publicIpAddress"),
        "private_ip": item.get("privateIpAddress"),
        "platform": item.get("platform") or "linux",
        "image_id": item.get("imageId") or req.get("imageId"),
    }


def _meta_ec2_volume(detail: dict) -> Dict[str, Any]:
    req = detail.get("requestParameters") or {}
    resp = detail.get("responseElements") or {}
    return {
        "availability_zone": resp.get("availabilityZone") or req.get("availabilityZone"),
        "encrypted": resp.get("encrypted") if "encrypted" in resp else req.get("encrypted"),
        "iops": resp.get("iops") or req.get("iops"),
        "size_gb": resp.get("size") or req.get("size"),
        "state": resp.get("status") or resp.get("state"),
        "throughput": resp.get("throughput") or req.get("throughput"),
        "volume_type": resp.get("volumeType") or req.get("volumeType"),
    }


def _meta_ec2_snapshot(detail: dict) -> Dict[str, Any]:
    req = detail.get("requestParameters") or {}
    resp = detail.get("responseElements") or {}
    return {
        "volume_id": resp.get("volumeId") or req.get("volumeId"),
        "volume_size": resp.get("volumeSize"),
        "state": resp.get("status") or resp.get("state"),
        "encrypted": resp.get("encrypted"),
        "description": resp.get("description") or req.get("description"),
    }


def _meta_ec2_eip(detail: dict) -> Dict[str, Any]:
    resp = detail.get("responseElements") or {}
    return {
        "public_ip": resp.get("publicIp"),
        "association_id": None,
        "instance_id": None,
        "domain": resp.get("domain"),
        "allocation_id": resp.get("allocationId"),
        "network_interface_id": None,
        "private_ip": None,
    }


def _meta_s3_bucket(detail: dict) -> Dict[str, Any]:
    req = detail.get("requestParameters") or {}
    return {
        "bucket_name": req.get("bucketName"),
        "creation_date": detail.get("eventTime"),
    }


def _meta_lambda_function(detail: dict) -> Dict[str, Any]:
    req = detail.get("requestParameters") or {}
    resp = detail.get("responseElements") or {}
    return {
        "runtime": resp.get("runtime") or req.get("runtime"),
        "handler": resp.get("handler") or req.get("handler"),
        "memory_size": resp.get("memorySize") or req.get("memorySize"),
        "timeout": resp.get("timeout") or req.get("timeout"),
        "code_size": resp.get("codeSize"),
        "state": resp.get("state"),
        "function_name": resp.get("functionName") or req.get("functionName"),
        "last_modified": resp.get("lastModified") or detail.get("eventTime"),
        "architectures": resp.get("architectures") or req.get("architectures") or ["x86_64"],
    }


def _meta_rds_dbinstance(detail: dict) -> Dict[str, Any]:
    req = detail.get("requestParameters") or {}
    return {
        "engine": req.get("engine"),
        "engine_version": req.get("engineVersion"),
        "instance_class": req.get("dBInstanceClass"),
        "status": "creating",
        "storage_type": req.get("storageType"),
        "storage_gb": req.get("allocatedStorage"),
        "storage_encrypted": req.get("storageEncrypted"),
        "multi_az": req.get("multiAZ"),
        "publicly_accessible": req.get("publiclyAccessible"),
        "deletion_protection": req.get("deletionProtection"),
        "backup_retention_period": req.get("backupRetentionPeriod"),
    }


def _meta_rds_dbcluster(detail: dict) -> Dict[str, Any]:
    req = detail.get("requestParameters") or {}
    return {
        "engine": req.get("engine"),
        "engine_version": req.get("engineVersion"),
        "status": "creating",
        "storage_encrypted": req.get("storageEncrypted"),
        "multi_az": None,
        "deletion_protection": req.get("deletionProtection"),
        "database_name": req.get("databaseName"),
    }


def _meta_dynamodb_table(detail: dict) -> Dict[str, Any]:
    req = detail.get("requestParameters") or {}
    resp = detail.get("responseElements") or {}
    td = (resp.get("tableDescription") or {})
    return {
        "table_status": td.get("tableStatus") or "CREATING",
        "item_count": td.get("itemCount") or 0,
        "table_size_bytes": td.get("tableSizeBytes") or 0,
        "billing_mode": (
            (td.get("billingModeSummary") or {}).get("billingMode")
            or req.get("billingMode")
            or "PROVISIONED"
        ),
    }


def _meta_ecs_cluster(detail: dict) -> Dict[str, Any]:
    resp = detail.get("responseElements") or {}
    cl = resp.get("cluster") or {}
    return {
        "status": cl.get("status") or "ACTIVE",
        "running_tasks": cl.get("runningTasksCount") or 0,
        "pending_tasks": cl.get("pendingTasksCount") or 0,
        "active_services": cl.get("activeServicesCount") or 0,
        "registered_instances": cl.get("registeredContainerInstancesCount") or 0,
    }


def _meta_ecs_service(detail: dict) -> Dict[str, Any]:
    req = detail.get("requestParameters") or {}
    resp = detail.get("responseElements") or {}
    svc = resp.get("service") or {}
    return {
        "status": svc.get("status") or "ACTIVE",
        "desired_count": svc.get("desiredCount") or req.get("desiredCount") or 0,
        "running_count": svc.get("runningCount") or 0,
        "launch_type": svc.get("launchType") or req.get("launchType"),
        "pending_count": svc.get("pendingCount") or 0,
        "cluster_arn": svc.get("clusterArn") or req.get("cluster"),
    }


def _meta_sns_topic(detail: dict) -> Dict[str, Any]:
    req = detail.get("requestParameters") or {}
    name = req.get("name") or ""
    attrs = req.get("attributes") or {}
    return {
        "topic_name": name,
        "display_name": attrs.get("DisplayName"),
        "fifo_topic": name.endswith(".fifo"),
        "kms_master_key_id": attrs.get("KmsMasterKeyId"),
        "subscriptions_confirmed": 0,
        "subscriptions_pending": 0,
    }


def _meta_sqs_queue(detail: dict) -> Dict[str, Any]:
    req = detail.get("requestParameters") or {}
    resp = detail.get("responseElements") or {}
    name = req.get("queueName") or ""
    attrs = req.get("attribute") or {}
    try:
        retention = int(attrs.get("MessageRetentionPeriod", 0))
    except (TypeError, ValueError):
        retention = 0
    try:
        vis = int(attrs.get("VisibilityTimeout", 0))
    except (TypeError, ValueError):
        vis = 0
    return {
        "queue_name": name,
        "approximate_messages": 0,
        "visibility_timeout": vis,
        "approximate_messages_delayed": 0,
        "fifo_queue": attrs.get("FifoQueue") == "true" or name.endswith(".fifo"),
        "kms_master_key_id": attrs.get("KmsMasterKeyId"),
        "message_retention_period": retention,
        "queue_url": resp.get("queueUrl"),
    }


def _meta_cloudwatch_alarm(detail: dict) -> Dict[str, Any]:
    req = detail.get("requestParameters") or {}
    return {
        "state_value": "OK",
        "metric_name": req.get("metricName"),
        "namespace": req.get("namespace"),
        "threshold": req.get("threshold"),
        "actions_enabled": req.get("actionsEnabled", True),
        "comparison_operator": req.get("comparisonOperator"),
    }


def _meta_elasticache_cluster(detail: dict) -> Dict[str, Any]:
    req = detail.get("requestParameters") or {}
    return {
        "engine": req.get("engine"),
        "engine_version": req.get("engineVersion"),
        "cache_node_type": req.get("cacheNodeType"),
        "num_cache_nodes": req.get("numCacheNodes"),
        "status": "creating",
    }


# resource_type -> extractor
_METADATA_EXTRACTORS: Dict[str, Any] = {
    "AWS::EC2::Instance": _meta_ec2_instance,
    "AWS::EC2::Volume": _meta_ec2_volume,
    "AWS::EC2::Snapshot": _meta_ec2_snapshot,
    "AWS::EC2::EIP": _meta_ec2_eip,
    "AWS::S3::Bucket": _meta_s3_bucket,
    "AWS::Lambda::Function": _meta_lambda_function,
    "AWS::RDS::DBInstance": _meta_rds_dbinstance,
    "AWS::RDS::DBCluster": _meta_rds_dbcluster,
    "AWS::DynamoDB::Table": _meta_dynamodb_table,
    "AWS::ECS::Cluster": _meta_ecs_cluster,
    "AWS::ECS::Service": _meta_ecs_service,
    "AWS::SNS::Topic": _meta_sns_topic,
    "AWS::SQS::Queue": _meta_sqs_queue,
    "AWS::CloudWatch::Alarm": _meta_cloudwatch_alarm,
    "AWS::ElastiCache::CacheCluster": _meta_elasticache_cluster,
}


def _extract_metadata(resource_type: str, detail: dict) -> Optional[Dict[str, Any]]:
    """Return collector-shaped metadata for a CloudTrail event, or None."""
    extractor = _METADATA_EXTRACTORS.get(resource_type)
    if not extractor:
        return None
    try:
        meta = extractor(detail)
    except Exception as exc:
        logger.debug("metadata extraction failed for %s: %s", resource_type, exc)
        return None
    # Drop keys whose values are all-None so we don't overwrite good metadata
    # that a prior scan already wrote.
    return {k: v for k, v in meta.items() if v is not None} or None


def _resource_id_from_arn(arn: str) -> str:
    """Extract a short resource ID from an ARN.

    e.g. arn:aws:ec2:us-east-1:123:instance/i-abc -> i-abc
         arn:aws:s3:::my-bucket -> my-bucket
    """
    if not arn:
        return ""
    parts = arn.split(":")
    if len(parts) >= 6:
        resource_part = ":".join(parts[5:])
        # Handle resource/id and resource:id formats
        for sep in ("/", ":"):
            if sep in resource_part:
                return resource_part.split(sep, 1)[-1]
        return resource_part
    return arn


class EventSyncService:
    """Polls SQS queues for CloudTrail events and updates the resource DB."""

    POLL_INTERVAL = 30  # seconds between poll cycles
    BATCH_SIZE = 10  # SQS max per receive
    VISIBILITY_TIMEOUT = 60  # seconds before retry
    LONG_POLL_WAIT = 5  # seconds (short long-poll to avoid blocking)

    def __init__(self, db_session_factory):
        """Initialise with a callable that returns a DB session context manager.

        Args:
            db_session_factory: legacy argument kept for compatibility.
        """
        self._db_factory = db_session_factory
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._paused = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        return self._running and self._thread is not None and self._thread.is_alive()

    @property
    def is_paused(self) -> bool:
        return self._paused

    def start(self):
        """Start the background polling thread."""
        if self.is_running:
            logger.warning("EventSyncService already running")
            return

        self._running = True
        self._paused = False
        self._thread = threading.Thread(
            target=self._poll_loop, name="event-sync", daemon=True
        )
        self._thread.start()
        logger.info("EventSyncService started")

    def stop(self):
        """Stop the background polling thread."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=self.POLL_INTERVAL + 5)
        self._thread = None
        logger.info("EventSyncService stopped")

    def pause(self):
        """Pause polling (events queue up in SQS)."""
        self._paused = True
        logger.info("EventSyncService paused")

    def resume(self):
        """Resume polling after pause."""
        self._paused = False
        logger.info("EventSyncService resumed")

    # ------------------------------------------------------------------
    # Core polling loop
    # ------------------------------------------------------------------

    def _poll_loop(self):
        """Run in background thread: poll all queues in a loop."""
        while self._running:
            if not self._paused:
                try:
                    processed = self.poll_all_queues()
                    if processed > 0:
                        logger.info("Event sync: processed %d events", processed)
                except Exception:
                    logger.exception("Event sync poll error")
            time.sleep(self.POLL_INTERVAL)

    def poll_all_queues(self) -> int:
        """Delegate queue polling to bluearch-core. Returns total processed."""
        result = request_core(
            "POST",
            "/api/v1/event-tracking/poll",
            service_token=True,
            json={
                "max_messages": self.BATCH_SIZE,
                "wait_time_seconds": self.LONG_POLL_WAIT,
                "visibility_timeout": self.VISIBILITY_TIMEOUT,
            },
            timeout=30.0,
        )
        return int(result.get("processed", result.get("messages_processed", 0)) or 0)

    def _poll_queue(self, db, queue_config: Any) -> int:
        """Legacy local poll path retained only for API compatibility."""
        raise RuntimeError("Event queue polling is owned by bluearch-core")

    # ------------------------------------------------------------------
    # Event normalisation (EventBridge -> SQS direct, no Lambda)
    # ------------------------------------------------------------------

    def _extract_event(self, body: dict) -> Optional[dict]:
        """Normalise a raw EventBridge/CloudTrail event into our standard format.

        Since we bypass Lambda and send EventBridge events directly to SQS,
        the body is the full EventBridge event envelope.  We extract the
        CloudTrail detail and normalise it inline (same logic as
        ``lambda/event_processor.py``).
        """
        detail = body.get("detail", {})
        if not detail:
            # Maybe the body itself is already a normalised event (from Lambda path)
            if "action" in body and "resource_arn" in body:
                return body
            return None

        ep = _get_event_processor()
        if ep is None:
            logger.warning("event_processor module not available, cannot normalise")
            return None

        event_name = detail.get("eventName", "")
        action = ep.ACTION_MAP.get(event_name)
        if not action:
            return None

        # Skip failed API calls
        if detail.get("errorCode"):
            return None

        arns = ep.extract_arns(detail)
        if not arns:
            return None

        source = body.get("source", "").replace("aws.", "")
        region = detail.get("awsRegion", "")
        account_id = detail.get("recipientAccountId", "")
        principal = detail.get("userIdentity", {}).get("arn", "")
        event_time = detail.get("eventTime", "")
        tags = ep.extract_tags(detail) if action == "tag" else None
        resource_type = _resource_type_for_event(source, event_name)
        metadata = (
            _extract_metadata(resource_type, detail) if action == "create" else None
        )

        return {
            "action": action,
            "resource_arn": arns[0],
            "service_name": source,
            "event_name": event_name,
            "resource_type": resource_type,
            "region": region,
            "account_id": account_id,
            "principal": principal,
            "event_time": event_time,
            "tags": tags,
            "metadata": metadata,
            "extra_arns": arns[1:] if len(arns) > 1 else [],
        }

    # ------------------------------------------------------------------
    # DB operations
    # ------------------------------------------------------------------

    def _process_event(self, db, event: dict):
        """Legacy local DB mutation path retained only for API compatibility."""
        raise RuntimeError("Event resource mutation is owned by bluearch-core")

    def _handle_create(self, db, arn: str, event: dict):
        """Legacy local create handler retained only for API compatibility."""
        raise RuntimeError("Event resource creation is owned by bluearch-core")

    def _handle_delete(self, db, arn: str):
        """Legacy local delete handler retained only for API compatibility."""
        raise RuntimeError("Event resource deletion is owned by bluearch-core")

    def _handle_tag(self, db, arn: str, event: dict):
        """Legacy local tag handler retained only for API compatibility."""
        raise RuntimeError("Event resource tag mutation is owned by bluearch-core")

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def get_status(self) -> dict:
        """Return current service status for API consumers."""
        status = request_core("GET", "/api/v1/event-tracking/status", timeout=10.0)
        return {
            "running": self.is_running,
            "paused": self.is_paused,
            "total_queues": status.get("total_queues", 0),
            "active_queues": status.get("active_queues", 0),
            "paused_queues": sum(1 for item in status.get("instances", []) if item.get("status") == "paused"),
        }


# ---------------------------------------------------------------------------
# Module-level singleton (initialised lazily by the web app)
# ---------------------------------------------------------------------------

_event_sync_service: Optional[EventSyncService] = None


def get_event_sync_service() -> Optional[EventSyncService]:
    """Return the singleton EventSyncService, or None if not initialised."""
    return _event_sync_service


def init_event_sync_service(db_session_factory) -> EventSyncService:
    """Create and return the singleton EventSyncService."""
    global _event_sync_service
    _event_sync_service = EventSyncService(db_session_factory)
    return _event_sync_service
