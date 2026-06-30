"""AWS resource types that support tag policy enforcement.

This module provides definitions of AWS resource types that can be used
in tag policy enforcement rules.

Reference: https://docs.aws.amazon.com/organizations/latest/userguide/orgs_manage_policies_supported-resources-enforcement.html
"""

# Common AWS resource types grouped by service
RESOURCE_TYPES = {
    "EC2": [
        "ec2:instance",
        "ec2:volume",
        "ec2:snapshot",
        "ec2:security-group",
        "ec2:network-interface",
        "ec2:elastic-ip",
        "ec2:vpc",
        "ec2:subnet",
        "ec2:route-table",
        "ec2:internet-gateway",
        "ec2:nat-gateway",
        "ec2:image",
        "ec2:*",  # All EC2 resources
    ],
    "S3": [
        "s3:bucket",
        "s3:*",  # All S3 resources
    ],
    "RDS": [
        "rds:db",
        "rds:cluster",
        "rds:snapshot",
        "rds:cluster-snapshot",
        "rds:*",  # All RDS resources
    ],
    "Lambda": [
        "lambda:function",
        "lambda:*",  # All Lambda resources
    ],
    "DynamoDB": [
        "dynamodb:table",
        "dynamodb:*",  # All DynamoDB resources
    ],
    "ECS": [
        "ecs:cluster",
        "ecs:service",
        "ecs:task",
        "ecs:task-definition",
        "ecs:*",  # All ECS resources
    ],
    "EKS": [
        "eks:cluster",
        "eks:nodegroup",
        "eks:*",  # All EKS resources
    ],
    "ELB": [
        "elasticloadbalancing:loadbalancer",
        "elasticloadbalancing:targetgroup",
        "elasticloadbalancing:*",  # All ELB resources
    ],
    "CloudFormation": [
        "cloudformation:stack",
        "cloudformation:stackset",
        "cloudformation:*",  # All CloudFormation resources
    ],
    "IAM": [
        "iam:role",
        "iam:user",
        "iam:policy",
        "iam:*",  # All IAM resources
    ],
    "Secrets Manager": [
        "secretsmanager:secret",
        "secretsmanager:*",  # All Secrets Manager resources
    ],
    "Systems Manager": [
        "ssm:parameter",
        "ssm:document",
        "ssm:*",  # All Systems Manager resources
    ],
    "KMS": [
        "kms:key",
        "kms:alias",
        "kms:*",  # All KMS resources
    ],
    "CloudWatch": [
        "logs:log-group",
        "cloudwatch:alarm",
        "cloudwatch:*",  # All CloudWatch resources
    ],
    "SNS": [
        "sns:topic",
        "sns:*",  # All SNS resources
    ],
    "SQS": [
        "sqs:queue",
        "sqs:*",  # All SQS resources
    ],
    "ElastiCache": [
        "elasticache:cluster",
        "elasticache:snapshot",
        "elasticache:*",  # All ElastiCache resources
    ],
    "Backup": [
        "backup:backup-plan",
        "backup:backup-vault",
        "backup:*",  # All Backup resources
    ],
    "EFS": [
        "elasticfilesystem:file-system",
        "elasticfilesystem:access-point",
        "elasticfilesystem:*",  # All EFS resources
    ],
    "Glue": [
        "glue:database",
        "glue:table",
        "glue:crawler",
        "glue:*",  # All Glue resources
    ],
    "Step Functions": [
        "states:stateMachine",
        "states:activity",
        "states:*",  # All Step Functions resources
    ],
}


def get_all_resource_types():
    """Get a flat list of all resource types.

    Returns:
        List of all resource types across all services
    """
    all_types = []
    for service_types in RESOURCE_TYPES.values():
        all_types.extend(service_types)
    return sorted(set(all_types))


def get_common_resource_types():
    """Get a list of commonly used resource types.

    Returns:
        List of most commonly enforced resource types
    """
    return [
        "ec2:instance",
        "ec2:volume",
        "s3:bucket",
        "rds:db",
        "lambda:function",
        "dynamodb:table",
        "ecs:cluster",
        "eks:cluster",
        "elasticloadbalancing:loadbalancer",
        "cloudformation:stack",
    ]


def get_resource_types_by_service(service_name):
    """Get resource types for a specific service.

    Args:
        service_name: Name of the AWS service

    Returns:
        List of resource types for the service, or empty list if not found
    """
    return RESOURCE_TYPES.get(service_name, [])


def search_resource_types(query):
    """Search for resource types matching a query.

    Args:
        query: Search string to match against resource types

    Returns:
        List of matching resource types
    """
    query_lower = query.lower()
    matches = []

    for types in RESOURCE_TYPES.values():
        for resource_type in types:
            if query_lower in resource_type.lower():
                matches.append(resource_type)

    return sorted(set(matches))
