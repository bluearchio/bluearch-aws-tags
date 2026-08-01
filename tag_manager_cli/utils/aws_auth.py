"""AWS authentication utilities for Tag Manager CLI."""

import os
import json
import time
import hashlib
import configparser
from pathlib import Path
from datetime import datetime, timedelta
from types import SimpleNamespace
from rich.console import Console
from typing import Optional, Any, Dict, List
from dataclasses import dataclass

from .core_client import CoreRuntimeError, request_core

console = Console()

# Check if debug mode is enabled
DEBUG_MODE = os.environ.get('TAG_MANAGER_DEBUG', '').lower() in ('1', 'true', 'yes')

# Lazy imports - only import when actually needed
_boto3 = None
_botocore_exceptions = None

@dataclass
class AssumedRoleSession:
    """Cached assumed role session"""
    session: Any  # boto3.Session
    expiration: datetime
    account_id: str
    role_arn: str


def _get_boto3():
    """Lazy load boto3 module."""
    global _boto3
    if _boto3 is None:
        import boto3 as module
        _boto3 = module
    return _boto3


def _get_botocore_exceptions():
    """Lazy load botocore exceptions."""
    global _botocore_exceptions
    if _botocore_exceptions is None:
        from botocore import exceptions
        _botocore_exceptions = exceptions
    return _botocore_exceptions


def _payload_from_core_record(record: dict) -> dict:
    payload = dict((record or {}).get("payload", record) or {})
    payload.setdefault("id", (record or {}).get("id") or (record or {}).get("record_key") or payload.get("id"))
    return payload


def _namespace_from_core_record(record: dict) -> SimpleNamespace:
    payload = _payload_from_core_record(record)
    for field in ("created_at", "updated_at", "last_used_at"):
        payload[field] = _parse_core_datetime(payload.get(field))
    return SimpleNamespace(**payload)


def _parse_core_datetime(value):
    if isinstance(value, datetime) or value is None:
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


