"""Mock AWS services for testing without real AWS credentials."""

import json
import time
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from unittest.mock import MagicMock, patch


class MockAWSClient:
    """Base mock AWS client with common functionality."""
    
    def __init__(self, service_name: str, region_name: str = 'us-east-1'):
        self.service_name = service_name
        self.region_name = region_name
        self._call_count = 0
    
    def _log_call(self, method_name: str, **kwargs):
        """Log API calls for debugging."""
        self._call_count += 1
        print(f"[MOCK AWS] {self.service_name}.{method_name}() call #{self._call_count}")


class MockEC2Client(MockAWSClient):
    """Mock EC2 client with test data."""
    
    def __init__(self, region_name: str = 'us-east-1'):
        super().__init__('ec2', region_name)
        self.instances = self._generate_test_instances()
        self.volumes = self._generate_test_volumes()
    
    def describe_instances(self, **kwargs):
        """Mock describe_instances API call."""
        self._log_call('describe_instances', **kwargs)
        
        return {
            'Reservations': [
                {
                    'Instances': self.instances
                }
            ]
        }
    
    def describe_volumes(self, **kwargs):
        """Mock describe_volumes API call."""
        self._log_call('describe_volumes', **kwargs)
        
        return {
            'Volumes': self.volumes
        }
    
    def _generate_test_instances(self) -> List[Dict[str, Any]]:
        """Generate test EC2 instances."""
        instances = []
        
        for i in range(3):
            instance_id = f"i-{hex(int(time.time() * 1000) + i)[2:]}"
            instances.append({
                'InstanceId': instance_id,
                'InstanceType': 't3.micro' if i == 0 else 't3.small',
                'State': {'Name': 'running' if i < 2 else 'stopped'},
                'LaunchTime': datetime.utcnow() - timedelta(days=i + 1),
                'VpcId': f'vpc-{hex(12345 + i)[2:]}',
                'SubnetId': f'subnet-{hex(67890 + i)[2:]}',
                'PublicIpAddress': f'54.{i+1}.{i+2}.{i+3}',
                'PrivateIpAddress': f'10.0.{i+1}.{i+10}',
                'OwnerId': '123456789012',
                'Tags': [
                    {'Key': 'Name', 'Value': f'test-instance-{i+1}'},
                    {'Key': 'Environment', 'Value': 'Test' if i < 2 else 'Development'},
                    {'Key': 'Project', 'Value': 'TagManagerCLI'},
                ]
            })
        
        return instances
    
    def _generate_test_volumes(self) -> List[Dict[str, Any]]:
        """Generate test EBS volumes."""
        volumes = []
        
        for i in range(2):
            volume_id = f"vol-{hex(int(time.time() * 1000) + i)[2:]}"
            volumes.append({
                'VolumeId': volume_id,
                'Size': 20 if i == 0 else 100,
                'VolumeType': 'gp3',
                'State': 'in-use',
                'CreateTime': datetime.utcnow() - timedelta(days=i + 1),
                'AvailabilityZone': f'{self.region_name}a',
                'Encrypted': True if i == 1 else False,
                'OwnerId': '123456789012',
                'Tags': [
                    {'Key': 'Name', 'Value': f'test-volume-{i+1}'},
                    {'Key': 'Environment', 'Value': 'Test'},
                ]
            })
        
        return volumes


class MockS3Client(MockAWSClient):
    """Mock S3 client with test data."""
    
    def __init__(self, region_name: str = 'us-east-1'):
        super().__init__('s3', region_name)
        self.buckets = self._generate_test_buckets()
    
    def list_buckets(self, **kwargs):
        """Mock list_buckets API call."""
        self._log_call('list_buckets', **kwargs)
        
        return {
            'Buckets': self.buckets
        }
    
    def get_bucket_location(self, Bucket: str, **kwargs):
        """Mock get_bucket_location API call."""
        self._log_call('get_bucket_location', Bucket=Bucket, **kwargs)
        
        # Return different regions for different buckets
        if 'west' in Bucket:
            return {'LocationConstraint': 'us-west-2'}
        elif 'eu' in Bucket:
            return {'LocationConstraint': 'eu-west-1'}
        else:
            return {'LocationConstraint': None}  # us-east-1
    
    def get_bucket_tagging(self, Bucket: str, **kwargs):
        """Mock get_bucket_tagging API call."""
        self._log_call('get_bucket_tagging', Bucket=Bucket, **kwargs)
        
        # Return different tags for different buckets
        if 'data' in Bucket:
            return {
                'TagSet': [
                    {'Key': 'Environment', 'Value': 'Production'},
                    {'Key': 'DataClassification', 'Value': 'Sensitive'},
                    {'Key': 'Project', 'Value': 'TagManagerCLI'},
                ]
            }
        elif 'logs' in Bucket:
            return {
                'TagSet': [
                    {'Key': 'Environment', 'Value': 'Production'},
                    {'Key': 'Purpose', 'Value': 'Logging'},
                    {'Key': 'Retention', 'Value': '90days'},
                ]
            }
        else:
            return {
                'TagSet': [
                    {'Key': 'Environment', 'Value': 'Test'},
                    {'Key': 'Project', 'Value': 'TagManagerCLI'},
                ]
            }
    
    def get_bucket_acl(self, Bucket: str, **kwargs):
        """Mock get_bucket_acl API call."""
        self._log_call('get_bucket_acl', Bucket=Bucket, **kwargs)
        
        return {
            'Owner': {
                'ID': '123456789012canonical-user-id',
                'DisplayName': 'test-user'
            }
        }
    
    def _generate_test_buckets(self) -> List[Dict[str, Any]]:
        """Generate test S3 buckets."""
        buckets = [
            {
                'Name': 'test-data-bucket-12345',
                'CreationDate': datetime.utcnow() - timedelta(days=30)
            },
            {
                'Name': 'test-logs-bucket-67890',
                'CreationDate': datetime.utcnow() - timedelta(days=15)
            },
            {
                'Name': 'test-backup-bucket-west',
                'CreationDate': datetime.utcnow() - timedelta(days=7)
            }
        ]
        
        return buckets


