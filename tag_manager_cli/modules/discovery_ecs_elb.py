"""Discovery functions for ECS and ELB/ALB resources."""

from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
from botocore.exceptions import ClientError
from ..utils.aws_auth import aws_auth
import logging
from .discovery import store_resource, get_current_account_id, _ec2_arn

logger = logging.getLogger("discovery_ecs_elb")


def discover_ecs_resources(
    regions: Optional[List[str]] = None,
    store_directly: bool = True,
    session: Any = None,
    account_id: str = None,
) -> Dict[str, Any]:
    """Discover ECS clusters, services, and tasks across regions.

    Args:
        regions: List of AWS regions to scan. If None, scans all regions.
        store_directly: If True, store resources immediately in database.
        session: Optional boto3.Session to use instead of global aws_auth
        account_id: Account ID for cache key generation
    """
    discovery_stats = {
        "discovered_count": 0,
        "errors": [],
        "resource_types": {},
        "discovered_resources": [],
    }

    # If no regions specified, get all regions
    if not regions:
        try:
            if session:
                ec2_client = session.client("ec2", region_name="us-east-1")
            else:
                ec2_client = aws_auth.get_client("ec2", region="us-east-1")
            response = ec2_client.describe_regions()
            regions = [r["RegionName"] for r in response["Regions"]]
        except Exception as e:
            logger.warning(f"Failed to get regions list: {e}. Using defaults.")
            regions = ["us-east-1", "us-west-2", "eu-west-1"]

    for region in regions:
        try:
            # Use provided session if available, otherwise fall back to global aws_auth
            if session:
                ecs_client = session.client("ecs", region_name=region)
            else:
                ecs_client = aws_auth.get_client("ecs", region=region)

            # Discover ECS clusters with pagination
            cluster_arns = []
            next_token = None

            while True:
                if next_token:
                    response = ecs_client.list_clusters(nextToken=next_token)
                else:
                    response = ecs_client.list_clusters()

                cluster_arns.extend(response.get("clusterArns", []))

                # Check if there are more results
                next_token = response.get("nextToken")
                if not next_token:
                    break

            # Get detailed information for each cluster
            if cluster_arns:
                # Batch describe clusters (max 100 at a time)
                for i in range(0, len(cluster_arns), 100):
                    batch_arns = cluster_arns[i : i + 100]
                    clusters_response = ecs_client.describe_clusters(
                        clusters=batch_arns, include=["TAGS"]
                    )

                    for cluster in clusters_response.get("clusters", []):
                        try:
                            resource = process_ecs_cluster(cluster, region)
                            if resource:
                                if store_directly:
                                    store_resource(resource)
                                discovery_stats["discovered_resources"].append(resource)
                                discovery_stats["discovered_count"] += 1
                                discovery_stats["resource_types"]["ecs_cluster"] = (
                                    discovery_stats["resource_types"].get(
                                        "ecs_cluster", 0
                                    )
                                    + 1
                                )

                            # Discover services in this cluster
                            service_arns = []
                            next_token = None

                            while True:
                                if next_token:
                                    services_response = ecs_client.list_services(
                                        cluster=cluster["clusterArn"],
                                        nextToken=next_token,
                                    )
                                else:
                                    services_response = ecs_client.list_services(
                                        cluster=cluster["clusterArn"]
                                    )

                                service_arns.extend(
                                    services_response.get("serviceArns", [])
                                )
                                next_token = services_response.get("nextToken")
                                if not next_token:
                                    break

                            # Describe services (max 10 at a time)
                            for j in range(0, len(service_arns), 10):
                                batch_service_arns = service_arns[j : j + 10]
                                services_detail = ecs_client.describe_services(
                                    cluster=cluster["clusterArn"],
                                    services=batch_service_arns,
                                    include=["TAGS"],
                                )

                                for service in services_detail.get("services", []):
                                    try:
                                        resource = process_ecs_service(service, region)
                                        if resource:
                                            if store_directly:
                                                store_resource(resource)
                                            discovery_stats[
                                                "discovered_resources"
                                            ].append(resource)
                                            discovery_stats["discovered_count"] += 1
                                            discovery_stats["resource_types"][
                                                "ecs_service"
                                            ] = (
                                                discovery_stats["resource_types"].get(
                                                    "ecs_service", 0
                                                )
                                                + 1
                                            )
                                    except Exception as e:
                                        discovery_stats["errors"].append(
                                            f"Error processing ECS service {service.get('serviceName', 'unknown')}: {str(e)}"
                                        )

                        except Exception as e:
                            discovery_stats["errors"].append(
                                f"Error processing ECS cluster {cluster.get('clusterName', 'unknown')}: {str(e)}"
                            )

        except ClientError as e:
            from ..utils.error_handlers import check_permission_error

            if not check_permission_error(e):
                raise
            discovery_stats["errors"].append(
                f"No permission to describe ECS resources in {region}"
            )
            discovery_stats["permission_errors"] = (
                discovery_stats.get("permission_errors", 0) + 1
            )

        except Exception as e:
            discovery_stats["errors"].append(
                f"Error discovering ECS resources in {region}: {str(e)}"
            )

    return discovery_stats