class AWSAuthManager:
    """Manages AWS authentication using SSO profiles and cross-account role assumption."""

    def __init__(self):
        self.profile_name = None
        self.session = None
        self.region = None  # Store resolved region
        self.assumed_sessions: Dict[str, AssumedRoleSession] = {}  # Cache for assumed role sessions
        self.default_role_name = "BlueArchRole"  # Default role name for cross-account access
        self.session_duration = 3600  # 1 hour session duration

        # Assume-role configuration tracking
        self.assume_role_config = None  # Holds core assume-role storage payload if loaded
        self.using_assumed_role = False  # True if currently using assumed role
        self._base_session = None  # Store base session before assume-role

    def get_aws_profile(self) -> str:
        """Get AWS profile from environment variable or prompt user."""
        profile = os.environ.get('AWS_PROFILE')
        if DEBUG_MODE:
            console.print(f"[debug]get_aws_profile: os.environ.get('AWS_PROFILE') = {profile}")

        # Also check settings as fallback
        if not profile:
            from .env_config import settings
            profile = settings.aws_profile
            if DEBUG_MODE:
                console.print(f"[debug]get_aws_profile: fallback to settings.aws_profile = {profile}")

        if not profile:
            raise ValueError(
                "AWS_PROFILE environment variable not set. "
                "Please set it to your SSO profile name."
            )

        if DEBUG_MODE:
            console.print(f"[debug]get_aws_profile: returning {profile}")
        return profile
    
    def get_current_profile(self) -> Optional[str]:
        """Get current AWS profile if available, None if using environment variables."""
        try:
            return self.get_aws_profile()
        except ValueError:
            # No profile set, might be using environment variables
            return None
    
    def check_aws_credentials(self) -> bool:
        """Check if AWS credentials are available (profile or environment variables)."""
        try:
            # First try with profile if available
            boto3 = _get_boto3()
            profile = self.get_current_profile()
            if profile:
                session = boto3.Session(profile_name=profile)
            else:
                # Try with default session (environment variables)
                session = boto3.Session()

            # Test credentials by calling STS
            sts_client = session.client('sts')
            sts_client.get_caller_identity()
            return True
        except Exception:
            return False

    def resolve_region(self, profile_name: Optional[str] = None) -> Optional[str]:
        """
        Resolve AWS region from multiple sources with proper fallback.

        Priority order:
        1. AWS_REGION environment variable
        2. AWS_DEFAULT_REGION environment variable
        3. Region from AWS config file for the profile
        4. Default region from settings (us-east-1)

        Args:
            profile_name: AWS profile name to check config for

        Returns:
            Resolved region string or None if not found
        """
        # 1. Check AWS_REGION env var (highest priority)
        region = os.environ.get('AWS_REGION')
        if region:
            if DEBUG_MODE:
                console.print(f"[debug]Region resolved from AWS_REGION: {region}")
            return region

        # 2. Check AWS_DEFAULT_REGION env var
        region = os.environ.get('AWS_DEFAULT_REGION')
        if region:
            if DEBUG_MODE:
                console.print(f"[debug]Region resolved from AWS_DEFAULT_REGION: {region}")
            return region

        # 3. Try to get region from AWS config file for the profile
        if profile_name and profile_name != "environment-variables":
            aws_config_path = Path.home() / '.aws' / 'config'
            if aws_config_path.exists():
                config = configparser.ConfigParser()
                try:
                    config.read(aws_config_path)

                    # Check the profile section
                    if profile_name == 'default':
                        section = 'default'
                    else:
                        section = f'profile {profile_name}'

                    if section in config and 'region' in config[section]:
                        region = config[section]['region']
                        if DEBUG_MODE:
                            console.print(f"[debug]Region resolved from AWS config for profile '{profile_name}': {region}")
                        return region
                except Exception as e:
                    if DEBUG_MODE:
                        console.print(f"[debug]Error reading AWS config: {e}")

        # 4. Fall back to default region from settings
        try:
            from .env_config import settings
            region = settings.aws_default_region or 'us-east-1'
            if DEBUG_MODE:
                console.print(f"[debug]Region resolved from default settings: {region}")
            return region
        except ImportError:
            pass

        # 5. Final fallback
        if DEBUG_MODE:
            console.print("[debug]No region found, falling back to us-east-1")
        return 'us-east-1'

    def detect_credential_conflict(self) -> Optional[str]:
        """
        Detect if both AWS_PROFILE and credential environment variables are set.

        Returns:
            Warning message if conflict detected, None otherwise
        """
        profile = os.environ.get('AWS_PROFILE')
        access_key = os.environ.get('AWS_ACCESS_KEY_ID')
        secret_key = os.environ.get('AWS_SECRET_ACCESS_KEY')

        if profile and access_key and secret_key:
            from .exceptions import CredentialConflictError
            return CredentialConflictError(profile=profile).args[0]

        return None
    
    def initialize_session(self) -> Any:  # Return type is boto3.Session but we use Any to avoid import
        """Initialize AWS session with SSO profile or environment variables."""
        try:
            boto3 = _get_boto3()

            # Check for credential conflict
            conflict_msg = self.detect_credential_conflict()
            if conflict_msg:
                # Warn about conflict but continue with profile precedence
                console.print(f"[yellow]Warning: {conflict_msg}[/yellow]")
                console.print("[yellow]Using AWS_PROFILE for authentication (ignoring environment credentials).[/yellow]")

                # Clear environment credentials to avoid confusion
                for key in ['AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'AWS_SESSION_TOKEN']:
                    if key in os.environ:
                        del os.environ[key]

            # Determine authentication method
            profile = os.environ.get('AWS_PROFILE')
            access_key = os.environ.get('AWS_ACCESS_KEY_ID')
            secret_key = os.environ.get('AWS_SECRET_ACCESS_KEY')

            if profile:
                # Profile-based authentication (preferred)
                self.profile_name = profile
                self.region = self.resolve_region(profile)

                if DEBUG_MODE:
                    console.print(f"[debug]Using AWS profile '{self.profile_name}' for authentication")
                    console.print(f"[debug]Resolved region: {self.region}")

                self.session = boto3.Session(
                    profile_name=self.profile_name,
                    region_name=self.region
                )

            elif access_key and secret_key:
                # Environment credential authentication
                if DEBUG_MODE:
                    console.print("[debug]Using AWS environment variables for authentication")

                self.profile_name = "environment-variables"
                self.region = self.resolve_region(None)

                if DEBUG_MODE:
                    console.print(f"[debug]Resolved region: {self.region}")

                # Pass region explicitly when using environment credentials
                self.session = boto3.Session(region_name=self.region)

            else:
                # No authentication method found - try to get profile from settings
                try:
                    self.profile_name = self.get_aws_profile()
                    self.region = self.resolve_region(self.profile_name)

                    if DEBUG_MODE:
                        console.print(f"[debug]Using AWS profile '{self.profile_name}' from settings")
                        console.print(f"[debug]Resolved region: {self.region}")

                    self.session = boto3.Session(
                        profile_name=self.profile_name,
                        region_name=self.region
                    )
                except ValueError:
                    # Last resort - try default session
                    if DEBUG_MODE:
                        console.print("[debug]No profile or credentials found, trying default session")

                    self.region = self.resolve_region(None)
                    self.session = boto3.Session(region_name=self.region)
                    self.profile_name = "default"

            # Verify region is set
            if not self.region:
                from .exceptions import RegionNotConfiguredError
                raise RegionNotConfiguredError(profile=self.profile_name)

            # Test the credentials by making a simple call
            sts_client = self.session.client('sts')
            identity = sts_client.get_caller_identity()

            if DEBUG_MODE:
                console.print(f"[green]OK[/green] Successfully authenticated as: {identity.get('Arn')}")
                console.print(f"[green]OK[/green] Authentication method: {self.profile_name}")
                console.print(f"[green]OK[/green] Region: {self.region}")

            # Apply assume-role configuration if enabled
            try:
                self._apply_assume_role_config()
            except Exception as e:
                # Show warning to user (not just in debug mode) if assume-role was configured but failed
                if self.assume_role_config:
                    console.print(f"[yellow]WARN[/yellow] Assume role failed, using direct credentials: {e}")
                    console.print("[dim]Run 'bluearch-aws-tags setup assume-role --status' to check configuration[/dim]")
                elif DEBUG_MODE:
                    console.print(f"[yellow]WARN[/yellow] Assume role not applied: {e}")
                # Continue with base session if assume-role fails
                # This allows CLI to still work for setup/configuration

            return self.session

        except _get_botocore_exceptions().ProfileNotFound:
            # If profile not found, try environment variables as fallback
            try:
                if DEBUG_MODE:
                    console.print("[debug]Profile not found, trying environment variables")

                self.region = self.resolve_region(None)
                self.session = boto3.Session(region_name=self.region)
                sts_client = self.session.client('sts')
                identity = sts_client.get_caller_identity()
                self.profile_name = "environment-variables"

                if DEBUG_MODE:
                    console.print(f"[green]OK[/green] Successfully authenticated with environment variables")
                    console.print(f"[green]OK[/green] Region: {self.region}")

                return self.session
            except Exception:
                raise ValueError(
                    f"AWS profile '{self.profile_name}' not found and no valid environment variables. "
                    "Please check your AWS configuration or run 'aws configure sso'."
                )
        except _get_botocore_exceptions().NoCredentialsError:
            from .exceptions import AWSCredentialsError
            raise AWSCredentialsError(
                "No valid AWS credentials found. "
                "Please ensure your SSO session is active by running 'aws sso login' or set environment variables."
            )
        except _get_botocore_exceptions().NoRegionError:
            from .exceptions import RegionNotConfiguredError
            raise RegionNotConfiguredError(profile=self.profile_name)
        except Exception as e:
            raise ValueError(f"Failed to authenticate with AWS: {str(e)}")
    
    def get_client(self, service_name: str, region: Optional[str] = None):
        """Get AWS service client."""
        if not self.session:
            self.initialize_session()

        # Use provided region or fall back to the resolved region
        effective_region = region or self.region

        kwargs = {}
        if effective_region:
            kwargs['region_name'] = effective_region

        return self.session.client(service_name, **kwargs)

    def get_resource(self, service_name: str, region: Optional[str] = None):
        """Get AWS service resource."""
        if not self.session:
            self.initialize_session()

        # Use provided region or fall back to the resolved region
        effective_region = region or self.region

        kwargs = {}
        if effective_region:
            kwargs['region_name'] = effective_region

        return self.session.resource(service_name, **kwargs)
    
    def get_caller_identity(self):
        """Get AWS caller identity information."""
        if not self.session:
            self.initialize_session()

        sts_client = self.session.client('sts')
        return sts_client.get_caller_identity()

    # Cross-account role assumption methods
    def assume_role(
        self,
        role_arn: str,
        session_name: str = "tag-manager-cli",
        external_id: Optional[str] = None,
        duration_seconds: Optional[int] = None
    ) -> Any:  # Returns boto3.Session
        """
        Assume a role and return a new session with temporary credentials.

        Args:
            role_arn: ARN of the role to assume
            session_name: Name for the assumed role session
            external_id: External ID if required by the role's trust policy
            duration_seconds: Session duration (default: 3600)

        Returns:
            boto3.Session with assumed role credentials
        """
        if not self.session:
            self.initialize_session()

        boto3 = _get_boto3()
        duration = duration_seconds or self.session_duration

        # Check cache first
        cache_key = f"{role_arn}:{external_id or 'no-external-id'}"
        if cache_key in self.assumed_sessions:
            cached = self.assumed_sessions[cache_key]
            # Check if session is still valid (with 5-minute buffer)
            if cached.expiration > datetime.now() + timedelta(minutes=5):
                if DEBUG_MODE:
                    console.print(f"[debug]Using cached session for {role_arn}")
                return cached.session

        try:
            # Assume the role
            sts_client = self.session.client('sts')
            assume_params = {
                'RoleArn': role_arn,
                'RoleSessionName': session_name,
                'DurationSeconds': duration
            }

            if external_id:
                assume_params['ExternalId'] = external_id

            response = sts_client.assume_role(**assume_params)
            credentials = response['Credentials']

            # Create new session with assumed role credentials and region
            assumed_session = boto3.Session(
                aws_access_key_id=credentials['AccessKeyId'],
                aws_secret_access_key=credentials['SecretAccessKey'],
                aws_session_token=credentials['SessionToken'],
                region_name=self.region  # Use the resolved region
            )

            # Cache the session
            account_id = role_arn.split(':')[4]  # Extract account ID from ARN
            self.assumed_sessions[cache_key] = AssumedRoleSession(
                session=assumed_session,
                expiration=credentials['Expiration'].replace(tzinfo=None),
                account_id=account_id,
                role_arn=role_arn
            )

            if DEBUG_MODE:
                console.print(f"[green]Successfully assumed role {role_arn}[/green]")

            return assumed_session

        except _get_botocore_exceptions().ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'AccessDenied':
                raise ValueError(
                    f"Access denied when assuming role {role_arn}. "
                    "Check that the role exists and trusts your account."
                )
            elif error_code == 'InvalidParameterValue':
                raise ValueError(
                    f"Invalid parameter when assuming role {role_arn}. "
                    "Check external ID requirements."
                )
            else:
                raise ValueError(f"Failed to assume role {role_arn}: {str(e)}")

    def get_client_for_account(
        self,
        account_id: str,
        service_name: str,
        region: Optional[str] = None,
        role_name: Optional[str] = None,
        external_id: Optional[str] = None
    ):
        """
        Get a service client for a specific account via role assumption.

        Args:
            account_id: Target AWS account ID
            service_name: AWS service name (e.g., 'ec2', 's3')
            region: AWS region (optional)
            role_name: Role name to assume (default: BlueArchRole)
            external_id: External ID if required (auto-retrieved if None)

        Returns:
            boto3 client for the specified service in the target account
        """
        # Get current account ID
        if not self.session:
            self.initialize_session()

        current_identity = self.get_caller_identity()
        current_account = current_identity['Account']

        # If same account, use regular client
        if account_id == current_account:
            return self.get_client(service_name, region)

        # Auto-retrieve ExternalId if not provided
        if external_id is None:
            external_id = self.get_cross_account_external_id()

        # Assume role in target account
        role_name = role_name or self.default_role_name
        role_arn = f"arn:aws:iam::{account_id}:role/{role_name}"

        assumed_session = self.assume_role(
            role_arn=role_arn,
            external_id=external_id
        )

        # Create client with assumed session
        kwargs = {}
        if region:
            kwargs['region_name'] = region

        return assumed_session.client(service_name, **kwargs)

    def get_resource_for_account(
        self,
        account_id: str,
        service_name: str,
        region: Optional[str] = None,
        role_name: Optional[str] = None,
        external_id: Optional[str] = None
    ):
        """
        Get a service resource for a specific account via role assumption.

        Args:
            account_id: Target AWS account ID
            service_name: AWS service name (e.g., 's3', 'dynamodb')
            region: AWS region (optional)
            role_name: Role name to assume (default: BlueArchRole)
            external_id: External ID if required (auto-retrieved if None)

        Returns:
            boto3 resource for the specified service in the target account
        """
        # Get current account ID
        if not self.session:
            self.initialize_session()

        current_identity = self.get_caller_identity()
        current_account = current_identity['Account']

        # If same account, use regular resource
        if account_id == current_account:
            return self.get_resource(service_name, region)

        # Auto-retrieve ExternalId if not provided
        if external_id is None:
            external_id = self.get_cross_account_external_id()

        # Assume role in target account
        role_name = role_name or self.default_role_name
        role_arn = f"arn:aws:iam::{account_id}:role/{role_name}"

        assumed_session = self.assume_role(
            role_arn=role_arn,
            external_id=external_id
        )

        # Create resource with assumed session
        kwargs = {}
        if region:
            kwargs['region_name'] = region

        return assumed_session.resource(service_name, **kwargs)

    def get_organization_accounts(self) -> List[Dict]:
        """
        List all accounts in the AWS Organization.

        Returns:
            List of account dictionaries with Id, Name, Email, Status
        """
        if not self.session:
            self.initialize_session()

        try:
            org_client = self.get_client('organizations')
            accounts = []

            # Paginate through all accounts
            paginator = org_client.get_paginator('list_accounts')
            for page in paginator.paginate():
                accounts.extend(page['Accounts'])

            if DEBUG_MODE:
                console.print(f"[debug]Found {len(accounts)} accounts in organization")

            return accounts

        except _get_botocore_exceptions().ClientError as e:
            if e.response['Error']['Code'] == 'AWSOrganizationsNotInUseException':
                raise ValueError(
                    "AWS Organizations is not enabled for this account. "
                    "Cross-account features require Organizations."
                )
            elif e.response['Error']['Code'] == 'AccessDeniedException':
                raise ValueError(
                    "Access denied to AWS Organizations. "
                    "Ensure you have organizations:ListAccounts permission."
                )
            else:
                raise ValueError(f"Failed to list organization accounts: {str(e)}")

    def get_cross_account_external_id(self) -> Optional[str]:
        """
        Retrieve the ExternalId for the shared BlueArchRole StackSet.

        Returns:
            The ExternalId string, or None if not found
        """
        try:
            # Get organization ID first
            org_client = self.get_client('organizations')
            org_info = org_client.describe_organization()
            org = org_info['Organization']
            org_id = org['Id']
            management_account_id = org['MasterAccountId']

            # Retrieve from Secrets Manager (v2 path for CloudFormation-managed)
            secrets_client = self.get_client('secretsmanager')
            secret_name = f"tag-manager-cli/v2/external-id/{org_id}"

            try:
                response = secrets_client.get_secret_value(SecretId=secret_name)
                secret_data = json.loads(response['SecretString'])
                external_id = secret_data.get('ExternalId')
            except Exception as e:
                if DEBUG_MODE:
                    console.print(
                        f"[yellow]Could not retrieve ExternalId from Secrets Manager: {str(e)}[/yellow]"
                    )
                external_id = None

            if not external_id:
                unique_string = f"{org_id}-{management_account_id}-BlueArchCLI"
                external_id = hashlib.sha256(unique_string.encode()).hexdigest()[:32]

            if DEBUG_MODE:
                console.print(f"[debug]Using cross-account ExternalId: {external_id[:8]}...")

            return external_id

        except Exception as e:
            if DEBUG_MODE:
                console.print(f"[yellow]Could not resolve cross-account ExternalId: {str(e)}[/yellow]")
            return None

    def validate_cross_account_access(
        self,
        account_id: str,
        role_name: Optional[str] = None,
        external_id: Optional[str] = None
    ) -> bool:
        """
        Test if we can assume a role in the target account.

        Args:
            account_id: Target account ID
            role_name: Role name (default: BlueArchRole)
            external_id: External ID if required (auto-retrieved if None)

        Returns:
            True if role assumption succeeds, False otherwise
        """
        try:
            # Auto-retrieve ExternalId if not provided
            if external_id is None:
                external_id = self.get_cross_account_external_id()

            role_name = role_name or self.default_role_name
            role_arn = f"arn:aws:iam::{account_id}:role/{role_name}"

            # Try to assume the role
            self.assume_role(
                role_arn=role_arn,
                external_id=external_id,
                duration_seconds=900  # 15 minutes for testing
            )

            return True

        except Exception as e:
            if DEBUG_MODE:
                console.print(f"[red]Failed to assume role in account {account_id}: {str(e)}[/red]")
            return False

    def clear_assumed_sessions_cache(self):
        """Clear the cache of assumed role sessions."""
        self.assumed_sessions.clear()
        if DEBUG_MODE:
            console.print("[debug]Cleared assumed sessions cache")

    # =========================================================================
    # Assume-Role Configuration Integration
    # =========================================================================

    def _load_assume_role_config(self):
        """Load active assume-role configuration from bluearch-core storage.

        Returns the active and enabled core assume-role payload, or None if not found.
        """
        try:
            records = request_core(
                "GET",
                "/api/v1/storage/core/assume-role-configurations",
                service_token=True,
                params=[
                    ("filter", "is_active=true"),
                    ("filter", "enabled=true"),
                    ("limit", 1),
                    ("order_by", "updated_at"),
                    ("descending", "true"),
                ],
                timeout=10.0,
            )
            if not records:
                return None
            return _namespace_from_core_record(records[0])

        except CoreRuntimeError as e:
            if DEBUG_MODE:
                console.print(f"[debug] Could not load assume-role config: {e}")
            return None

    def _apply_assume_role_config(self):
        """Apply assume-role configuration to current session.

        If an assume-role configuration is active and enabled, this method will:
        1. Load the configuration from the database
        2. Assume the configured role
        3. Replace the current session with the assumed role session
        4. Update the last_used_at timestamp
        """
        # Don't apply during the initial setup phase
        if not self.session:
            return

        # Load configuration
        config = self._load_assume_role_config()
        if not config:
            if DEBUG_MODE:
                console.print("[debug] No active assume-role configuration found")
            return

        self.assume_role_config = config

        if DEBUG_MODE:
            console.print(f"[debug] Found assume-role config: {config.role_name} in account {config.account_id}")

        # Store the base session before assuming role
        self._base_session = self.session

        try:
            boto3 = _get_boto3()

            # Assume the role
            sts_client = self.session.client('sts')
            assume_params = {
                'RoleArn': config.role_arn,
                'RoleSessionName': 'tag-manager-cli',
                'DurationSeconds': self.session_duration
            }

            if config.external_id:
                assume_params['ExternalId'] = config.external_id

            response = sts_client.assume_role(**assume_params)
            credentials = response['Credentials']

            # Create new session with assumed role credentials
            self.session = boto3.Session(
                aws_access_key_id=credentials['AccessKeyId'],
                aws_secret_access_key=credentials['SecretAccessKey'],
                aws_session_token=credentials['SessionToken'],
                region_name=self.region
            )

            self.using_assumed_role = True

            if DEBUG_MODE:
                console.print(f"[green]OK[/green] Using assumed role: {config.role_arn}")

            # Update last_used_at in database
            self._update_last_used_timestamp(config.id)

        except Exception as e:
            # Restore base session on failure
            self.session = self._base_session
            self._base_session = None
            self.using_assumed_role = False
            raise RuntimeError(f"Failed to assume role: {e}")

    def _update_last_used_timestamp(self, config_id: str):
        """Update the last_used_at timestamp for an assume-role configuration."""
        try:
            record = request_core(
                "GET",
                f"/api/v1/storage/core/assume-role-configurations/{config_id}",
                service_token=True,
                timeout=10.0,
            )
            payload = _payload_from_core_record(record)
            payload["last_used_at"] = datetime.utcnow().isoformat()
            request_core(
                "PUT",
                f"/api/v1/storage/core/assume-role-configurations/{config_id}",
                service_token=True,
                json={"payload": payload},
                timeout=10.0,
            )
        except CoreRuntimeError as e:
            if DEBUG_MODE:
                console.print(f"[debug] Could not update last_used_at: {e}")

    def is_assume_role_enabled(self) -> bool:
        """Check if assume-role is currently active."""
        return self.using_assumed_role

    def get_assume_role_status(self) -> Dict[str, Any]:
        """Get current assume-role configuration status.

        Returns:
            Dict with: enabled, role_arn, account_id, last_used_at
        """
        if self.assume_role_config:
            return {
                'enabled': self.using_assumed_role,
                'role_arn': self.assume_role_config.role_arn,
                'role_name': self.assume_role_config.role_name,
                'account_id': self.assume_role_config.account_id,
                'external_id_configured': bool(self.assume_role_config.external_id),
                'last_used_at': self.assume_role_config.last_used_at.isoformat() if self.assume_role_config.last_used_at else None
            }
        return {
            'enabled': False,
            'role_arn': None,
            'role_name': None,
            'account_id': None,
            'external_id_configured': False,
            'last_used_at': None
        }

    def get_base_session(self):
        """Get the base session (before assume-role was applied).

        Useful for operations that need the original credentials,
        such as setting up assume-role configuration.
        """
        return self._base_session or self.session


# Global instance
aws_auth = AWSAuthManager()