class MockLambdaClient(MockAWSClient):
    """Mock Lambda client with test data."""
    
    def __init__(self, region_name: str = 'us-east-1'):
        super().__init__('lambda', region_name)
        self.functions = self._generate_test_functions()
    
    def list_functions(self, **kwargs):
        """Mock list_functions API call."""
        self._log_call('list_functions', **kwargs)
        
        return {
            'Functions': self.functions
        }
    
    def list_tags(self, Resource: str, **kwargs):
        """Mock list_tags API call."""
        self._log_call('list_tags', Resource=Resource, **kwargs)
        
        # Return different tags based on function name
        if 'processor' in Resource:
            return {
                'Tags': {
                    'Environment': 'Production',
                    'Function': 'DataProcessing',
                    'Team': 'DataEngineering'
                }
            }
        elif 'trigger' in Resource:
            return {
                'Tags': {
                    'Environment': 'Development', 
                    'Function': 'EventTrigger',
                    'Team': 'Backend'
                }
            }
        else:
            return {
                'Tags': {
                    'Environment': 'Test',
                    'Project': 'TagManagerCLI'
                }
            }
    
    def _generate_test_functions(self) -> List[Dict[str, Any]]:
        """Generate test Lambda functions."""
        functions = []
        
        function_names = ['data-processor', 'event-trigger', 'health-checker']
        
        for i, name in enumerate(function_names):
            function_arn = f"arn:aws:lambda:{self.region_name}:123456789012:function:{name}"
            functions.append({
                'FunctionName': name,
                'FunctionArn': function_arn,
                'Runtime': 'python3.9',
                'Handler': f'{name.replace("-", "_")}.handler',
                'CodeSize': 1024 * (i + 1),
                'Timeout': 30 + (i * 30),
                'MemorySize': 128 * (2 ** i),
                'LastModified': (datetime.utcnow() - timedelta(days=i)).isoformat() + 'Z'
            })
        
        return functions


class MockAWSSetup:
    """Setup and manage mock AWS services."""
    
    def __init__(self):
        self.patches = []
        self.mock_clients = {}
        self.is_enabled = False
    
    def enable_mocks(self, services: Optional[List[str]] = None):
        """Enable mock AWS services."""
        if services is None:
            services = ['ec2', 's3', 'lambda']
        
        print(f"[MOCK AWS] Enabling mock services: {', '.join(services)}")
        
        # Mock boto3.client to return our mock clients
        def mock_boto3_client(service_name, region_name='us-east-1', region=None, **kwargs):
            # Use region parameter if provided, fallback to region_name
            actual_region = region or region_name
            
            if service_name == 'ec2' and 'ec2' in services:
                return MockEC2Client(actual_region)
            elif service_name == 's3' and 's3' in services:
                return MockS3Client(actual_region)
            elif service_name == 'lambda' and 'lambda' in services:
                return MockLambdaClient(actual_region)
            else:
                # For services not mocked, return a basic mock
                return MagicMock()
        
        # Patch boto3.client
        import boto3
        boto3_patch = patch('boto3.client', side_effect=mock_boto3_client)
        boto3_patch.start()
        self.patches.append(boto3_patch)
        
        # Also patch aws_auth.get_client if it exists
        try:
            from ..utils.aws_auth import aws_auth
            aws_auth_patch = patch.object(aws_auth, 'get_client', side_effect=mock_boto3_client)
            aws_auth_patch.start()
            self.patches.append(aws_auth_patch)
        except ImportError:
            pass
        
        self.is_enabled = True
        print("[MOCK AWS] Mock services enabled successfully")
    
    def disable_mocks(self):
        """Disable mock AWS services."""
        print("[MOCK AWS] Disabling mock services...")
        
        for patch_obj in self.patches:
            patch_obj.stop()
        
        self.patches.clear()
        self.mock_clients.clear()
        self.is_enabled = False
        
        print("[MOCK AWS] Mock services disabled")
    
    def get_mock_statistics(self) -> Dict[str, Any]:
        """Get statistics about mock service usage."""
        stats = {
            'enabled': self.is_enabled,
            'services_mocked': len(self.mock_clients),
            'total_api_calls': sum(
                getattr(client, '_call_count', 0) 
                for client in self.mock_clients.values()
            )
        }
        
        return stats


# Global mock setup instance
mock_aws = MockAWSSetup()


def enable_aws_mocks(services: Optional[List[str]] = None):
    """Enable AWS mocking for testing."""
    mock_aws.enable_mocks(services)


def disable_aws_mocks():
    """Disable AWS mocking."""
    mock_aws.disable_mocks()


def is_mocking_enabled() -> bool:
    """Check if AWS mocking is currently enabled."""
    return mock_aws.is_enabled


def get_mock_stats() -> Dict[str, Any]:
    """Get mock service statistics."""
    return mock_aws.get_mock_statistics()