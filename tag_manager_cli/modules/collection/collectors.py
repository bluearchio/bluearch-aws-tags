"""Service collectors for the collection engine.

Each collector fetches resources from a single AWS service in a single
region, returning a CollectorResult.  Collectors do NOT write to the
database -- that is the batcher's job.

Collectors reuse the existing process_* helper functions from the
discovery modules to ensure identical resource dict formats.
"""

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

from botocore.exceptions import ClientError

from ...utils.aws_auth import aws_auth
from ...utils.cache import cache
from ...utils.env_config import settings
from .models import CollectionJob, CollectorResult

logger = logging.getLogger(__name__)


PERMISSION_RESOURCE_TYPES: Dict[str, List[str]] = {
    "EC2 instances": ["AWS::EC2::Instance"],
    "EBS volumes": ["AWS::EC2::Volume"],
    "AMIs": ["AWS::EC2::Image"],
    "Elastic IPs": ["AWS::EC2::EIP"],
    "EBS snapshots": ["AWS::EC2::Snapshot"],
    "S3 buckets": ["AWS::S3::Bucket"],
    "Lambda functions": ["AWS::Lambda::Function"],
    "Lambda layers": ["AWS::Lambda::LayerVersion"],
    "RDS resources": ["AWS::RDS::DBInstance", "AWS::RDS::DBCluster"],
    "RDS snapshots": ["AWS::RDS::DBSnapshot"],
    "DynamoDB resources": ["AWS::DynamoDB::Table"],
    "ECS resources": ["AWS::ECS::Cluster", "AWS::ECS::Service"],
    "ECS task definitions": ["AWS::ECS::TaskDefinition"],
    "Classic LBs": ["AWS::ElasticLoadBalancing::LoadBalancer"],
    "ALB/NLB": [
        "AWS::ElasticLoadBalancingV2::LoadBalancer/Application",
        "AWS::ElasticLoadBalancingV2::LoadBalancer/Network",
    ],
    "ELB resources": [
        "AWS::ElasticLoadBalancing::LoadBalancer",
        "AWS::ElasticLoadBalancingV2::LoadBalancer/Application",
        "AWS::ElasticLoadBalancingV2::LoadBalancer/Network",
    ],
    "SNS topics": ["AWS::SNS::Topic"],
    "SQS queues": ["AWS::SQS::Queue"],
    "CloudWatch alarms": ["AWS::CloudWatch::Alarm"],
    "CloudWatch Log Groups": ["AWS::Logs::LogGroup"],
    "EKS clusters": ["AWS::EKS::Cluster"],
    "ElastiCache clusters": ["AWS::ElastiCache::CacheCluster"],
    "VPCs": ["AWS::EC2::VPC"],
    "Subnets": ["AWS::EC2::Subnet"],
    "Security Groups": ["AWS::EC2::SecurityGroup"],
    "IAM roles": ["AWS::IAM::Role"],
}


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------

class ServiceCollector:
    """Base class with retry/backoff for AWS API calls."""

    MAX_RETRIES = 3
    BASE_BACKOFF = 0.5

    def collect(self, job: CollectionJob) -> CollectorResult:
        raise NotImplementedError

    def _call_with_retry(self, func, *args, **kwargs):
        """Call *func* with exponential backoff on Throttling errors."""
        last_exc = None
        for attempt in range(self.MAX_RETRIES):
            try:
                return func(*args, **kwargs)
            except ClientError as e:
                code = e.response['Error'].get('Code', '')
                if code in ('Throttling', 'ThrottlingException', 'RequestLimitExceeded', 'TooManyRequestsException'):
                    wait = self.BASE_BACKOFF * (2 ** attempt)
                    logger.debug(f"Throttled ({code}), retrying in {wait:.1f}s (attempt {attempt + 1})")
                    time.sleep(wait)
                    last_exc = e
                else:
                    raise
        raise last_exc

    def _get_client(self, service_name: str, region: Optional[str], session: Any = None):
        """Get boto3 client from provided session or global aws_auth."""
        if session:
            kwargs = {}
            if region:
                kwargs['region_name'] = region
            return session.client(service_name, **kwargs)
        return aws_auth.get_client(service_name, region=region)

    @staticmethod
    def _get_effective_account_id(account_id: Optional[str]) -> str:
        from ..discovery import get_current_account_id
        return account_id or get_current_account_id()

    @staticmethod
    def _is_permission_error(e: ClientError) -> bool:
        from ...utils.error_handlers import check_permission_error
        return check_permission_error(e)

    def _record_permission_error(
        self,
        result: CollectorResult,
        region: Optional[str],
        service: str,
        exc: Exception,
        account_id: Optional[str] = None,
    ) -> None:
        """Record a structured permission failure for CLI and web summaries."""
        code = ""
        message = str(exc)
        if isinstance(exc, ClientError):
            error = exc.response.get("Error", {})
            code = error.get("Code", "")
            message = error.get("Message") or message

        result.permission_errors += 1
        result.permission_error_details.append({
            "type": "permission_denied",
            "service": service,
            "region": region or "global",
            "account_id": account_id,
            "code": code or type(exc).__name__,
            "message": f"{service} in {region or 'global'} was not collected: {message}",
            "resource_types": list(PERMISSION_RESOURCE_TYPES.get(service, [])),
            "suggestion": (
                "Update the BlueArchRole StackSet or assume-role policy for these resource types, "
                "then rerun the scan."
            ),
        })

    def _extract_relationships(self, resource_dict, result):
        """Pop relationships from resource dict and add to result."""
        rels = resource_dict.pop('relationships', [])
        if rels:
            result.relationships.extend(rels)


