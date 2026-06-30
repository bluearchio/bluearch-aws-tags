#!/usr/bin/env python3
"""Insert realistic mock AWS resources into the database for evaluator testing.

Creates mock ec2_instance, ec2_volume, and rds_instance resources with metadata
designed to trigger (and pass) all misconfiguration evaluators.
"""

import json
import sys
import uuid
from datetime import datetime, timedelta

# Add parent dir to path for imports
sys.path.insert(0, '.')

from tag_manager_cli.database.connection import get_db_session
from tag_manager_cli.database.models import Resource

MOCK_ACCOUNT = '123456789012'
MOCK_REGION = 'us-east-1'
NOW = datetime.utcnow()


def make_resource(
    resource_id: str,
    resource_type: str,  # CloudFormation type
    service_name: str,
    arn: str,
    metadata: dict,
    tags: dict | None = None,
    created_at: datetime | None = None,
) -> Resource:
    """Create a Resource ORM object with realistic fields."""
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


def ec2_instances() -> list[Resource]:
    """Create mock EC2 instances -- 1 previous-gen (failing), 1 current-gen (passing)."""
    return [
        # FAILS: Previous-generation instance type (t2.micro)
        # Triggers: PREVIOUS_GEN_INSTANCE (030f361e-eb21-4382-8d26-fcd86f47c8d5)
        make_resource(
            resource_id='i-0mock001prevgen01',
            resource_type='AWS::EC2::Instance',
            service_name='ec2',
            arn=f'arn:aws:ec2:{MOCK_REGION}:{MOCK_ACCOUNT}:instance/i-0mock001prevgen01',
            tags={'Name': 'mock-legacy-webserver', 'Environment': 'staging'},
            metadata={
                'instance_type': 't2.micro',
                'state': 'running',
                'vpc_id': 'vpc-0abcdef1234567890',
                'subnet_id': 'subnet-0abcdef1234567890',
                'public_ip': '54.123.45.67',
                'private_ip': '10.0.1.100',
            },
        ),
        # PASSES: Current-generation instance type (t3.micro)
        make_resource(
            resource_id='i-0mock002current01',
            resource_type='AWS::EC2::Instance',
            service_name='ec2',
            arn=f'arn:aws:ec2:{MOCK_REGION}:{MOCK_ACCOUNT}:instance/i-0mock002current01',
            tags={'Name': 'mock-modern-webserver', 'Environment': 'production'},
            metadata={
                'instance_type': 't3.micro',
                'state': 'running',
                'vpc_id': 'vpc-0abcdef1234567890',
                'subnet_id': 'subnet-0abcdef1234567891',
                'public_ip': None,
                'private_ip': '10.0.2.100',
            },
        ),
    ]


def ebs_volumes() -> list[Resource]:
    """Create mock EBS volumes -- 3 failing (one per evaluator), 1 clean."""
    return [
        # FAILS: Unencrypted volume
        # Triggers: UNENCRYPTED_VOLUME (249dd667-4b1e-4200-bec5-19c6c718f958)
        make_resource(
            resource_id='vol-0mock001unencr01',
            resource_type='AWS::EC2::Volume',
            service_name='ec2',
            arn=f'arn:aws:ec2:{MOCK_REGION}:{MOCK_ACCOUNT}:volume/vol-0mock001unencr01',
            tags={'Name': 'mock-unencrypted-data-vol', 'Environment': 'dev'},
            metadata={
                'size_gb': 100,
                'volume_type': 'gp3',
                'state': 'in-use',
                'availability_zone': f'{MOCK_REGION}a',
                'encrypted': False,
                'iops': 3000,
                'throughput': 125,
            },
        ),
        # FAILS: Unattached volume (state=available)
        # Triggers: UNATTACHED_VOLUME (033ae438-4620-4f65-80cd-776fd0102bb0)
        make_resource(
            resource_id='vol-0mock002unatch01',
            resource_type='AWS::EC2::Volume',
            service_name='ec2',
            arn=f'arn:aws:ec2:{MOCK_REGION}:{MOCK_ACCOUNT}:volume/vol-0mock002unatch01',
            tags={'Name': 'mock-orphaned-volume', 'Environment': 'staging'},
            metadata={
                'size_gb': 50,
                'volume_type': 'gp3',
                'state': 'available',
                'availability_zone': f'{MOCK_REGION}b',
                'encrypted': True,
                'iops': 3000,
                'throughput': 125,
            },
        ),
        # FAILS: Previous-gen volume type (gp2)
        # Triggers: PREVIOUS_GEN_VOLUME_TYPE (0f5cfb3e-623b-4140-a5ed-db4b5be406f8)
        make_resource(
            resource_id='vol-0mock003prevgn01',
            resource_type='AWS::EC2::Volume',
            service_name='ec2',
            arn=f'arn:aws:ec2:{MOCK_REGION}:{MOCK_ACCOUNT}:volume/vol-0mock003prevgn01',
            tags={'Name': 'mock-legacy-storage', 'Environment': 'production'},
            metadata={
                'size_gb': 200,
                'volume_type': 'gp2',
                'state': 'in-use',
                'availability_zone': f'{MOCK_REGION}c',
                'encrypted': True,
                'iops': 600,
                'throughput': None,
            },
        ),
        # PASSES: Modern encrypted in-use gp3 volume
        make_resource(
            resource_id='vol-0mock004clean01',
            resource_type='AWS::EC2::Volume',
            service_name='ec2',
            arn=f'arn:aws:ec2:{MOCK_REGION}:{MOCK_ACCOUNT}:volume/vol-0mock004clean01',
            tags={'Name': 'mock-production-root', 'Environment': 'production'},
            metadata={
                'size_gb': 80,
                'volume_type': 'gp3',
                'state': 'in-use',
                'availability_zone': f'{MOCK_REGION}a',
                'encrypted': True,
                'iops': 3000,
                'throughput': 125,
            },
        ),
    ]