def discover_elb_resources(
    regions: Optional[List[str]] = None,
    store_directly: bool = True,
    session: Any = None,
    account_id: str = None,
) -> Dict[str, Any]:
    """Discover ELB (Classic, Application, and Network Load Balancers) across regions.

    Args:
        regions: List of AWS regions to scan. If None, scans all regions.
        store_directly: If True, store resources immediately in database.
        session: Optional boto3.Session to use instead of global aws_auth
        account_id: Account ID for cache key generation
    """
    discovery_stats = {
        "discovered_count": 0,
        "errors": [],
        "resource_types": {},
        "discovered_resources": [],
    }

    # If no regions specified, get all regions
    if not regions:
        try:
            if session:
                ec2_client = session.client("ec2", region_name="us-east-1")
            else:
                ec2_client = aws_auth.get_client("ec2", region="us-east-1")
            response = ec2_client.describe_regions()
            regions = [r["RegionName"] for r in response["Regions"]]
        except Exception as e:
            logger.warning(f"Failed to get regions list: {e}. Using defaults.")
            regions = ["us-east-1", "us-west-2", "eu-west-1"]

    for region in regions:
        try:
            # Discover Classic Load Balancers
            # Use provided session if available, otherwise fall back to global aws_auth
            if session:
                elb_client = session.client("elb", region_name=region)
            else:
                elb_client = aws_auth.get_client("elb", region=region)

            # List classic load balancers with pagination
            classic_lbs = []
            next_marker = None

            while True:
                if next_marker:
                    response = elb_client.describe_load_balancers(Marker=next_marker)
                else:
                    response = elb_client.describe_load_balancers()

                classic_lbs.extend(response.get("LoadBalancerDescriptions", []))

                # Check if there are more results
                next_marker = response.get("NextMarker")
                if not next_marker:
                    break

            # Process classic load balancers
            for lb in classic_lbs:
                try:
                    # Get tags for classic LB
                    lb_name = lb.get("LoadBalancerName", "")
                    tags_response = elb_client.describe_tags(
                        LoadBalancerNames=[lb_name]
                    )
                    tag_list = []
                    for tag_desc in tags_response.get("TagDescriptions", []):
                        if tag_desc.get("LoadBalancerName") == lb_name:
                            tag_list = tag_desc.get("Tags", [])
                            break

                    resource = process_classic_lb(lb, tag_list, region)
                    if resource:
                        if store_directly:
                            store_resource(resource)
                        discovery_stats["discovered_resources"].append(resource)
                        discovery_stats["discovered_count"] += 1
                        discovery_stats["resource_types"]["elb_classic"] = (
                            discovery_stats["resource_types"].get("elb_classic", 0) + 1
                        )

                except Exception as e:
                    discovery_stats["errors"].append(
                        f"Error processing Classic LB {lb.get('LoadBalancerName', 'unknown')}: {str(e)}"
                    )

            # Discover Application and Network Load Balancers (ALB/NLB)
            # Use provided session if available, otherwise fall back to global aws_auth
            if session:
                elbv2_client = session.client("elbv2", region_name=region)
            else:
                elbv2_client = aws_auth.get_client("elbv2", region=region)

            # List ALB/NLB with pagination
            v2_lbs = []
            next_marker = None

            while True:
                if next_marker:
                    response = elbv2_client.describe_load_balancers(Marker=next_marker)
                else:
                    response = elbv2_client.describe_load_balancers()

                v2_lbs.extend(response.get("LoadBalancers", []))

                # Check if there are more results
                next_marker = response.get("NextMarker")
                if not next_marker:
                    break

            # Process ALB/NLB
            for lb in v2_lbs:
                try:
                    # Get tags for ALB/NLB
                    lb_arn = lb.get("LoadBalancerArn", "")
                    tags_response = elbv2_client.describe_tags(ResourceArns=[lb_arn])
                    tag_list = []
                    for tag_desc in tags_response.get("TagDescriptions", []):
                        if tag_desc.get("ResourceArn") == lb_arn:
                            tag_list = tag_desc.get("Tags", [])
                            break

                    resource = process_v2_lb(lb, tag_list, region)
                    if resource:
                        if store_directly:
                            store_resource(resource)
                        discovery_stats["discovered_resources"].append(resource)
                        discovery_stats["discovered_count"] += 1
                        lb_type = (
                            "elb_application"
                            if lb.get("Type") == "application"
                            else "elb_network"
                        )
                        discovery_stats["resource_types"][lb_type] = (
                            discovery_stats["resource_types"].get(lb_type, 0) + 1
                        )

                except Exception as e:
                    discovery_stats["errors"].append(
                        f"Error processing ALB/NLB {lb.get('LoadBalancerName', 'unknown')}: {str(e)}"
                    )

        except ClientError as e:
            from ..utils.error_handlers import check_permission_error

            if not check_permission_error(e):
                raise
            discovery_stats["errors"].append(
                f"No permission to describe ELB resources in {region}"
            )
            discovery_stats["permission_errors"] = (
                discovery_stats.get("permission_errors", 0) + 1
            )

        except Exception as e:
            discovery_stats["errors"].append(
                f"Error discovering ELB resources in {region}: {str(e)}"
            )

    return discovery_stats