# ---------------------------------------------------------------------------
# EC2
# ---------------------------------------------------------------------------

class EC2Collector(ServiceCollector):
    """Collect EC2 instances and EBS volumes."""

    def collect(self, job: CollectionJob) -> CollectorResult:
        from ..discovery import process_ec2_instance, process_ebs_volume

        result = CollectorResult()
        region = job.region
        effective_account_id = self._get_effective_account_id(job.account_id)

        # --- Instances ---
        try:
            cache_key = cache.generate_key('ec2', 'describe_instances', region=region, account_id=effective_account_id)
            cached = cache.get(cache_key)

            if cached:
                instances_data = cached
            else:
                ec2_client = self._get_client('ec2', region, job.session)
                instances_data = []
                paginator = ec2_client.get_paginator('describe_instances')
                for page in self._call_with_retry(lambda: list(paginator.paginate())):
                    for reservation in page.get('Reservations', []):
                        instances_data.extend(reservation.get('Instances', []))
                cache.set(cache_key, instances_data, ttl=settings.cache_ttl_resources)

            for inst in instances_data:
                try:
                    resource = process_ec2_instance(inst, region)
                    if resource:
                        self._extract_relationships(resource, result)
                        result.resources.append(resource)
                except Exception as e:
                    result.errors.append(f"Error processing instance {inst.get('InstanceId', '?')}: {e}")

        except ClientError as e:
            if self._is_permission_error(e):
                result.errors.append(f"No permission to describe EC2 instances in {region}")
                self._record_permission_error(result, region, "EC2 instances", e, job.account_id)
                return result
            raise

        # --- EBS Volumes ---
        try:
            ec2_client = self._get_client('ec2', region, job.session)
            volumes_data = []
            paginator = ec2_client.get_paginator('describe_volumes')
            for page in self._call_with_retry(lambda: list(paginator.paginate())):
                volumes_data.extend(page.get('Volumes', []))

            for vol in volumes_data:
                try:
                    resource = process_ebs_volume(vol, region)
                    if resource:
                        self._extract_relationships(resource, result)
                        result.resources.append(resource)
                except Exception as e:
                    result.errors.append(f"Error processing volume {vol.get('VolumeId', '?')}: {e}")

        except ClientError as e:
            if self._is_permission_error(e):
                result.errors.append(f"No permission to describe EBS volumes in {region}")
                self._record_permission_error(result, region, "EBS volumes", e, job.account_id)
            else:
                raise

        # --- AMIs (owned by this account) ---
        try:
            from ..discovery import process_ec2_image

            ec2_client = self._get_client('ec2', region, job.session)
            cache_key = cache.generate_key('ec2', 'describe_images', region=region, account_id=effective_account_id)
            cached = cache.get(cache_key)

            if cached:
                images_data = cached
            else:
                response = self._call_with_retry(
                    ec2_client.describe_images, Owners=['self']
                )
                images_data = response.get('Images', [])
                cache.set(cache_key, images_data, ttl=settings.cache_ttl_resources)

            for img in images_data:
                try:
                    resource = process_ec2_image(img, region)
                    if resource:
                        self._extract_relationships(resource, result)
                        result.resources.append(resource)
                except Exception as e:
                    result.errors.append(f"Error processing AMI {img.get('ImageId', '?')}: {e}")

        except ClientError as e:
            if self._is_permission_error(e):
                result.errors.append(f"No permission to describe AMIs in {region}")
                self._record_permission_error(result, region, "AMIs", e, job.account_id)
            else:
                raise

        # --- Elastic IPs ---
        try:
            from ..discovery import process_ec2_eip

            ec2_client = self._get_client('ec2', region, job.session)
            response = self._call_with_retry(ec2_client.describe_addresses)
            addresses_data = response.get('Addresses', [])

            for addr in addresses_data:
                try:
                    resource = process_ec2_eip(addr, region)
                    if resource:
                        self._extract_relationships(resource, result)
                        result.resources.append(resource)
                except Exception as e:
                    result.errors.append(f"Error processing EIP {addr.get('AllocationId', '?')}: {e}")

        except ClientError as e:
            if self._is_permission_error(e):
                result.errors.append(f"No permission to describe Elastic IPs in {region}")
                self._record_permission_error(result, region, "Elastic IPs", e, job.account_id)
            else:
                raise

        # --- Snapshots ---
        try:
            ec2_client = self._get_client('ec2', region, job.session)
            snapshots_data = []
            paginator = ec2_client.get_paginator('describe_snapshots')
            for page in self._call_with_retry(lambda: list(paginator.paginate(OwnerIds=['self']))):
                snapshots_data.extend(page.get('Snapshots', []))

            for snap in snapshots_data:
                try:
                    from ..discovery import process_ec2_instance  # noqa: reuse pattern
                    tags = {}
                    for tag in snap.get('Tags', []):
                        tags[tag['Key']] = tag['Value']
                    snap_id = snap['SnapshotId']
                    start_time = snap.get('StartTime')
                    if start_time and isinstance(start_time, str):
                        from datetime import datetime
                        try:
                            start_time = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                        except (ValueError, TypeError):
                            start_time = None
                    resource = {
                        'resource_arn': f"arn:aws:ec2:{region}:{effective_account_id}:snapshot/{snap_id}",
                        'resource_type': 'AWS::EC2::Snapshot',
                        'service_name': 'ec2',
                        'region': region,
                        'account_id': snap.get('OwnerId', effective_account_id),
                        'resource_id': snap_id,
                        'created_at': start_time,
                        'current_tags': tags,
                        'metadata_json': {
                            'volume_id': snap.get('VolumeId'),
                            'state': snap.get('State'),
                            'volume_size': snap.get('VolumeSize'),
                            'description': snap.get('Description', '')[:200],
                            'encrypted': snap.get('Encrypted', False),
                        }
                    }
                    result.resources.append(resource)
                except Exception as e:
                    result.errors.append(f"Error processing snapshot {snap.get('SnapshotId', '?')}: {e}")

        except ClientError as e:
            if self._is_permission_error(e):
                result.errors.append(f"No permission to describe snapshots in {region}")
                self._record_permission_error(result, region, "EBS snapshots", e, job.account_id)
            else:
                raise

        return result


