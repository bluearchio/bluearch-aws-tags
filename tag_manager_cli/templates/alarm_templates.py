"""Built-in CloudWatch alarm templates for common AWS services.

Provides pre-configured alarm templates for EC2, RDS, Lambda, and other services
with sensible defaults that can be customized.
"""

from typing import Any, Dict, List, Optional

# Template structure:
# Each template defines the CloudWatch alarm parameters with sensible defaults.
# Templates can be customized when creating alarms.

ALARM_TEMPLATES: Dict[str, Dict[str, Dict[str, Any]]] = {
    "ec2": {
        "cpu_high": {
            "display_name": "High CPU Utilization",
            "description": "Alarm when CPU exceeds threshold for extended period",
            "metric_name": "CPUUtilization",
            "namespace": "AWS/EC2",
            "statistic": "Average",
            "period": 300,  # 5 minutes
            "evaluation_periods": 2,
            "threshold": 80,
            "comparison_operator": "GreaterThanThreshold",
            "treat_missing_data": "missing",
            "dimension_key": "InstanceId",
            "unit": "Percent",
        },
        "cpu_critical": {
            "display_name": "Critical CPU Utilization",
            "description": "Alarm when CPU is critically high",
            "metric_name": "CPUUtilization",
            "namespace": "AWS/EC2",
            "statistic": "Average",
            "period": 300,
            "evaluation_periods": 2,
            "threshold": 95,
            "comparison_operator": "GreaterThanThreshold",
            "treat_missing_data": "missing",
            "dimension_key": "InstanceId",
            "unit": "Percent",
        },
        "status_check_failed": {
            "display_name": "Status Check Failed",
            "description": "Alarm when instance or system status check fails",
            "metric_name": "StatusCheckFailed",
            "namespace": "AWS/EC2",
            "statistic": "Maximum",
            "period": 60,  # 1 minute
            "evaluation_periods": 2,
            "threshold": 1,
            "comparison_operator": "GreaterThanOrEqualToThreshold",
            "treat_missing_data": "breaching",
            "dimension_key": "InstanceId",
            "unit": "Count",
        },
        "network_in_high": {
            "display_name": "High Network In",
            "description": "Alarm when inbound network traffic is high",
            "metric_name": "NetworkIn",
            "namespace": "AWS/EC2",
            "statistic": "Average",
            "period": 300,
            "evaluation_periods": 3,
            "threshold": 1000000000,  # 1 GB
            "comparison_operator": "GreaterThanThreshold",
            "treat_missing_data": "missing",
            "dimension_key": "InstanceId",
            "unit": "Bytes",
        },
        "network_out_high": {
            "display_name": "High Network Out",
            "description": "Alarm when outbound network traffic is high",
            "metric_name": "NetworkOut",
            "namespace": "AWS/EC2",
            "statistic": "Average",
            "period": 300,
            "evaluation_periods": 3,
            "threshold": 1000000000,  # 1 GB
            "comparison_operator": "GreaterThanThreshold",
            "treat_missing_data": "missing",
            "dimension_key": "InstanceId",
            "unit": "Bytes",
        },
    },
    "rds": {
        "cpu_high": {
            "display_name": "High CPU Utilization",
            "description": "Alarm when RDS CPU exceeds threshold",
            "metric_name": "CPUUtilization",
            "namespace": "AWS/RDS",
            "statistic": "Average",
            "period": 300,
            "evaluation_periods": 2,
            "threshold": 80,
            "comparison_operator": "GreaterThanThreshold",
            "treat_missing_data": "missing",
            "dimension_key": "DBInstanceIdentifier",
            "unit": "Percent",
        },
        "free_storage_low": {
            "display_name": "Low Free Storage Space",
            "description": "Alarm when free storage space is low",
            "metric_name": "FreeStorageSpace",
            "namespace": "AWS/RDS",
            "statistic": "Average",
            "period": 300,
            "evaluation_periods": 2,
            "threshold": 10737418240,  # 10 GB in bytes
            "comparison_operator": "LessThanThreshold",
            "treat_missing_data": "missing",
            "dimension_key": "DBInstanceIdentifier",
            "unit": "Bytes",
        },
        "free_storage_critical": {
            "display_name": "Critical Free Storage Space",
            "description": "Alarm when free storage space is critically low",
            "metric_name": "FreeStorageSpace",
            "namespace": "AWS/RDS",
            "statistic": "Average",
            "period": 300,
            "evaluation_periods": 1,
            "threshold": 5368709120,  # 5 GB in bytes
            "comparison_operator": "LessThanThreshold",
            "treat_missing_data": "breaching",
            "dimension_key": "DBInstanceIdentifier",
            "unit": "Bytes",
        },
        "connections_high": {
            "display_name": "High Database Connections",
            "description": "Alarm when database connections are high",
            "metric_name": "DatabaseConnections",
            "namespace": "AWS/RDS",
            "statistic": "Average",
            "period": 300,
            "evaluation_periods": 2,
            "threshold": 100,
            "comparison_operator": "GreaterThanThreshold",
            "treat_missing_data": "missing",
            "dimension_key": "DBInstanceIdentifier",
            "unit": "Count",
        },
        "freeable_memory_low": {
            "display_name": "Low Freeable Memory",
            "description": "Alarm when freeable memory is low",
            "metric_name": "FreeableMemory",
            "namespace": "AWS/RDS",
            "statistic": "Average",
            "period": 300,
            "evaluation_periods": 2,
            "threshold": 268435456,  # 256 MB in bytes
            "comparison_operator": "LessThanThreshold",
            "treat_missing_data": "missing",
            "dimension_key": "DBInstanceIdentifier",
            "unit": "Bytes",
        },
        "read_latency_high": {
            "display_name": "High Read Latency",
            "description": "Alarm when read latency is high",
            "metric_name": "ReadLatency",
            "namespace": "AWS/RDS",
            "statistic": "Average",
            "period": 300,
            "evaluation_periods": 2,
            "threshold": 0.02,  # 20ms
            "comparison_operator": "GreaterThanThreshold",
            "treat_missing_data": "missing",
            "dimension_key": "DBInstanceIdentifier",
            "unit": "Seconds",
        },
        "write_latency_high": {
            "display_name": "High Write Latency",
            "description": "Alarm when write latency is high",
            "metric_name": "WriteLatency",
            "namespace": "AWS/RDS",
            "statistic": "Average",
            "period": 300,
            "evaluation_periods": 2,
            "threshold": 0.02,  # 20ms
            "comparison_operator": "GreaterThanThreshold",
            "treat_missing_data": "missing",
            "dimension_key": "DBInstanceIdentifier",
            "unit": "Seconds",
        },
    },
    "lambda": {
        "errors": {
            "display_name": "Lambda Errors",
            "description": "Alarm when Lambda function has errors",
            "metric_name": "Errors",
            "namespace": "AWS/Lambda",
            "statistic": "Sum",
            "period": 300,
            "evaluation_periods": 1,
            "threshold": 1,
            "comparison_operator": "GreaterThanOrEqualToThreshold",
            "treat_missing_data": "notBreaching",
            "dimension_key": "FunctionName",
            "unit": "Count",
        },
        "errors_rate": {
            "display_name": "Lambda Error Rate",
            "description": "Alarm when Lambda error rate exceeds threshold",
            "metric_name": "Errors",
            "namespace": "AWS/Lambda",
            "statistic": "Average",
            "period": 300,
            "evaluation_periods": 2,
            "threshold": 0.05,  # 5% error rate
            "comparison_operator": "GreaterThanThreshold",
            "treat_missing_data": "notBreaching",
            "dimension_key": "FunctionName",
            "unit": "Count",
        },
        "duration_high": {
            "display_name": "High Duration",
            "description": "Alarm when Lambda duration approaches timeout",
            "metric_name": "Duration",
            "namespace": "AWS/Lambda",
            "statistic": "Average",
            "period": 300,
            "evaluation_periods": 2,
            "threshold": 10000,  # 10 seconds in ms
            "comparison_operator": "GreaterThanThreshold",
            "treat_missing_data": "missing",
            "dimension_key": "FunctionName",
            "unit": "Milliseconds",
        },
        "throttles": {
            "display_name": "Lambda Throttles",
            "description": "Alarm when Lambda function is being throttled",
            "metric_name": "Throttles",
            "namespace": "AWS/Lambda",
            "statistic": "Sum",
            "period": 300,
            "evaluation_periods": 1,
            "threshold": 1,
            "comparison_operator": "GreaterThanOrEqualToThreshold",
            "treat_missing_data": "notBreaching",
            "dimension_key": "FunctionName",
            "unit": "Count",
        },
        "concurrent_executions_high": {
            "display_name": "High Concurrent Executions",
            "description": "Alarm when concurrent executions are high",
            "metric_name": "ConcurrentExecutions",
            "namespace": "AWS/Lambda",
            "statistic": "Maximum",
            "period": 60,
            "evaluation_periods": 5,
            "threshold": 900,  # Approaching default limit of 1000
            "comparison_operator": "GreaterThanThreshold",
            "treat_missing_data": "missing",
            "dimension_key": "FunctionName",
            "unit": "Count",
        },
    },
    "sqs": {
        "queue_depth_high": {
            "display_name": "High Queue Depth",
            "description": "Alarm when SQS queue has many messages",
            "metric_name": "ApproximateNumberOfMessagesVisible",
            "namespace": "AWS/SQS",
            "statistic": "Average",
            "period": 300,
            "evaluation_periods": 2,
            "threshold": 1000,
            "comparison_operator": "GreaterThanThreshold",
            "treat_missing_data": "missing",
            "dimension_key": "QueueName",
            "unit": "Count",
        },
        "oldest_message_age": {
            "display_name": "Old Messages in Queue",
            "description": "Alarm when messages are waiting too long",
            "metric_name": "ApproximateAgeOfOldestMessage",
            "namespace": "AWS/SQS",
            "statistic": "Maximum",
            "period": 300,
            "evaluation_periods": 2,
            "threshold": 3600,  # 1 hour in seconds
            "comparison_operator": "GreaterThanThreshold",
            "treat_missing_data": "missing",
            "dimension_key": "QueueName",
            "unit": "Seconds",
        },
        "dlq_messages": {
            "display_name": "Messages in DLQ",
            "description": "Alarm when dead letter queue has messages",
            "metric_name": "ApproximateNumberOfMessagesVisible",
            "namespace": "AWS/SQS",
            "statistic": "Sum",
            "period": 300,
            "evaluation_periods": 1,
            "threshold": 1,
            "comparison_operator": "GreaterThanOrEqualToThreshold",
            "treat_missing_data": "notBreaching",
            "dimension_key": "QueueName",
            "unit": "Count",
        },
    },
    "dynamodb": {
        "read_throttled": {
            "display_name": "Read Throttled",
            "description": "Alarm when read requests are being throttled",
            "metric_name": "ReadThrottledEvents",
            "namespace": "AWS/DynamoDB",
            "statistic": "Sum",
            "period": 300,
            "evaluation_periods": 1,
            "threshold": 1,
            "comparison_operator": "GreaterThanOrEqualToThreshold",
            "treat_missing_data": "notBreaching",
            "dimension_key": "TableName",
            "unit": "Count",
        },
        "write_throttled": {
            "display_name": "Write Throttled",
            "description": "Alarm when write requests are being throttled",
            "metric_name": "WriteThrottledEvents",
            "namespace": "AWS/DynamoDB",
            "statistic": "Sum",
            "period": 300,
            "evaluation_periods": 1,
            "threshold": 1,
            "comparison_operator": "GreaterThanOrEqualToThreshold",
            "treat_missing_data": "notBreaching",
            "dimension_key": "TableName",
            "unit": "Count",
        },
        "consumed_read_capacity_high": {
            "display_name": "High Read Capacity Usage",
            "description": "Alarm when consumed read capacity is high",
            "metric_name": "ConsumedReadCapacityUnits",
            "namespace": "AWS/DynamoDB",
            "statistic": "Sum",
            "period": 300,
            "evaluation_periods": 2,
            "threshold": 100,
            "comparison_operator": "GreaterThanThreshold",
            "treat_missing_data": "missing",
            "dimension_key": "TableName",
            "unit": "Count",
        },
        "consumed_write_capacity_high": {
            "display_name": "High Write Capacity Usage",
            "description": "Alarm when consumed write capacity is high",
            "metric_name": "ConsumedWriteCapacityUnits",
            "namespace": "AWS/DynamoDB",
            "statistic": "Sum",
            "period": 300,
            "evaluation_periods": 2,
            "threshold": 100,
            "comparison_operator": "GreaterThanThreshold",
            "treat_missing_data": "missing",
            "dimension_key": "TableName",
            "unit": "Count",
        },
    },
    "elb": {
        "unhealthy_hosts": {
            "display_name": "Unhealthy Hosts",
            "description": "Alarm when targets are unhealthy",
            "metric_name": "UnHealthyHostCount",
            "namespace": "AWS/ApplicationELB",
            "statistic": "Average",
            "period": 300,
            "evaluation_periods": 2,
            "threshold": 1,
            "comparison_operator": "GreaterThanOrEqualToThreshold",
            "treat_missing_data": "notBreaching",
            "dimension_key": "TargetGroup",
            "unit": "Count",
        },
        "target_response_time_high": {
            "display_name": "High Target Response Time",
            "description": "Alarm when target response time is high",
            "metric_name": "TargetResponseTime",
            "namespace": "AWS/ApplicationELB",
            "statistic": "Average",
            "period": 300,
            "evaluation_periods": 2,
            "threshold": 5,  # 5 seconds
            "comparison_operator": "GreaterThanThreshold",
            "treat_missing_data": "missing",
            "dimension_key": "LoadBalancer",
            "unit": "Seconds",
        },
        "5xx_errors": {
            "display_name": "5XX Errors",
            "description": "Alarm when 5XX errors are occurring",
            "metric_name": "HTTPCode_ELB_5XX_Count",
            "namespace": "AWS/ApplicationELB",
            "statistic": "Sum",
            "period": 300,
            "evaluation_periods": 1,
            "threshold": 10,
            "comparison_operator": "GreaterThanThreshold",
            "treat_missing_data": "notBreaching",
            "dimension_key": "LoadBalancer",
            "unit": "Count",
        },
    },
    "s3": {
        "4xx_errors": {
            "display_name": "4XX Errors",
            "description": "Alarm when S3 4XX errors are high",
            "metric_name": "4xxErrors",
            "namespace": "AWS/S3",
            "statistic": "Sum",
            "period": 300,
            "evaluation_periods": 2,
            "threshold": 100,
            "comparison_operator": "GreaterThanThreshold",
            "treat_missing_data": "notBreaching",
            "dimension_key": "BucketName",
            "unit": "Count",
        },
        "5xx_errors": {
            "display_name": "5XX Errors",
            "description": "Alarm when S3 5XX errors are occurring",
            "metric_name": "5xxErrors",
            "namespace": "AWS/S3",
            "statistic": "Sum",
            "period": 300,
            "evaluation_periods": 1,
            "threshold": 1,
            "comparison_operator": "GreaterThanOrEqualToThreshold",
            "treat_missing_data": "notBreaching",
            "dimension_key": "BucketName",
            "unit": "Count",
        },
    },
}