def process_ecs_cluster(
    cluster: Dict[str, Any], region: str
) -> Optional[Dict[str, Any]]:
    """Process ECS cluster data into standardized resource format."""
    try:
        cluster_arn = cluster["clusterArn"]
        cluster_name = cluster["clusterName"]

        # Extract tags
        tags = {}
        for tag in cluster.get("tags", []):
            tags[tag["key"]] = tag["value"]

        # Extract account ID from ARN
        arn_parts = cluster_arn.split(":")
        account_id = arn_parts[4] if len(arn_parts) > 4 else get_current_account_id()

        return {
            "resource_arn": cluster_arn,
            "resource_type": "AWS::ECS::Cluster",
            "service_name": "ecs",
            "region": region,
            "account_id": account_id,
            "resource_id": cluster_name,
            "created_at": None,  # ECS doesn't provide creation time
            "current_tags": tags,
            "metadata_json": {
                "status": cluster.get("status"),
                "running_tasks": cluster.get("runningTasksCount", 0),
                "pending_tasks": cluster.get("pendingTasksCount", 0),
                "active_services": cluster.get("activeServicesCount", 0),
                "registered_instances": cluster.get(
                    "registeredContainerInstancesCount", 0
                ),
            },
        }
    except KeyError as e:
        raise ValueError(f"Missing required field in ECS cluster data: {e}")