# ---------------------------------------------------------------------------
# S3
# ---------------------------------------------------------------------------

class S3Collector(ServiceCollector):
    """Collect S3 buckets with parallel location lookups."""

    def collect(self, job: CollectionJob) -> CollectorResult:
        from ..discovery import process_s3_bucket, get_bucket_region

        result = CollectorResult()
        effective_account_id = self._get_effective_account_id(job.account_id)

        try:
            s3_client = self._get_client('s3', None, job.session)

            cache_key = cache.generate_key('s3', 'list_buckets', account_id=effective_account_id)
            cached = cache.get(cache_key)

            if cached:
                buckets_data = cached
            else:
                response = self._call_with_retry(s3_client.list_buckets)
                buckets_data = response.get('Buckets', [])
                cache.set(cache_key, buckets_data, ttl=settings.cache_ttl_resources * 4)

            # Parallel bucket region lookups
            bucket_regions: Dict[str, str] = {}

            def _get_region(name: str) -> tuple:
                return name, get_bucket_region(name)

            with ThreadPoolExecutor(max_workers=5) as pool:
                futures = {pool.submit(_get_region, b['Name']): b for b in buckets_data}
                for future in as_completed(futures):
                    try:
                        name, region = future.result()
                        bucket_regions[name] = region
                    except Exception:
                        bucket_regions[futures[future]['Name']] = 'us-east-1'

            # Process buckets
            for bucket in buckets_data:
                try:
                    name = bucket['Name']
                    region = bucket_regions.get(name, 'us-east-1')
                    resource = process_s3_bucket(bucket, region)
                    if resource:
                        self._extract_relationships(resource, result)
                        result.resources.append(resource)
                except Exception as e:
                    result.errors.append(f"Error processing bucket {bucket.get('Name', '?')}: {e}")

        except ClientError as e:
            if self._is_permission_error(e):
                result.errors.append("No permission to list S3 buckets")
                self._record_permission_error(result, "global", "S3 buckets", e, job.account_id)
            else:
                raise

        return result


# ---------------------------------------------------------------------------
# Lambda
# ---------------------------------------------------------------------------

class LambdaCollector(ServiceCollector):
    """Collect Lambda functions."""

    def collect(self, job: CollectionJob) -> CollectorResult:
        from ..discovery import process_lambda_function

        result = CollectorResult()
        region = job.region
        effective_account_id = self._get_effective_account_id(job.account_id)

        try:
            cache_key = cache.generate_key('lambda', 'list_functions', region=region, account_id=effective_account_id)
            cached = cache.get(cache_key)

            if cached:
                functions_data = cached
            else:
                client = self._get_client('lambda', region, job.session)
                functions_data = []
                paginator = client.get_paginator('list_functions')
                for page in self._call_with_retry(lambda: list(paginator.paginate())):
                    functions_data.extend(page.get('Functions', []))
                cache.set(cache_key, functions_data, ttl=settings.cache_ttl_resources)

            for func in functions_data:
                try:
                    resource = process_lambda_function(func, region)
                    if resource:
                        self._extract_relationships(resource, result)
                        result.resources.append(resource)
                except Exception as e:
                    result.errors.append(f"Error processing function {func.get('FunctionName', '?')}: {e}")

        except ClientError as e:
            if self._is_permission_error(e):
                result.errors.append(f"No permission to list Lambda functions in {region}")
                self._record_permission_error(result, region, "Lambda functions", e, job.account_id)
            else:
                raise

        # --- Lambda Layers ---
        try:
            from ..discovery import process_lambda_layer

            client = self._get_client('lambda', region, job.session)
            layers_data = []
            paginator = client.get_paginator('list_layers')
            for page in self._call_with_retry(lambda: list(paginator.paginate())):
                layers_data.extend(page.get('Layers', []))

            for layer in layers_data:
                try:
                    resource = process_lambda_layer(layer, region)
                    if resource:
                        self._extract_relationships(resource, result)
                        result.resources.append(resource)
                except Exception as e:
                    result.errors.append(f"Error processing layer {layer.get('LayerName', '?')}: {e}")

        except ClientError as e:
            if self._is_permission_error(e):
                result.errors.append(f"No permission to list Lambda layers in {region}")
                self._record_permission_error(result, region, "Lambda layers", e, job.account_id)
            else:
                raise

        return result


