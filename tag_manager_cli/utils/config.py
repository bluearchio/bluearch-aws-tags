"""DynamoDB configuration storage for Tag Manager CLI."""

import boto3
from botocore.exceptions import ClientError
from typing import Dict, Optional, Any
from rich.console import Console
import json

from .aws_auth import aws_auth
from .env_config import settings

console = Console()


class ConfigManager:
    """Manages configuration storage in DynamoDB."""
    
    def __init__(self, table_name: Optional[str] = None):
        self.table_name = table_name or f"tag-manager-config-{settings.aws_profile}"
        self.table = None
        self._initialize_table()
    
    def _initialize_table(self):
        """Initialize DynamoDB table."""
        try:
            dynamodb = aws_auth.get_resource('dynamodb')
            self.table = dynamodb.Table(self.table_name)
            
            # Check if table exists
            self.table.table_status
            console.print(f"[green]OK[/green] DynamoDB config table '{self.table_name}' ready")
            
        except ClientError as e:
            if e.response['Error']['Code'] == 'ResourceNotFoundException':
                console.print(f"[yellow]Table '{self.table_name}' not found. Creating...[/yellow]")
                self._create_table()
            else:
                console.print(f"[red]Error accessing DynamoDB: {e}[/red]")
                self.table = None
        except Exception as e:
            console.print(f"[red]Error initializing config storage: {e}[/red]")
            self.table = None
    
    def _create_table(self):
        """Create the DynamoDB configuration table."""
        try:
            dynamodb = aws_auth.get_resource('dynamodb')
            
            table = dynamodb.create_table(
                TableName=self.table_name,
                KeySchema=[
                    {
                        'AttributeName': 'config_key',
                        'KeyType': 'HASH'
                    }
                ],
                AttributeDefinitions=[
                    {
                        'AttributeName': 'config_key',
                        'AttributeType': 'S'
                    }
                ],
                BillingMode='PAY_PER_REQUEST',
                Tags=[
                    {
                        'Key': 'Application',
                        'Value': 'TagManagerCLI'
                    },
                    {
                        'Key': 'Purpose',
                        'Value': 'Configuration'
                    }
                ]
            )
            
            # Wait for table to be created
            table.wait_until_exists()
            self.table = table
            console.print(f"[green]OK[/green] Created DynamoDB table '{self.table_name}'")
            
        except ClientError as e:
            console.print(f"[red]Failed to create table: {e}[/red]")
            self.table = None
    
    def get_config(self, key: str) -> Optional[Any]:
        """Get configuration value by key."""
        if not self.table:
            return None
        
        try:
            response = self.table.get_item(Key={'config_key': key})
            if 'Item' in response:
                return json.loads(response['Item']['config_value'])
            return None
        except (ClientError, json.JSONDecodeError, Exception) as e:
            console.print(f"[red]Error getting config '{key}': {e}[/red]")
            return None
    
    def set_config(self, key: str, value: Any) -> bool:
        """Set configuration value."""
        if not self.table:
            return False
        
        try:
            self.table.put_item(
                Item={
                    'config_key': key,
                    'config_value': json.dumps(value, default=str),
                    'updated_at': str(aws_auth.get_client('sts').get_caller_identity()['UserId'])
                }
            )
            return True
        except (ClientError, json.JSONEncodeError, Exception) as e:
            console.print(f"[red]Error setting config '{key}': {e}[/red]")
            return False
    
    def delete_config(self, key: str) -> bool:
        """Delete configuration key."""
        if not self.table:
            return False
        
        try:
            self.table.delete_item(Key={'config_key': key})
            return True
        except ClientError as e:
            console.print(f"[red]Error deleting config '{key}': {e}[/red]")
            return False
    
    def list_configs(self) -> Dict[str, Any]:
        """List all configuration keys and values."""
        if not self.table:
            return {}
        
        try:
            response = self.table.scan()
            configs = {}
            for item in response.get('Items', []):
                key = item['config_key']
                value = json.loads(item['config_value'])
                configs[key] = value
            return configs
        except (ClientError, json.JSONDecodeError, Exception) as e:
            console.print(f"[red]Error listing configs: {e}[/red]")
            return {}


# Global config instance
config = ConfigManager()