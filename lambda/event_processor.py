"""BlueArch Tag Manager - CloudTrail Event Processor Lambda.

Receives CloudTrail events via EventBridge, normalises them into resource
change messages, and writes to SQS for the Tag Manager app to consume.

Deployed once per account-region pair via the EventTracking StackSet.
"""

import json
import os
import logging

import boto3

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

SQS_QUEUE_URL = os.environ["SQS_QUEUE_URL"]
sqs = boto3.client("sqs")

# ---------------------------------------------------------------------------
# CloudTrail eventName -> normalised action type
# ---------------------------------------------------------------------------

ACTION_MAP = {
    # --- Creates ---
    "RunInstances": "create",
    "CreateVolume": "create",
    "CreateSnapshot": "create",
    "RegisterImage": "create",
    "AllocateAddress": "create",
    "CreateBucket": "create",
    "CreateFunction20150331": "create",
    "CreateDBInstance": "create",
    "CreateDBCluster": "create",
    "CreateTable": "create",
    "CreateCluster": "create",
    "CreateService": "create",
    "RegisterTaskDefinition": "create",
    "CreateLoadBalancer": "create",
    "CreateTargetGroup": "create",
    "CreateTopic": "create",
    "CreateQueue": "create",
    "PutMetricAlarm": "create",
    "CreateNodegroup": "create",
    "CreateCacheCluster": "create",
    "CreateReplicationGroup": "create",
    # --- Deletes ---
    "TerminateInstances": "delete",
    "DeleteVolume": "delete",
    "DeleteSnapshot": "delete",
    "DeregisterImage": "delete",
    "ReleaseAddress": "delete",
    "DeleteBucket": "delete",
    "DeleteFunction20150331": "delete",
    "DeleteDBInstance": "delete",
    "DeleteDBCluster": "delete",
    "DeleteTable": "delete",
    "DeleteCluster": "delete",
    "DeleteService": "delete",
    "DeregisterTaskDefinition": "delete",
    "DeleteLoadBalancer": "delete",
    "DeleteTargetGroup": "delete",
    "DeleteTopic": "delete",
    "DeleteQueue": "delete",
    "DeleteAlarms": "delete",
    "DeleteNodegroup": "delete",
    "DeleteCacheCluster": "delete",
    "DeleteReplicationGroup": "delete",
    # --- Tag changes ---
    # EC2
    "CreateTags": "tag",
    "DeleteTags": "tag",
    # S3
    "PutBucketTagging": "tag",
    "DeleteBucketTagging": "tag",
    # Lambda
    "TagResource20170331v2": "tag",
    "UntagResource20170331v2": "tag",
    # RDS / ElastiCache
    "AddTagsToResource": "tag",
    "RemoveTagsFromResource": "tag",
    # ELB
    "AddTags": "tag",
    "RemoveTags": "tag",
    # SQS
    "TagQueue": "tag",
    "UntagQueue": "tag",
    # Generic (DynamoDB, ECS, SNS, CloudWatch, EKS)
    "TagResource": "tag",
    "UntagResource": "tag",
}


def extract_arns(detail):
    """Best-effort ARN extraction from a CloudTrail event detail block."""
    arns = []

    # 1. Try the ``resources`` array first -- most reliable when present.
    for r in detail.get("resources", []):
        arn = r.get("ARN") or r.get("arn")
        if arn:
            arns.append(arn)
    if arns:
        return arns

    # 2. Fallback: parse from responseElements / requestParameters.
    resp = detail.get("responseElements") or {}
    req = detail.get("requestParameters") or {}
    region = detail.get("awsRegion", "")
    account = detail.get("recipientAccountId", "")

    # EC2 instances from RunInstances
    instances_set = resp.get("instancesSet") or {}
    for item in instances_set.get("items", []):
        iid = item.get("instanceId")
        if iid:
            arns.append(f"arn:aws:ec2:{region}:{account}:instance/{iid}")

    # EC2 volumes
    volume_id = resp.get("volumeId") or req.get("volumeId")
    if volume_id:
        arns.append(f"arn:aws:ec2:{region}:{account}:volume/{volume_id}")

    # EC2 snapshots
    snapshot_id = resp.get("snapshotId") or req.get("snapshotId")
    if snapshot_id:
        arns.append(f"arn:aws:ec2:{region}:{account}:snapshot/{snapshot_id}")

    # EC2 AMIs
    image_id = resp.get("imageId") or req.get("imageId")
    if image_id:
        arns.append(f"arn:aws:ec2:{region}:{account}:image/{image_id}")

    # EC2 EIPs
    allocation_id = resp.get("allocationId") or req.get("allocationId")
    if allocation_id:
        arns.append(
            f"arn:aws:ec2:{region}:{account}:elastic-ip/{allocation_id}"
        )

    # S3 buckets
    bucket = req.get("bucketName")
    if bucket:
        arns.append(f"arn:aws:s3:::{bucket}")

    # Generic ARN fields found across many services
    for key in (
        "functionArn",
        "topicArn",
        "tableArn",
        "clusterArn",
        "serviceArn",
        "taskDefinitionArn",
        "loadBalancerArn",
        "targetGroupArn",
        "nodeGroupArn",
        "queueUrl",
    ):
        val = resp.get(key) or req.get(key)
        if val:
            # queueUrl is not an ARN but can be converted
            if key == "queueUrl" and val.startswith("https://"):
                # https://sqs.REGION.amazonaws.com/ACCT/NAME -> arn
                parts = val.replace("https://", "").split("/")
                if len(parts) >= 3:
                    queue_region = parts[0].split(".")[1] if "." in parts[0] else region
                    queue_account = parts[1]
                    queue_name = parts[2]
                    arns.append(
                        f"arn:aws:sqs:{queue_region}:{queue_account}:{queue_name}"
                    )
            else:
                arns.append(val)

    # ElastiCache -- uses IDs rather than ARNs in responses
    for id_key, svc_type in (
        ("cacheClusterId", "cluster"),
        ("replicationGroupId", "replicationgroup"),
    ):
        val = resp.get(id_key) or req.get(id_key)
        if val and not val.startswith("arn:"):
            arns.append(
                f"arn:aws:elasticache:{region}:{account}:{svc_type}:{val}"
            )

    # EC2 CreateTags / DeleteTags -- resourcesSet in request
    resources_set = req.get("resourcesSet") or {}
    for item in resources_set.get("items", []):
        resource_id = item.get("resourceId")
        if resource_id:
            rtype = _ec2_id_to_type(resource_id)
            if rtype:
                arns.append(f"arn:aws:ec2:{region}:{account}:{rtype}/{resource_id}")

    return arns