# ---------------------------------------------------------------------------
# RDS
# ---------------------------------------------------------------------------

class RDSCollector(ServiceCollector):
    """Collect RDS instances and clusters."""

    def collect(self, job: CollectionJob) -> CollectorResult:
        from ..discovery import process_rds_instance, process_rds_cluster

        result = CollectorResult()
        region = job.region

        try:
            client = self._get_client('rds', region, job.session)

            # DB Instances
            db_instances = []
            paginator = client.get_paginator('describe_db_instances')
            for page in self._call_with_retry(lambda: list(paginator.paginate())):
                db_instances.extend(page.get('DBInstances', []))

            for inst in db_instances:
                try:
                    resource = process_rds_instance(inst, region)
                    if resource:
                        self._extract_relationships(resource, result)
                        result.resources.append(resource)
                except Exception as e:
                    result.errors.append(f"Error processing RDS instance {inst.get('DBInstanceIdentifier', '?')}: {e}")

            # DB Clusters
            db_clusters = []
            paginator = client.get_paginator('describe_db_clusters')
            for page in self._call_with_retry(lambda: list(paginator.paginate())):
                db_clusters.extend(page.get('DBClusters', []))

            for cluster in db_clusters:
                try:
                    resource = process_rds_cluster(cluster, region)
                    if resource:
                        self._extract_relationships(resource, result)
                        result.resources.append(resource)
                except Exception as e:
                    result.errors.append(f"Error processing RDS cluster {cluster.get('DBClusterIdentifier', '?')}: {e}")

            # DB Snapshots (manual only, not automated backups)
            try:
                from ..discovery import process_rds_snapshot

                db_snapshots = []
                snap_paginator = client.get_paginator('describe_db_snapshots')
                for page in self._call_with_retry(
                    lambda: list(snap_paginator.paginate(SnapshotType='manual'))
                ):
                    db_snapshots.extend(page.get('DBSnapshots', []))

                for snap in db_snapshots:
                    try:
                        snap_arn = snap.get('DBSnapshotArn', '')
                        tags_resp = self._call_with_retry(
                            client.list_tags_for_resource, ResourceName=snap_arn
                        )
                        tag_list = tags_resp.get('TagList', [])
                        resource = process_rds_snapshot(snap, tag_list, region)
                        if resource:
                            self._extract_relationships(resource, result)
                            result.resources.append(resource)
                    except Exception as e:
                        result.errors.append(
                            f"Error processing RDS snapshot {snap.get('DBSnapshotIdentifier', '?')}: {e}"
                        )
            except ClientError as e:
                if self._is_permission_error(e):
                    result.errors.append(f"No permission to describe RDS snapshots in {region}")
                    self._record_permission_error(result, region, "RDS snapshots", e, job.account_id)

        except ClientError as e:
            if self._is_permission_error(e):
                result.errors.append(f"No permission to describe RDS resources in {region}")
                self._record_permission_error(result, region, "RDS resources", e, job.account_id)
            else:
                raise

        return result


# ---------------------------------------------------------------------------
# DynamoDB
# ---------------------------------------------------------------------------

class DynamoDBCollector(ServiceCollector):
    """Collect DynamoDB tables."""

    def collect(self, job: CollectionJob) -> CollectorResult:
        from ..discovery import process_dynamodb_table

        result = CollectorResult()
        region = job.region

        try:
            client = self._get_client('dynamodb', region, job.session)

            # List tables
            table_names: List[str] = []
            paginator = client.get_paginator('list_tables')
            for page in self._call_with_retry(lambda: list(paginator.paginate())):
                table_names.extend(page.get('TableNames', []))

            for table_name in table_names:
                try:
                    table_resp = self._call_with_retry(client.describe_table, TableName=table_name)
                    table_data = table_resp.get('Table', {})
                    table_arn = table_data.get('TableArn', '')
                    tags_resp = self._call_with_retry(client.list_tags_of_resource, ResourceArn=table_arn)
                    tag_list = tags_resp.get('Tags', [])

                    resource = process_dynamodb_table(table_data, tag_list, region)
                    if resource:
                        self._extract_relationships(resource, result)
                        result.resources.append(resource)
                except Exception as e:
                    result.errors.append(f"Error processing DynamoDB table {table_name}: {e}")

        except ClientError as e:
            if self._is_permission_error(e):
                result.errors.append(f"No permission to describe DynamoDB resources in {region}")
                self._record_permission_error(result, region, "DynamoDB resources", e, job.account_id)
            else:
                raise

        return result


