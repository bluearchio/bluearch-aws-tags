#!/usr/bin/env python3
"""Seed the SQLite database with safe mock data for Playwright video recordings.

Uses only generic names, the AWS example account ID (123456789012),
and demo-safe tags. No real AWS data appears in recordings.
"""

import json
import sys
import uuid
from datetime import datetime, timedelta

sys.path.insert(0, '.')

from tag_manager_cli.database.connection import get_db_session
from tag_manager_cli.database.models import Resource

MOCK_ACCOUNT = '123456789012'
MOCK_REGION = 'us-east-1'
NOW = datetime.utcnow()


def make_resource(
    resource_id: str,
    resource_type: str,
    service_name: str,
    arn: str,
    metadata: dict,
    tags: dict | None = None,
    created_at: datetime | None = None,
) -> Resource:
    return Resource(
        id=str(uuid.uuid4()),
        resource_arn=arn,
        resource_type=resource_type,
        service_name=service_name,
        region=MOCK_REGION,
        account_id=MOCK_ACCOUNT,
        resource_id=resource_id,
        created_at=created_at or (NOW - timedelta(days=30)),
        discovered_at=NOW,
        last_scanned_at=NOW,
        current_tags=json.dumps(tags or {}),
        metadata_json=json.dumps(metadata),
        lifecycle_state='active',
    )