def process_ecs_service(
    service: Dict[str, Any], region: str
) -> Optional[Dict[str, Any]]:
    """Process ECS service data into standardized resource format."""
    try:
        service_arn = service["serviceArn"]
        service_name = service["serviceName"]

        # Extract tags
        tags = {}
        for tag in service.get("tags", []):
            tags[tag["key"]] = tag["value"]

        # Extract account ID from ARN
        arn_parts = service_arn.split(":")
        account_id = arn_parts[4] if len(arn_parts) > 4 else get_current_account_id()

        relationships = []
        cluster_arn = service.get("clusterArn")
        if cluster_arn:
            relationships.append(
                {
                    "source_arn": service_arn,
                    "target_arn": cluster_arn,
                    "relationship_type": "BELONGS_TO",
                    "source_type": "AWS::ECS::Service",
                    "target_type": "AWS::ECS::Cluster",
                    "region": region,
                    "account_id": account_id,
                }
            )
        for lb in service.get("loadBalancers", []):
            tg_arn = lb.get("targetGroupArn")
            if tg_arn:
                relationships.append(
                    {
                        "source_arn": service_arn,
                        "target_arn": tg_arn,
                        "relationship_type": "TARGETS",
                        "source_type": "AWS::ECS::Service",
                        "target_type": "AWS::ElasticLoadBalancingV2::TargetGroup",
                        "region": region,
                        "account_id": account_id,
                    }
                )
        # VPC networking (awsvpc launch type)
        awsvpc = service.get("networkConfiguration", {}).get("awsvpcConfiguration", {})
        for subnet_id in awsvpc.get("subnets", []):
            if subnet_id:
                relationships.append(
                    {
                        "source_arn": service_arn,
                        "target_arn": f"arn:aws:ec2:{region}:{account_id}:subnet/{subnet_id}",
                        "relationship_type": "RUNS_IN",
                        "source_type": "AWS::ECS::Service",
                        "target_type": "AWS::EC2::Subnet",
                        "region": region,
                        "account_id": account_id,
                    }
                )
        for sg_id in awsvpc.get("securityGroups", []):
            if sg_id:
                relationships.append(
                    {
                        "source_arn": service_arn,
                        "target_arn": f"arn:aws:ec2:{region}:{account_id}:security-group/{sg_id}",
                        "relationship_type": "USES",
                        "source_type": "AWS::ECS::Service",
                        "target_type": "AWS::EC2::SecurityGroup",
                        "region": region,
                        "account_id": account_id,
                    }
                )

        return {
            "resource_arn": service_arn,
            "resource_type": "AWS::ECS::Service",
            "service_name": "ecs",
            "region": region,
            "account_id": account_id,
            "resource_id": service_name,
            "created_at": service.get("createdAt"),
            "current_tags": tags,
            "relationships": relationships,
            "metadata_json": {
                "status": service.get("status"),
                "desired_count": service.get("desiredCount", 0),
                "running_count": service.get("runningCount", 0),
                "pending_count": service.get("pendingCount", 0),
                "launch_type": service.get("launchType"),
                "cluster_arn": service.get("clusterArn"),
            },
        }
    except KeyError as e:
        raise ValueError(f"Missing required field in ECS service data: {e}")


def process_classic_lb(
    lb: Dict[str, Any], tag_list: List[Dict[str, str]], region: str
) -> Optional[Dict[str, Any]]:
    """Process Classic Load Balancer data into standardized resource format."""
    try:
        lb_name = lb["LoadBalancerName"]

        # Build ARN for classic LB
        account_id = get_current_account_id()
        lb_arn = (
            f"arn:aws:elasticloadbalancing:{region}:{account_id}:loadbalancer/{lb_name}"
        )

        # Extract tags
        tags = {}
        for tag in tag_list:
            tags[tag["Key"]] = tag["Value"]

        relationships = []
        vpc_id = lb.get("VPCId")
        if vpc_id:
            relationships.append(
                {
                    "source_arn": lb_arn,
                    "target_arn": _ec2_arn(region, account_id, "vpc", vpc_id),
                    "relationship_type": "RUNS_IN",
                    "source_type": "AWS::ElasticLoadBalancing::LoadBalancer",
                    "target_type": "AWS::EC2::VPC",
                    "region": region,
                    "account_id": account_id,
                }
            )
        for inst in lb.get("Instances", []):
            inst_id = inst.get("InstanceId")
            if inst_id:
                relationships.append(
                    {
                        "source_arn": lb_arn,
                        "target_arn": f"arn:aws:ec2:{region}:{account_id}:instance/{inst_id}",
                        "relationship_type": "TARGETS",
                        "source_type": "AWS::ElasticLoadBalancing::LoadBalancer",
                        "target_type": "AWS::EC2::Instance",
                        "region": region,
                        "account_id": account_id,
                    }
                )
        for sg_id in lb.get("SecurityGroups", []):
            relationships.append(
                {
                    "source_arn": lb_arn,
                    "target_arn": _ec2_arn(region, account_id, "security-group", sg_id),
                    "relationship_type": "USES",
                    "source_type": "AWS::ElasticLoadBalancing::LoadBalancer",
                    "target_type": "AWS::EC2::SecurityGroup",
                    "region": region,
                    "account_id": account_id,
                }
            )

        return {
            "resource_arn": lb_arn,
            "resource_type": "AWS::ElasticLoadBalancing::LoadBalancer",
            "service_name": "elb",
            "region": region,
            "account_id": account_id,
            "resource_id": lb_name,
            "created_at": lb.get("CreatedTime"),
            "current_tags": tags,
            "relationships": relationships,
            "metadata_json": {
                "scheme": lb.get("Scheme"),
                "dns_name": lb.get("DNSName"),
                "vpc_id": lb.get("VPCId"),
                "availability_zones": lb.get("AvailabilityZones", []),
                "instance_count": len(lb.get("Instances", [])),
            },
        }
    except KeyError as e:
        raise ValueError(f"Missing required field in Classic LB data: {e}")