# ---------------------------------------------------------------------------
# ECS
# ---------------------------------------------------------------------------

class ECSCollector(ServiceCollector):
    """Collect ECS clusters and services."""

    def collect(self, job: CollectionJob) -> CollectorResult:
        from ..discovery_ecs_elb import process_ecs_cluster, process_ecs_service

        result = CollectorResult()
        region = job.region

        try:
            client = self._get_client('ecs', region, job.session)

            # List clusters
            cluster_arns: List[str] = []
            paginator = client.get_paginator('list_clusters')
            for page in self._call_with_retry(lambda: list(paginator.paginate())):
                cluster_arns.extend(page.get('clusterArns', []))

            if not cluster_arns:
                return result

            # Describe clusters in batches of 100
            for i in range(0, len(cluster_arns), 100):
                batch = cluster_arns[i:i + 100]
                clusters_resp = self._call_with_retry(
                    client.describe_clusters, clusters=batch, include=['TAGS']
                )

                for cluster in clusters_resp.get('clusters', []):
                    try:
                        resource = process_ecs_cluster(cluster, region)
                        if resource:
                            self._extract_relationships(resource, result)
                            result.resources.append(resource)
                    except Exception as e:
                        result.errors.append(f"Error processing ECS cluster {cluster.get('clusterName', '?')}: {e}")

                    # Discover services in this cluster
                    try:
                        service_arns: List[str] = []
                        svc_paginator = client.get_paginator('list_services')
                        for svc_page in self._call_with_retry(
                            lambda c=cluster['clusterArn']: list(svc_paginator.paginate(cluster=c))
                        ):
                            service_arns.extend(svc_page.get('serviceArns', []))

                        for j in range(0, len(service_arns), 10):
                            svc_batch = service_arns[j:j + 10]
                            svc_detail = self._call_with_retry(
                                client.describe_services,
                                cluster=cluster['clusterArn'],
                                services=svc_batch,
                                include=['TAGS'],
                            )
                            for svc in svc_detail.get('services', []):
                                try:
                                    resource = process_ecs_service(svc, region)
                                    if resource:
                                        self._extract_relationships(resource, result)
                                        result.resources.append(resource)
                                except Exception as e:
                                    result.errors.append(
                                        f"Error processing ECS service {svc.get('serviceName', '?')}: {e}"
                                    )
                    except Exception as e:
                        result.errors.append(f"Error discovering ECS services: {e}")

        except ClientError as e:
            if self._is_permission_error(e):
                result.errors.append(f"No permission to describe ECS resources in {region}")
                self._record_permission_error(result, region, "ECS resources", e, job.account_id)
            else:
                raise

        # --- Task Definitions (active only) ---
        try:
            from ..discovery import process_ecs_task_definition

            client = self._get_client('ecs', region, job.session)
            taskdef_arns: List[str] = []
            paginator = client.get_paginator('list_task_definitions')
            for page in self._call_with_retry(
                lambda: list(paginator.paginate(status='ACTIVE'))
            ):
                taskdef_arns.extend(page.get('taskDefinitionArns', []))

            for td_arn in taskdef_arns:
                try:
                    td_resp = self._call_with_retry(
                        client.describe_task_definition,
                        taskDefinition=td_arn,
                        include=['TAGS'],
                    )
                    td_data = td_resp.get('taskDefinition', {})
                    tag_list = td_resp.get('tags', [])
                    resource = process_ecs_task_definition(td_data, tag_list, region)
                    if resource:
                        self._extract_relationships(resource, result)
                        result.resources.append(resource)
                except Exception as e:
                    result.errors.append(f"Error processing task definition {td_arn.split('/')[-1]}: {e}")

        except ClientError as e:
            if self._is_permission_error(e):
                result.errors.append(f"No permission to list ECS task definitions in {region}")
                self._record_permission_error(result, region, "ECS task definitions", e, job.account_id)
            else:
                raise

        return result


# ---------------------------------------------------------------------------
# ELB
# ---------------------------------------------------------------------------