# Service to resource type mapping for ARN parsing
SERVICE_RESOURCE_TYPES = {
    "ec2": ["instance"],
    "rds": ["db"],
    "lambda": ["function"],
    "sqs": ["queue"],
    "dynamodb": ["table"],
    "elasticloadbalancing": ["loadbalancer", "targetgroup"],
    "s3": ["bucket"],
}


def get_available_services() -> List[str]:
    """Get list of services with alarm templates."""
    return list(ALARM_TEMPLATES.keys())


def get_templates_for_service(service: str) -> Dict[str, Dict[str, Any]]:
    """Get all alarm templates for a specific service.

    Args:
        service: Service name (e.g., 'ec2', 'rds', 'lambda')

    Returns:
        Dictionary of template_name -> template_config
    """
    service_lower = service.lower()
    return ALARM_TEMPLATES.get(service_lower, {})


def get_template(service: str, template_name: str) -> Optional[Dict[str, Any]]:
    """Get a specific alarm template.

    Args:
        service: Service name (e.g., 'ec2', 'rds')
        template_name: Template name (e.g., 'cpu_high', 'errors')

    Returns:
        Template configuration dict or None if not found
    """
    service_templates = get_templates_for_service(service)
    return service_templates.get(template_name)


def get_all_templates() -> Dict[str, Dict[str, Dict[str, Any]]]:
    """Get all alarm templates organized by service."""
    return ALARM_TEMPLATES.copy()