def _ec2_id_to_type(resource_id):
    """Map an EC2 resource ID prefix to its ARN type component."""
    prefixes = {
        "i-": "instance",
        "vol-": "volume",
        "snap-": "snapshot",
        "ami-": "image",
        "eipalloc-": "elastic-ip",
        "sg-": "security-group",
        "eni-": "network-interface",
        "subnet-": "subnet",
        "vpc-": "vpc",
        "igw-": "internet-gateway",
        "rtb-": "route-table",
        "nat-": "natgateway",
    }
    for prefix, rtype in prefixes.items():
        if resource_id.startswith(prefix):
            return rtype
    return None


def extract_tags(detail):
    """Extract tags from CloudTrail request parameters."""
    tags = {}
    req = detail.get("requestParameters") or {}
    for field in ("tagSet", "tags", "tagList", "addOrUpdateTags", "tagSpecificationSet"):
        data = req.get(field)
        if data is None:
            continue

        # tagSet / tagSpecificationSet can be {"items": [...]}
        if isinstance(data, dict) and "items" in data:
            for item in data["items"]:
                # tagSpecificationSet items contain nested tags
                if "tags" in item:
                    for t in item["tags"]:
                        k = t.get("key", t.get("Key", ""))
                        v = t.get("value", t.get("Value", ""))
                        if k:
                            tags[k] = v
                else:
                    k = item.get("key", item.get("Key", ""))
                    v = item.get("value", item.get("Value", ""))
                    if k:
                        tags[k] = v

        elif isinstance(data, list):
            for t in data:
                k = t.get("Key", t.get("key", ""))
                v = t.get("Value", t.get("value", ""))
                if k:
                    tags[k] = v

    return tags


def handler(event, context):
    """Lambda entry point -- invoked by EventBridge for each matched event."""
    detail = event.get("detail", {})
    event_name = detail.get("eventName", "")
    action = ACTION_MAP.get(event_name)

    if not action:
        logger.debug("Ignoring unmapped event: %s", event_name)
        return

    # Skip failed API calls
    error_code = detail.get("errorCode")
    if error_code:
        logger.debug("Ignoring failed API call %s: %s", event_name, error_code)
        return

    arns = extract_arns(detail)
    if not arns:
        logger.warning("Could not extract ARN from event: %s", event_name)
        return

    source = event.get("source", "").replace("aws.", "")
    region = detail.get("awsRegion", "")
    account_id = detail.get("recipientAccountId", "")
    principal = detail.get("userIdentity", {}).get("arn", "")
    event_time = detail.get("eventTime", "")
    tags = extract_tags(detail) if action == "tag" else None

    entries = []
    for arn in arns:
        message = {
            "action": action,
            "resource_arn": arn,
            "service_name": source,
            "region": region,
            "account_id": account_id,
            "event_name": event_name,
            "event_time": event_time,
            "principal": principal,
        }
        if tags is not None:
            message["tags"] = tags

        entries.append({"MessageBody": json.dumps(message)})

    # Send in batches of 10 (SQS limit)
    for i in range(0, len(entries), 10):
        batch = entries[i : i + 10]
        for idx, entry in enumerate(batch):
            entry["Id"] = str(idx)
        resp = sqs.send_message_batch(QueueUrl=SQS_QUEUE_URL, Entries=batch)
        failed = resp.get("Failed", [])
        if failed:
            logger.error("Failed to send %d messages: %s", len(failed), failed)

    logger.info(
        "Processed %s: %d ARN(s), action=%s, account=%s, region=%s",
        event_name,
        len(arns),
        action,
        account_id,
        region,
    )