class ELBCollector(ServiceCollector):
    """Collect Classic and v2 (ALB/NLB) load balancers."""

    def collect(self, job: CollectionJob) -> CollectorResult:
        from ..discovery_ecs_elb import process_classic_lb, process_v2_lb

        result = CollectorResult()
        region = job.region

        try:
            # --- Classic LBs ---
            try:
                elb_client = self._get_client('elb', region, job.session)
                classic_lbs = []
                paginator = elb_client.get_paginator('describe_load_balancers')
                for page in self._call_with_retry(lambda: list(paginator.paginate())):
                    classic_lbs.extend(page.get('LoadBalancerDescriptions', []))

                for lb in classic_lbs:
                    try:
                        lb_name = lb.get('LoadBalancerName', '')
                        tags_resp = self._call_with_retry(
                            elb_client.describe_tags, LoadBalancerNames=[lb_name]
                        )
                        tag_list = []
                        for td in tags_resp.get('TagDescriptions', []):
                            if td.get('LoadBalancerName') == lb_name:
                                tag_list = td.get('Tags', [])
                                break
                        resource = process_classic_lb(lb, tag_list, region)
                        if resource:
                            self._extract_relationships(resource, result)
                            result.resources.append(resource)
                    except Exception as e:
                        result.errors.append(f"Error processing Classic LB {lb.get('LoadBalancerName', '?')}: {e}")
            except ClientError as e:
                if self._is_permission_error(e):
                    result.errors.append(f"No permission to describe Classic LBs in {region}")
                    self._record_permission_error(result, region, "Classic LBs", e, job.account_id)
                else:
                    raise

            # --- ALB / NLB ---
            try:
                elbv2_client = self._get_client('elbv2', region, job.session)
                v2_lbs = []
                paginator = elbv2_client.get_paginator('describe_load_balancers')
                for page in self._call_with_retry(lambda: list(paginator.paginate())):
                    v2_lbs.extend(page.get('LoadBalancers', []))

                for lb in v2_lbs:
                    try:
                        lb_arn = lb.get('LoadBalancerArn', '')
                        tags_resp = self._call_with_retry(
                            elbv2_client.describe_tags, ResourceArns=[lb_arn]
                        )
                        tag_list = []
                        for td in tags_resp.get('TagDescriptions', []):
                            if td.get('ResourceArn') == lb_arn:
                                tag_list = td.get('Tags', [])
                                break
                        resource = process_v2_lb(lb, tag_list, region)
                        if resource:
                            self._extract_relationships(resource, result)
                            result.resources.append(resource)
                    except Exception as e:
                        result.errors.append(f"Error processing ALB/NLB {lb.get('LoadBalancerName', '?')}: {e}")
            except ClientError as e:
                if self._is_permission_error(e):
                    result.errors.append(f"No permission to describe ALB/NLB in {region}")
                    self._record_permission_error(result, region, "ALB/NLB", e, job.account_id)
                else:
                    raise

        except ClientError as e:
            if self._is_permission_error(e):
                result.errors.append(f"No permission to describe ELB resources in {region}")
                self._record_permission_error(result, region, "ELB resources", e, job.account_id)
            else:
                raise

        return result


# ---------------------------------------------------------------------------
# SNS
# ---------------------------------------------------------------------------

class SNSCollector(ServiceCollector):
    """Collect SNS topics."""

    def collect(self, job: CollectionJob) -> CollectorResult:
        from ..discovery import process_sns_topic

        result = CollectorResult()
        region = job.region

        try:
            client = self._get_client('sns', region, job.session)

            topic_arns: List[str] = []
            paginator = client.get_paginator('list_topics')
            for page in self._call_with_retry(lambda: list(paginator.paginate())):
                for t in page.get('Topics', []):
                    topic_arns.append(t['TopicArn'])

            for topic_arn in topic_arns:
                try:
                    attrs_resp = self._call_with_retry(
                        client.get_topic_attributes, TopicArn=topic_arn
                    )
                    attrs = attrs_resp.get('Attributes', {})
                    attrs['TopicArn'] = topic_arn

                    tags_resp = self._call_with_retry(
                        client.list_tags_for_resource, ResourceArn=topic_arn
                    )
                    tag_list = tags_resp.get('Tags', [])

                    resource = process_sns_topic(attrs, tag_list, region)
                    if resource:
                        self._extract_relationships(resource, result)
                        result.resources.append(resource)
                except Exception as e:
                    result.errors.append(f"Error processing SNS topic {topic_arn.split(':')[-1]}: {e}")

        except ClientError as e:
            if self._is_permission_error(e):
                result.errors.append(f"No permission to list SNS topics in {region}")
                self._record_permission_error(result, region, "SNS topics", e, job.account_id)
            else:
                raise

        return result


# ---------------------------------------------------------------------------
# SQS
# ---------------------------------------------------------------------------

class SQSCollector(ServiceCollector):
    """Collect SQS queues."""

    def collect(self, job: CollectionJob) -> CollectorResult:
        from ..discovery import process_sqs_queue

        result = CollectorResult()
        region = job.region

        try:
            client = self._get_client('sqs', region, job.session)

            queue_urls: List[str] = []
            paginator = client.get_paginator('list_queues')
            for page in self._call_with_retry(lambda: list(paginator.paginate())):
                queue_urls.extend(page.get('QueueUrls', []))

            for queue_url in queue_urls:
                try:
                    attrs_resp = self._call_with_retry(
                        client.get_queue_attributes,
                        QueueUrl=queue_url,
                        AttributeNames=['All'],
                    )
                    attrs = attrs_resp.get('Attributes', {})

                    tags_resp = self._call_with_retry(
                        client.list_queue_tags, QueueUrl=queue_url
                    )
                    tag_dict = tags_resp.get('Tags', {})

                    resource = process_sqs_queue(queue_url, attrs, tag_dict, region)
                    if resource:
                        self._extract_relationships(resource, result)
                        result.resources.append(resource)
                except Exception as e:
                    result.errors.append(f"Error processing SQS queue {queue_url.split('/')[-1]}: {e}")

        except ClientError as e:
            if self._is_permission_error(e):
                result.errors.append(f"No permission to list SQS queues in {region}")
                self._record_permission_error(result, region, "SQS queues", e, job.account_id)
            else:
                raise

        return result