def get_template_summary() -> List[Dict[str, Any]]:
    """Get a summary of all available templates for display.

    Returns:
        List of dicts with service, template_name, display_name, description
    """
    summary = []
    for service, templates in ALARM_TEMPLATES.items():
        for template_name, config in templates.items():
            summary.append({
                "service": service,
                "template_name": template_name,
                "display_name": config.get("display_name", template_name),
                "description": config.get("description", ""),
                "metric_name": config.get("metric_name", ""),
                "threshold": config.get("threshold", ""),
                "unit": config.get("unit", ""),
            })
    return summary


def suggest_templates_for_service(service: str) -> List[Dict[str, Any]]:
    """Suggest alarm templates for a given AWS service.

    Args:
        service: Service name or partial match (e.g., 'ec2', 'rds', 'elasticloadbalancing')

    Returns:
        List of suggested templates with full configuration
    """
    service_lower = service.lower()

    # Handle service name variations
    service_mapping = {
        "ec2": "ec2",
        "instance": "ec2",
        "rds": "rds",
        "database": "rds",
        "lambda": "lambda",
        "function": "lambda",
        "sqs": "sqs",
        "queue": "sqs",
        "dynamodb": "dynamodb",
        "dynamo": "dynamodb",
        "table": "dynamodb",
        "elb": "elb",
        "elasticloadbalancing": "elb",
        "loadbalancer": "elb",
        "alb": "elb",
        "s3": "s3",
        "bucket": "s3",
    }

    mapped_service = service_mapping.get(service_lower, service_lower)
    templates = get_templates_for_service(mapped_service)

    suggestions = []
    for template_name, config in templates.items():
        suggestions.append({
            "service": mapped_service,
            "template_name": template_name,
            **config
        })

    return suggestions


