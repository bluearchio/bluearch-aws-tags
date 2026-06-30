"""
OAuth Token Manager for DynamoDB

Manages Slack OAuth tokens stored in AWS DynamoDB.
Fetches, caches, and refreshes tokens for the Slack worker.
No local storage of credentials.
"""

import os
import json
import time
from typing import Dict, Optional, Any
from datetime import datetime, timedelta
import logging
import boto3
from botocore.exceptions import ClientError
from ..utils.aws_auth import aws_auth

logger = logging.getLogger(__name__)


class OAuthTokenManager:
    """Manages OAuth tokens stored in AWS DynamoDB."""
    
    def __init__(self, table_name: str = None, region: str = 'us-east-1'):
        """
        Initialize the OAuth Token Manager.
        
        Args:
            table_name: DynamoDB table name (defaults to environment variable)
            region: AWS region
        """
        # Use dev as default environment for now
        # TODO: Switch to prod when ready for production release
        env = 'dev'
        default_table = f'tag-manager-slack-tokens-{env}'
        self.table_name = table_name or os.getenv('OAUTH_TABLE_NAME', default_table)
        self.environment = env
        self.region = region
        self.dynamodb = None
        self.ssm = None
        self._token_cache = {}
        self._cache_expiry = {}
        self._cache_duration = 300  # 5 minutes cache
        
        # Initialize AWS clients
        self._init_aws_clients()
        
    def _init_aws_clients(self):
        """Initialize AWS clients with authentication."""
        try:
            # Use the global aws_auth instance
            self.dynamodb = aws_auth.get_client('dynamodb', region=self.region)
            self.ssm = aws_auth.get_client('ssm', region=self.region)
            logger.info(f"Initialized AWS clients for region {self.region}")
        except Exception as e:
            logger.error(f"Failed to initialize AWS clients: {e}")
            raise
    
    def get_slack_token(self, team_id: str = None, force_refresh: bool = False) -> Optional[str]:
        """
        Fetch Slack OAuth token from DynamoDB.
        
        Args:
            team_id: Slack team ID (optional, will fetch first available if not provided)
            force_refresh: Force fetch from DynamoDB, bypassing cache
            
        Returns:
            Slack bot token or None if not found
        """
        # Check cache first (unless force refresh)
        if not force_refresh and team_id in self._token_cache:
            if time.time() < self._cache_expiry.get(team_id, 0):
                logger.debug(f"Using cached token for team {team_id}")
                return self._token_cache[team_id]
        
        try:
            if team_id:
                # Fetch specific team token
                response = self.dynamodb.get_item(
                    TableName=self.table_name,
                    Key={'team_id': {'S': team_id}}
                )
                
                if 'Item' in response:
                    token_data = self._parse_dynamodb_item(response['Item'])
                    token = token_data.get('bot_token')
                    
                    # Cache the token
                    self._cache_token(team_id, token)
                    return token
            else:
                # Fetch first available token
                response = self.dynamodb.scan(
                    TableName=self.table_name,
                    Limit=1
                )
                
                if response.get('Items'):
                    item = response['Items'][0]
                    token_data = self._parse_dynamodb_item(item)
                    team_id = token_data.get('team_id')
                    token = token_data.get('bot_token')
                    
                    # Cache the token
                    if team_id and token:
                        self._cache_token(team_id, token)
                    return token
                    
            logger.warning(f"No Slack token found in DynamoDB table {self.table_name}")
            return None
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'ResourceNotFoundException':
                logger.error(f"DynamoDB table {self.table_name} not found")
            else:
                logger.error(f"Error fetching token from DynamoDB: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error fetching token: {e}")
            return None
    
    def get_sqs_queue_url(self, parameter_name: str = '/tag-manager/sqs-queue-url') -> Optional[str]:
        """
        Fetch SQS queue URL from AWS Systems Manager Parameter Store.
        
        Args:
            parameter_name: SSM parameter name
            
        Returns:
            SQS queue URL or None if not found
        """
        # Check cache first
        cache_key = 'sqs_queue_url'
        if cache_key in self._token_cache:
            if time.time() < self._cache_expiry.get(cache_key, 0):
                return self._token_cache[cache_key]
        
        try:
            response = self.ssm.get_parameter(
                Name=parameter_name,
                WithDecryption=True
            )
            
            queue_url = response['Parameter']['Value']
            
            # Cache the URL
            self._cache_token(cache_key, queue_url)
            return queue_url
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'ParameterNotFound':
                logger.warning(f"SSM parameter {parameter_name} not found")
                # Try environment variable as fallback
                return os.getenv('SQS_QUEUE_URL')
            else:
                logger.error(f"Error fetching SQS URL from Parameter Store: {e}")
                return None
        except Exception as e:
            logger.error(f"Unexpected error fetching SQS URL: {e}")
            return None
    
    def get_worker_configuration(self) -> Dict[str, Any]:
        """
        Fetch complete worker configuration from AWS.
        
        Returns:
            Dictionary with worker configuration:
            {
                'sqs_queue_url': 'https://sqs...',
                'slack_token': 'your-slack-bot-token',
                'team_id': 'T123456',
                'region': 'us-east-1',
                'max_messages': 1,
                'wait_time': 20
            }
        """
        config = {}
        
        # Get SQS Queue URL
        queue_url = self.get_sqs_queue_url()
        if queue_url:
            config['sqs_queue_url'] = queue_url
        else:
            # Fallback to environment variable
            config['sqs_queue_url'] = os.getenv('SQS_QUEUE_URL')
        
        # Get Slack token
        token = self.get_slack_token()
        if token:
            config['slack_token'] = token
        
        # Get additional configuration from SSM (optional)
        try:
            # Try to get worker configuration from Parameter Store
            params_to_fetch = [
                '/tag-manager/worker/region',
                '/tag-manager/worker/max-messages',
                '/tag-manager/worker/wait-time'
            ]
            
            for param_name in params_to_fetch:
                try:
                    response = self.ssm.get_parameter(Name=param_name)
                    key = param_name.split('/')[-1].replace('-', '_')
                    config[key] = response['Parameter']['Value']
                except ClientError:
                    pass  # Parameter doesn't exist, use defaults
                    
        except Exception as e:
            logger.debug(f"Could not fetch optional parameters: {e}")
        
        # Set defaults for missing configuration
        config.setdefault('region', os.getenv('AWS_REGION', 'us-east-1'))
        config.setdefault('max_messages', 1)
        config.setdefault('wait_time', 20)
        
        return config
    
    def store_slack_token(self, team_id: str, token_data: Dict[str, Any]) -> bool:
        """
        Store Slack OAuth token in DynamoDB.
        
        Args:
            team_id: Slack team ID
            token_data: Dictionary containing OAuth token data
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Prepare item for DynamoDB
            item = {
                'team_id': {'S': team_id},
                'bot_token': {'S': token_data.get('bot_token', '')},
                'app_id': {'S': token_data.get('app_id', '')},
                'team_name': {'S': token_data.get('team_name', '')},
                'updated_at': {'S': datetime.utcnow().isoformat()},
                'installation_id': {'S': token_data.get('installation_id', team_id)}
            }
            
            # Add optional fields if present
            if 'user_token' in token_data:
                item['user_token'] = {'S': token_data['user_token']}
            if 'scope' in token_data:
                item['scope'] = {'S': token_data['scope']}
            if 'bot_user_id' in token_data:
                item['bot_user_id'] = {'S': token_data['bot_user_id']}
                
            # Store in DynamoDB
            self.dynamodb.put_item(
                TableName=self.table_name,
                Item=item
            )
            
            logger.info(f"Successfully stored OAuth token for team {team_id}")
            
            # Invalidate cache
            if team_id in self._token_cache:
                del self._token_cache[team_id]
                del self._cache_expiry[team_id]
                
            return True
            
        except ClientError as e:
            logger.error(f"Error storing token in DynamoDB: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error storing token: {e}")
            return False
    
    def store_sqs_queue_url(self, queue_url: str, parameter_name: str = '/tag-manager/sqs-queue-url') -> bool:
        """
        Store SQS queue URL in Parameter Store.
        
        Args:
            queue_url: SQS queue URL
            parameter_name: SSM parameter name
            
        Returns:
            True if successful, False otherwise
        """
        try:
            self.ssm.put_parameter(
                Name=parameter_name,
                Value=queue_url,
                Type='String',
                Overwrite=True,
                Description='SQS Queue URL for Tag Manager Slack Worker'
            )
            
            logger.info(f"Successfully stored SQS queue URL in Parameter Store")
            
            # Invalidate cache
            cache_key = 'sqs_queue_url'
            if cache_key in self._token_cache:
                del self._token_cache[cache_key]
                del self._cache_expiry[cache_key]
                
            return True
            
        except ClientError as e:
            logger.error(f"Error storing SQS URL in Parameter Store: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error storing SQS URL: {e}")
            return False
    
    def _parse_dynamodb_item(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parse DynamoDB item to extract values.
        
        Args:
            item: DynamoDB item with type descriptors
            
        Returns:
            Dictionary with extracted values
        """
        result = {}
        for key, value in item.items():
            if 'S' in value:
                result[key] = value['S']
            elif 'N' in value:
                result[key] = value['N']
            elif 'BOOL' in value:
                result[key] = value['BOOL']
            elif 'M' in value:
                result[key] = self._parse_dynamodb_item(value['M'])
            elif 'L' in value:
                result[key] = [self._parse_dynamodb_item({'item': v})['item'] for v in value['L']]
                
        return result
    
    def _cache_token(self, key: str, value: Any):
        """
        Cache a token or configuration value.
        
        Args:
            key: Cache key
            value: Value to cache
        """
        self._token_cache[key] = value
        self._cache_expiry[key] = time.time() + self._cache_duration
        
    def validate_token(self, token: str) -> bool:
        """
        Validate a Slack token by testing it.
        
        Args:
            token: Slack bot token
            
        Returns:
            True if valid, False otherwise
        """
        try:
            from slack_sdk import WebClient
            from slack_sdk.errors import SlackApiError
            
            client = WebClient(token=token)
            response = client.auth_test()
            
            if response.get('ok'):
                logger.info(f"Token validated for team: {response.get('team', 'unknown')}")
                return True
            else:
                logger.warning(f"Token validation failed: {response.get('error', 'unknown error')}")
                return False
                
        except ImportError:
            logger.warning("slack_sdk not installed, cannot validate token")
            return True  # Assume valid if we can't test
        except SlackApiError as e:
            logger.error(f"Slack API error during token validation: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error validating token: {e}")
            return False

    def get_oauth_configuration(self) -> Optional[Dict[str, Any]]:
        """
        Get OAuth configuration from AWS Parameter Store.
        
        Returns:
            Configuration dictionary or None
        """
        try:
            # Get OAuth callback URL from Parameter Store
            parameter_name = f'/tag-manager/{self.environment}/oauth-callback-url'
            response = self.ssm.get_parameter(Name=parameter_name)
            callback_url = response['Parameter']['Value']
            
            return {
                'callback_url': callback_url,
                'table_name': self.table_name,
                'region': self.region
            }
            
        except ClientError as e:
            if e.response['Error']['Code'] == 'ParameterNotFound':
                logger.warning(f"OAuth configuration not found in Parameter Store")
            else:
                logger.error(f"Error getting OAuth configuration: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error getting OAuth configuration: {e}")
            return None

    def get_oauth_session_result(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        Check if OAuth session has completed and get the result.
        
        Args:
            session_id: OAuth session ID to check
            
        Returns:
            Token data if session completed, None otherwise
        """
        try:
            # Check OAuth sessions table for completed session
            sessions_table_name = f"{self.table_name}-sessions"
            
            response = self.dynamodb.get_item(
                TableName=sessions_table_name,
                Key={
                    'session_id': {'S': session_id}
                }
            )
            
            if 'Item' not in response:
                return None  # Session not found or not completed
            
            item = response['Item']
            
            # Check if session is completed
            if item.get('status', {}).get('S') != 'completed':
                return None
            
            # Extract token data
            token_data = {
                'access_token': item.get('access_token', {}).get('S'),
                'user_email': item.get('user_email', {}).get('S'),
                'team_info': {
                    'team_id': item.get('team_id', {}).get('S'),
                    'team_name': item.get('team_name', {}).get('S'),
                    'bot_user_id': item.get('bot_user_id', {}).get('S')
                }
            }
            
            # Store token in main tokens table
            self._store_token_from_oauth(token_data)
            
            # Clean up session record
            self._cleanup_oauth_session(session_id, sessions_table_name)
            
            return token_data
            
        except ClientError as e:
            if e.response['Error']['Code'] == 'ResourceNotFoundException':
                logger.debug(f"OAuth sessions table not found - OAuth service not deployed")
            else:
                logger.error(f"Error checking OAuth session: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error checking OAuth session: {e}")
            return None

    def _store_token_from_oauth(self, token_data: Dict[str, Any]):
        """
        Store token from OAuth flow in main tokens table.
        
        Args:
            token_data: Token data from OAuth flow
        """
        try:
            team_id = token_data['team_info']['team_id']
            
            item = {
                'team_id': {'S': team_id},
                'access_token': {'S': token_data['access_token']},
                'team_name': {'S': token_data['team_info']['team_name']},
                'bot_user_id': {'S': token_data['team_info']['bot_user_id']},
                'installed_at': {'S': datetime.utcnow().isoformat()},
                'updated_at': {'S': datetime.utcnow().isoformat()}
            }
            
            self.dynamodb.put_item(
                TableName=self.table_name,
                Item=item
            )
            
            logger.info(f"Stored OAuth token for team: {token_data['team_info']['team_name']}")
            
        except Exception as e:
            logger.error(f"Error storing OAuth token: {e}")

    def _cleanup_oauth_session(self, session_id: str, sessions_table_name: str):
        """
        Clean up completed OAuth session.
        
        Args:
            session_id: Session ID to clean up
            sessions_table_name: Sessions table name
        """
        try:
            self.dynamodb.delete_item(
                TableName=sessions_table_name,
                Key={
                    'session_id': {'S': session_id}
                }
            )
            logger.debug(f"Cleaned up OAuth session: {session_id}")
            
        except Exception as e:
            logger.warning(f"Could not clean up OAuth session {session_id}: {e}")
    def get_slack_token_by_team_id(self, team_id: str) -> Optional[Dict[str, Any]]:
        """
        Get Slack token information by team ID.

        Args:
            team_id: Slack team/workspace ID

        Returns:
            Token information including email if available
        """
        try:
            # Query DynamoDB for the teams token
            response = self.dynamodb.scan(
                TableName=self.table_name,
                FilterExpression="team_id = :team_id",
                ExpressionAttributeValues={
                    ":team_id": {"S": team_id}
                },
                Limit=1
            )

            items = response.get("Items", [])
            if not items:
                logger.debug(f"No token found for team_id: {team_id}")
                return None

            item = items[0]

            # Convert DynamoDB item to dictionary
            token_info = {
                "team_id": item.get("team_id", {}).get("S"),
                "team_name": item.get("team_name", {}).get("S"),
                "access_token": item.get("access_token", {}).get("S"),
                "bot_user_id": item.get("bot_user_id", {}).get("S"),
                "authed_user_id": item.get("authed_user_id", {}).get("S"),
                "authed_user_email": item.get("authed_user_email", {}).get("S"),
                "installed_at": item.get("installed_at", {}).get("S"),
                "updated_at": item.get("updated_at", {}).get("S")
            }

            logger.debug(f"Retrieved token info for team {team_id}")
            return token_info

        except Exception as e:
            logger.error(f"Error getting token by team_id {team_id}: {e}")
            return None