# ---------------------------------------------------------------------------
# CloudWatch (Alarms + Log Groups)
# ---------------------------------------------------------------------------

class CloudWatchCollector(ServiceCollector):
    """Collect CloudWatch alarms and Log Groups."""

    def collect(self, job: CollectionJob) -> CollectorResult:
        from ..discovery import process_cloudwatch_alarm, process_log_group

        result = CollectorResult()
        region = job.region

        # --- Alarms ---
        try:
            client = self._get_client('cloudwatch', region, job.session)

            alarms_data = []
            paginator = client.get_paginator('describe_alarms')
            for page in self._call_with_retry(lambda: list(paginator.paginate())):
                alarms_data.extend(page.get('MetricAlarms', []))

            for alarm in alarms_data:
                try:
                    alarm_arn = alarm.get('AlarmArn', '')
                    tags_resp = self._call_with_retry(
                        client.list_tags_for_resource, ResourceARN=alarm_arn
                    )
                    tag_list = tags_resp.get('Tags', [])

                    resource = process_cloudwatch_alarm(alarm, tag_list, region)
                    if resource:
                        self._extract_relationships(resource, result)
                        result.resources.append(resource)
                except Exception as e:
                    result.errors.append(f"Error processing alarm {alarm.get('AlarmName', '?')}: {e}")

        except ClientError as e:
            if self._is_permission_error(e):
                result.errors.append(f"No permission to describe CloudWatch alarms in {region}")
                self._record_permission_error(result, region, "CloudWatch alarms", e, job.account_id)
            else:
                raise

        # --- Log Groups ---
        try:
            logs_client = self._get_client('logs', region, job.session)

            log_groups_data = []
            paginator = logs_client.get_paginator('describe_log_groups')
            for page in self._call_with_retry(lambda: list(paginator.paginate())):
                log_groups_data.extend(page.get('logGroups', []))

            for lg in log_groups_data:
                try:
                    lg_arn = lg.get('arn', '')
                    # Strip trailing :*
                    if lg_arn.endswith(':*'):
                        lg_arn = lg_arn[:-2]
                    tags_resp = self._call_with_retry(
                        logs_client.list_tags_for_resource, resourceArn=lg_arn
                    )
                    tag_dict = tags_resp.get('tags', {})

                    resource = process_log_group(lg, tag_dict, region)
                    if resource:
                        self._extract_relationships(resource, result)
                        result.resources.append(resource)
                except Exception as e:
                    result.errors.append(f"Error processing log group {lg.get('logGroupName', '?')}: {e}")

        except ClientError as e:
            if self._is_permission_error(e):
                result.errors.append(f"No permission to describe CloudWatch Log Groups in {region}")
                self._record_permission_error(result, region, "CloudWatch Log Groups", e, job.account_id)
            else:
                raise

        return result


# ---------------------------------------------------------------------------
# EKS
# ---------------------------------------------------------------------------

class EKSCollector(ServiceCollector):
    """Collect EKS clusters."""

    def collect(self, job: CollectionJob) -> CollectorResult:
        from ..discovery import process_eks_cluster

        result = CollectorResult()
        region = job.region

        try:
            client = self._get_client('eks', region, job.session)

            cluster_names: List[str] = []
            paginator = client.get_paginator('list_clusters')
            for page in self._call_with_retry(lambda: list(paginator.paginate())):
                cluster_names.extend(page.get('clusters', []))

            for name in cluster_names:
                try:
                    resp = self._call_with_retry(
                        client.describe_cluster, name=name
                    )
                    cluster_data = resp.get('cluster', {})
                    resource = process_eks_cluster(cluster_data, region)
                    if resource:
                        self._extract_relationships(resource, result)
                        result.resources.append(resource)
                except Exception as e:
                    result.errors.append(f"Error processing EKS cluster {name}: {e}")

        except ClientError as e:
            if self._is_permission_error(e):
                result.errors.append(f"No permission to list EKS clusters in {region}")
                self._record_permission_error(result, region, "EKS clusters", e, job.account_id)
            else:
                raise

        return result


# ---------------------------------------------------------------------------
# ElastiCache
# ---------------------------------------------------------------------------

class ElastiCacheCollector(ServiceCollector):
    """Collect ElastiCache clusters."""

    def collect(self, job: CollectionJob) -> CollectorResult:
        from ..discovery import process_elasticache_cluster

        result = CollectorResult()
        region = job.region

        try:
            client = self._get_client('elasticache', region, job.session)

            clusters_data = []
            paginator = client.get_paginator('describe_cache_clusters')
            for page in self._call_with_retry(lambda: list(paginator.paginate())):
                clusters_data.extend(page.get('CacheClusters', []))

            for cluster in clusters_data:
                try:
                    cluster_arn = cluster.get('ARN', '')
                    tags_resp = self._call_with_retry(
                        client.list_tags_for_resource, ResourceName=cluster_arn
                    )
                    tag_list = tags_resp.get('TagList', [])

                    resource = process_elasticache_cluster(cluster, tag_list, region)
                    if resource:
                        self._extract_relationships(resource, result)
                        result.resources.append(resource)
                except Exception as e:
                    result.errors.append(f"Error processing ElastiCache cluster {cluster.get('CacheClusterId', '?')}: {e}")

        except ClientError as e:
            if self._is_permission_error(e):
                result.errors.append(f"No permission to describe ElastiCache clusters in {region}")
                self._record_permission_error(result, region, "ElastiCache clusters", e, job.account_id)
            else:
                raise

        return result