def demo_resources() -> list[Resource]:
    """Create a diverse set of mock resources for video demos."""
    resources = []

    # --- EC2 Instances ---
    ec2_instances = [
        ('i-0demo001websvr01', 'demo-web-server', 'production', 't3.medium', 'running'),
        ('i-0demo002apisvr01', 'demo-api-server', 'production', 't3.large', 'running'),
        ('i-0demo003staging01', 'staging-web-server', 'staging', 't3.small', 'running'),
        ('i-0demo004devbox01', 'dev-sandbox-box', 'demo', 't3.micro', 'running'),
        ('i-0demo005legacy01', 'legacy-batch-worker', 'demo', 't2.micro', 'running'),
        ('i-0demo006test0101', 'test-runner-01', 'demo', 't2.small', 'stopped'),
        ('i-0demo007testbox1', 'test-environment', 'demo', 'm4.large', 'stopped'),
    ]

    for rid, name, env, itype, state in ec2_instances:
        resources.append(make_resource(
            resource_id=rid,
            resource_type='AWS::EC2::Instance',
            service_name='ec2',
            arn=f'arn:aws:ec2:{MOCK_REGION}:{MOCK_ACCOUNT}:instance/{rid}',
            tags={'Name': name, 'Environment': env, 'Team': 'platform', 'Project': 'acme-app'},
            metadata={
                'instance_type': itype,
                'state': state,
                'vpc_id': 'vpc-0abcdef1234567890',
                'subnet_id': 'subnet-0abcdef1234567890',
                'private_ip': f'10.0.1.{10 + len(resources)}',
            },
        ))

    # --- Lambda Functions ---
    lambdas = [
        ('demo-api-handler', 'python3.12', 256, 'production'),
        ('demo-image-processor', 'python3.11', 512, 'production'),
        ('demo-event-listener', 'nodejs20.x', 128, 'production'),
        ('staging-data-pipeline', 'python3.9', 256, 'staging'),
        ('dev-webhook-handler', 'python3.8', 128, 'demo'),
        ('test-auth-validator', 'python3.7', 128, 'demo'),
        ('legacy-report-gen', 'python3.6', 256, 'demo'),
        ('demo-notification-sender', 'nodejs18.x', 128, 'demo'),
    ]

    for fname, runtime, mem, env in lambdas:
        resources.append(make_resource(
            resource_id=fname,
            resource_type='AWS::Lambda::Function',
            service_name='lambda',
            arn=f'arn:aws:lambda:{MOCK_REGION}:{MOCK_ACCOUNT}:function:{fname}',
            tags={'Environment': env, 'Team': 'platform', 'Project': 'acme-app'},
            metadata={
                'runtime': runtime,
                'memory_size': mem,
                'timeout': 30,
                'handler': 'index.handler',
                'last_modified': (NOW - timedelta(days=15)).isoformat(),
            },
        ))

    # --- S3 Buckets ---
    buckets = [
        ('acme-app-assets-prod', 'production'),
        ('acme-app-logs-staging', 'staging'),
        ('acme-app-backups', 'production'),
        ('demo-data-lake', 'demo'),
        ('demo-temp-uploads', 'demo'),
    ]

    for bname, env in buckets:
        resources.append(make_resource(
            resource_id=bname,
            resource_type='AWS::S3::Bucket',
            service_name='s3',
            arn=f'arn:aws:s3:::{bname}',
            tags={'Environment': env, 'Team': 'platform', 'Project': 'acme-app'},
            metadata={
                'creation_date': (NOW - timedelta(days=90)).isoformat(),
                'versioning': 'Enabled' if env == 'production' else 'Suspended',
                'encryption': 'AES256',
            },
        ))

    # --- RDS Instances ---
    rds_instances = [
        ('demo-primary-db', 'postgres', '15.4', 'db.r6g.large', True, True, False),
        ('demo-dev-database', 'mysql', '8.0.35', 'db.m5.large', False, False, True),
        ('demo-legacy-db', 'postgres', '13.9', 'db.m4.large', True, False, False),
    ]

    for rname, engine, ver, cls, multi_az, del_prot, public in rds_instances:
        env = 'production' if multi_az else 'demo'
        resources.append(make_resource(
            resource_id=rname,
            resource_type='AWS::RDS::DBInstance',
            service_name='rds',
            arn=f'arn:aws:rds:{MOCK_REGION}:{MOCK_ACCOUNT}:db:{rname}',
            tags={'Name': rname, 'Environment': env, 'Team': 'platform'},
            metadata={
                'engine': engine,
                'engine_version': ver,
                'instance_class': cls,
                'status': 'available',
                'multi_az': multi_az,
                'storage_gb': 100,
                'storage_encrypted': multi_az,
                'publicly_accessible': public,
                'storage_type': 'gp3' if multi_az else 'gp2',
                'deletion_protection': del_prot,
                'backup_retention_period': 14 if multi_az else 0,
            },
        ))

    # --- EBS Volumes ---
    volumes = [
        ('vol-0demo001encrypt', 'demo-app-data', 100, 'gp3', 'in-use', True),
        ('vol-0demo002legacy1', 'demo-legacy-vol', 200, 'gp2', 'in-use', True),
        ('vol-0demo003orphan1', 'demo-orphaned-vol', 50, 'gp3', 'available', True),
        ('vol-0demo004noencr1', 'demo-unencrypted', 80, 'gp3', 'in-use', False),
    ]

    for vid, name, size, vtype, state, encrypted in volumes:
        resources.append(make_resource(
            resource_id=vid,
            resource_type='AWS::EC2::Volume',
            service_name='ec2',
            arn=f'arn:aws:ec2:{MOCK_REGION}:{MOCK_ACCOUNT}:volume/{vid}',
            tags={'Name': name, 'Environment': 'demo', 'Team': 'platform'},
            metadata={
                'size_gb': size,
                'volume_type': vtype,
                'state': state,
                'availability_zone': f'{MOCK_REGION}a',
                'encrypted': encrypted,
                'iops': 3000,
            },
        ))

    return resources


def main():
    all_resources = demo_resources()
    print(f"Seeding {len(all_resources)} mock resources for video demos...")

    with get_db_session() as session:
        # Remove old demo data first
        deleted = session.query(Resource).filter(
            Resource.account_id == MOCK_ACCOUNT
        ).delete()
        if deleted:
            print(f"  Cleared {deleted} existing mock resources")

        for resource in all_resources:
            session.add(resource)
            print(f"  ADD: {resource.resource_id} ({resource.service_name})")

        session.commit()
        print(f"\nSeeded {len(all_resources)} resources for account {MOCK_ACCOUNT}")


if __name__ == '__main__':
    main()