def process_v2_lb(
    lb: Dict[str, Any], tag_list: List[Dict[str, str]], region: str
) -> Optional[Dict[str, Any]]:
    """Process ALB/NLB data into standardized resource format."""
    try:
        lb_arn = lb["LoadBalancerArn"]
        lb_name = lb["LoadBalancerName"]

        # Extract tags
        tags = {}
        for tag in tag_list:
            tags[tag["Key"]] = tag["Value"]

        # Extract account ID from ARN
        arn_parts = lb_arn.split(":")
        account_id = arn_parts[4] if len(arn_parts) > 4 else get_current_account_id()

        resource_type = "AWS::ElasticLoadBalancingV2::LoadBalancer"
        if lb.get("Type") == "network":
            resource_type = "AWS::ElasticLoadBalancingV2::LoadBalancer/Network"
        elif lb.get("Type") == "application":
            resource_type = "AWS::ElasticLoadBalancingV2::LoadBalancer/Application"

        relationships = []
        vpc_id = lb.get("VpcId")
        if vpc_id:
            relationships.append(
                {
                    "source_arn": lb_arn,
                    "target_arn": _ec2_arn(region, account_id, "vpc", vpc_id),
                    "relationship_type": "RUNS_IN",
                    "source_type": resource_type,
                    "target_type": "AWS::EC2::VPC",
                    "region": region,
                    "account_id": account_id,
                }
            )
        for az in lb.get("AvailabilityZones", []):
            subnet_id = az.get("SubnetId")
            if subnet_id:
                relationships.append(
                    {
                        "source_arn": lb_arn,
                        "target_arn": _ec2_arn(region, account_id, "subnet", subnet_id),
                        "relationship_type": "RUNS_IN",
                        "source_type": resource_type,
                        "target_type": "AWS::EC2::Subnet",
                        "region": region,
                        "account_id": account_id,
                    }
                )
        for sg_id in lb.get("SecurityGroups", []):
            relationships.append(
                {
                    "source_arn": lb_arn,
                    "target_arn": _ec2_arn(region, account_id, "security-group", sg_id),
                    "relationship_type": "USES",
                    "source_type": resource_type,
                    "target_type": "AWS::EC2::SecurityGroup",
                    "region": region,
                    "account_id": account_id,
                }
            )

        return {
            "resource_arn": lb_arn,
            "resource_type": resource_type,
            "service_name": "elbv2",
            "region": region,
            "account_id": account_id,
            "resource_id": lb_name,
            "created_at": lb.get("CreatedTime"),
            "current_tags": tags,
            "relationships": relationships,
            "metadata_json": {
                "type": lb.get("Type"),
                "scheme": lb.get("Scheme"),
                "state": lb.get("State", {}).get("Code"),
                "dns_name": lb.get("DNSName"),
                "vpc_id": lb.get("VpcId"),
                "availability_zones": [
                    az["ZoneName"] for az in lb.get("AvailabilityZones", [])
                ],
            },
        }
    except KeyError as e:
        raise ValueError(f"Missing required field in ALB/NLB data: {e}")