# ---------------------------------------------------------------------------
# VPC (VPCs, Subnets, Security Groups)
# ---------------------------------------------------------------------------

class VPCCollector(ServiceCollector):
    """Collect VPCs, Subnets, and Security Groups."""

    def collect(self, job: CollectionJob) -> CollectorResult:
        from ..discovery import process_vpc, process_subnet, process_security_group

        result = CollectorResult()
        region = job.region

        # --- VPCs ---
        try:
            ec2_client = self._get_client('ec2', region, job.session)
            vpcs_data = []
            paginator = ec2_client.get_paginator('describe_vpcs')
            for page in self._call_with_retry(lambda: list(paginator.paginate())):
                vpcs_data.extend(page.get('Vpcs', []))

            for vpc in vpcs_data:
                try:
                    resource = process_vpc(vpc, region)
                    if resource:
                        self._extract_relationships(resource, result)
                        result.resources.append(resource)
                except Exception as e:
                    result.errors.append(f"Error processing VPC {vpc.get('VpcId', '?')}: {e}")

        except ClientError as e:
            if self._is_permission_error(e):
                result.errors.append(f"No permission to describe VPCs in {region}")
                self._record_permission_error(result, region, "VPCs", e, job.account_id)
            else:
                raise

        # --- Subnets ---
        try:
            ec2_client = self._get_client('ec2', region, job.session)
            subnets_data = []
            paginator = ec2_client.get_paginator('describe_subnets')
            for page in self._call_with_retry(lambda: list(paginator.paginate())):
                subnets_data.extend(page.get('Subnets', []))

            for subnet in subnets_data:
                try:
                    resource = process_subnet(subnet, region)
                    if resource:
                        self._extract_relationships(resource, result)
                        result.resources.append(resource)
                except Exception as e:
                    result.errors.append(f"Error processing Subnet {subnet.get('SubnetId', '?')}: {e}")

        except ClientError as e:
            if self._is_permission_error(e):
                result.errors.append(f"No permission to describe Subnets in {region}")
                self._record_permission_error(result, region, "Subnets", e, job.account_id)
            else:
                raise

        # --- Security Groups ---
        try:
            ec2_client = self._get_client('ec2', region, job.session)
            sgs_data = []
            paginator = ec2_client.get_paginator('describe_security_groups')
            for page in self._call_with_retry(lambda: list(paginator.paginate())):
                sgs_data.extend(page.get('SecurityGroups', []))

            for sg in sgs_data:
                try:
                    resource = process_security_group(sg, region)
                    if resource:
                        self._extract_relationships(resource, result)
                        result.resources.append(resource)
                except Exception as e:
                    result.errors.append(f"Error processing SG {sg.get('GroupId', '?')}: {e}")

        except ClientError as e:
            if self._is_permission_error(e):
                result.errors.append(f"No permission to describe Security Groups in {region}")
                self._record_permission_error(result, region, "Security Groups", e, job.account_id)
            else:
                raise

        return result


# ---------------------------------------------------------------------------
# IAM
# ---------------------------------------------------------------------------

class IAMCollector(ServiceCollector):
    """Collect IAM Roles (global service)."""

    def collect(self, job: CollectionJob) -> CollectorResult:
        from ..discovery import process_iam_role

        result = CollectorResult()

        try:
            iam_client = self._get_client('iam', None, job.session)
            roles_data = []
            paginator = iam_client.get_paginator('list_roles')
            for page in self._call_with_retry(lambda: list(paginator.paginate())):
                roles_data.extend(page.get('Roles', []))

            for role in roles_data:
                try:
                    resource = process_iam_role(role)
                    if resource:
                        self._extract_relationships(resource, result)
                        result.resources.append(resource)
                except Exception as e:
                    result.errors.append(f"Error processing IAM Role {role.get('RoleName', '?')}: {e}")

        except ClientError as e:
            if self._is_permission_error(e):
                result.errors.append("No permission to list IAM roles")
                self._record_permission_error(result, "global", "IAM roles", e, job.account_id)
            else:
                raise

        return result


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

COLLECTORS: Dict[str, ServiceCollector] = {
    'ec2': EC2Collector(),
    's3': S3Collector(),
    'lambda': LambdaCollector(),
    'rds': RDSCollector(),
    'dynamodb': DynamoDBCollector(),
    'ecs': ECSCollector(),
    'elb': ELBCollector(),
    'sns': SNSCollector(),
    'sqs': SQSCollector(),
    'cloudwatch': CloudWatchCollector(),
    'eks': EKSCollector(),
    'elasticache': ElastiCacheCollector(),
    'vpc': VPCCollector(),
    'iam': IAMCollector(),
}