def rds_instances() -> list[Resource]:
    """Create mock RDS instances -- 2 failing (different evaluators), 1 clean."""
    return [
        # FAILS: Multiple misconfigs (unencrypted, no multi-az, public, gp2, no del prot, no backups)
        # Triggers: UNENCRYPTED_RDS, NO_MULTI_AZ, PUBLICLY_ACCESSIBLE_RDS,
        #           GP2_STORAGE, NO_DELETION_PROTECTION_RDS, NO_BACKUPS_RDS
        make_resource(
            resource_id='mock-insecure-db-01',
            resource_type='AWS::RDS::DBInstance',
            service_name='rds',
            arn=f'arn:aws:rds:{MOCK_REGION}:{MOCK_ACCOUNT}:db:mock-insecure-db-01',
            tags={'Name': 'mock-insecure-db', 'Environment': 'dev'},
            metadata={
                'engine': 'mysql',
                'engine_version': '8.0.35',
                'instance_class': 'db.m5.large',
                'status': 'available',
                'multi_az': False,
                'storage_gb': 100,
                'storage_encrypted': False,
                'publicly_accessible': True,
                'storage_type': 'gp2',
                'deletion_protection': False,
                'backup_retention_period': 0,
            },
        ),
        # FAILS: Previous-generation instance class only
        # Triggers: PREVIOUS_GEN_RDS (a1f5645b-0bce-475a-b036-d34b9abd5dbb)
        make_resource(
            resource_id='mock-prevgen-db-01',
            resource_type='AWS::RDS::DBInstance',
            service_name='rds',
            arn=f'arn:aws:rds:{MOCK_REGION}:{MOCK_ACCOUNT}:db:mock-prevgen-db-01',
            tags={'Name': 'mock-legacy-postgres', 'Environment': 'staging'},
            metadata={
                'engine': 'postgres',
                'engine_version': '15.4',
                'instance_class': 'db.m4.large',
                'status': 'available',
                'multi_az': True,
                'storage_gb': 200,
                'storage_encrypted': True,
                'publicly_accessible': False,
                'storage_type': 'gp3',
                'deletion_protection': True,
                'backup_retention_period': 7,
            },
        ),
        # PASSES: Fully compliant, current-gen RDS instance
        make_resource(
            resource_id='mock-secure-db-01',
            resource_type='AWS::RDS::DBInstance',
            service_name='rds',
            arn=f'arn:aws:rds:{MOCK_REGION}:{MOCK_ACCOUNT}:db:mock-secure-db-01',
            tags={'Name': 'mock-production-aurora', 'Environment': 'production'},
            metadata={
                'engine': 'aurora-postgresql',
                'engine_version': '15.4',
                'instance_class': 'db.r6g.large',
                'status': 'available',
                'multi_az': True,
                'storage_gb': 500,
                'storage_encrypted': True,
                'publicly_accessible': False,
                'storage_type': 'aurora',
                'deletion_protection': True,
                'backup_retention_period': 14,
            },
        ),
    ]


def main():
    all_resources = ec2_instances() + ebs_volumes() + rds_instances()

    print(f"Inserting {len(all_resources)} mock resources...")

    with get_db_session() as session:
        # Check for existing mock resources to avoid duplicates
        existing = (
            session.query(Resource.resource_arn)
            .filter(Resource.account_id == MOCK_ACCOUNT)
            .all()
        )
        existing_arns = {r[0] for r in existing}

        inserted = 0
        skipped = 0
        for resource in all_resources:
            if resource.resource_arn in existing_arns:
                print(f"  SKIP (exists): {resource.resource_arn}")
                skipped += 1
                continue
            session.add(resource)
            inserted += 1
            print(f"  ADD: {resource.resource_id} ({resource.resource_type})")
            print(f"        metadata: {resource.metadata_json[:80]}...")

        session.commit()
        print(f"\nDone: {inserted} inserted, {skipped} skipped (already exist)")

        # Verify counts
        for rtype in ['AWS::EC2::Instance', 'AWS::EC2::Volume', 'AWS::RDS::DBInstance']:
            count = session.query(Resource).filter(Resource.resource_type == rtype).count()
            print(f"  {rtype}: {count} total in DB")


if __name__ == '__main__':
    main()