def build_alarm_name(
    resource_id: str,
    template_name: str,
    prefix: str = "tag-manager"
) -> str:
    """Build a standardized alarm name.

    Args:
        resource_id: The resource identifier (e.g., instance ID, function name)
        template_name: The template name being used
        prefix: Prefix for the alarm name

    Returns:
        Formatted alarm name like 'tag-manager-i-1234567890-cpu-high'
    """
    # Clean resource ID (remove any ARN prefix if present)
    clean_id = resource_id.split("/")[-1].split(":")[-1]

    # Build alarm name
    alarm_name = f"{prefix}-{clean_id}-{template_name}".replace("_", "-")

    # Ensure name doesn't exceed CloudWatch limit (255 chars)
    if len(alarm_name) > 255:
        alarm_name = alarm_name[:255]

    return alarm_name


def extract_service_from_arn(arn: str) -> Optional[str]:
    """Extract the service name from an AWS ARN.

    Args:
        arn: AWS ARN string

    Returns:
        Service name or None if cannot be determined
    """
    if not arn or not arn.startswith("arn:"):
        return None

    parts = arn.split(":")
    if len(parts) < 3:
        return None

    service = parts[2]

    # Map AWS service names to our template service names
    service_mapping = {
        "ec2": "ec2",
        "rds": "rds",
        "lambda": "lambda",
        "sqs": "sqs",
        "dynamodb": "dynamodb",
        "elasticloadbalancing": "elb",
        "s3": "s3",
    }

    return service_mapping.get(service)


def extract_resource_id_from_arn(arn: str) -> Optional[str]:
    """Extract the resource ID from an AWS ARN.

    Args:
        arn: AWS ARN string

    Returns:
        Resource ID or None if cannot be determined
    """
    if not arn or not arn.startswith("arn:"):
        return None

    parts = arn.split(":")
    if len(parts) < 6:
        return None

    # Resource part is typically the last segment
    resource_part = parts[-1]

    # Handle different ARN formats
    if "/" in resource_part:
        # Format: resource-type/resource-id
        return resource_part.split("/")[-1]
    else:
        # Format: resource-id directly
        return resource_part
