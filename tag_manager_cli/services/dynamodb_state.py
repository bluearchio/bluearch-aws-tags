"""
DynamoDB State Management Service for Cross-Account Configuration

This service provides centralized state management for multi-account operations,
storing account enable/disable states in DynamoDB with local caching for offline support.
"""

import json
import logging
import os
from typing import Dict, List, Optional, Any, Set
from pathlib import Path
from datetime import datetime, timezone
from dataclasses import dataclass, asdict
import time

from botocore.exceptions import ClientError
from rich.console import Console

from ..utils.aws_auth import aws_auth
from ..utils.error_handlers import handle_aws_errors
from ..utils.core_client import request_core

logger = logging.getLogger(__name__)
console = Console()


@dataclass
class AccountState:
    """Represents an account's state in the system"""
    account_id: str
    enabled_for_discovery: bool
    enabled_for_tagging: bool
    enabled_by: str
    enabled_at: str
    disabled_by: Optional[str] = None
    disabled_at: Optional[str] = None
    account_name: Optional[str] = None
    organizational_unit_id: Optional[str] = None
    metadata: Optional[Dict] = None


class DynamoDBStateService:
    """
    Manages cross-account state in DynamoDB with local fallback.

    Architecture:
    - DynamoDB: Centralized source of truth for account states
    - Local JSON: Cache for offline support and fast reads
    - bluearch-core: Detailed account status and scan statistics
    """

    def __init__(self):
        self.table_name = "tag-manager-cross-account"
        self.local_cache_file = Path.home() / ".tag-manager" / "data" / "enabled_accounts.json"
        self.local_state_file = Path.home() / ".tag-manager" / "data" / "account_states.json"
        self.dynamodb_client = None
        self.dynamodb_available = False
        self._dynamodb_initialized = False  # Track if we've attempted initialization
        self.last_sync_time = 0
        self.sync_interval = 300  # 5 minutes

        # Ensure local directories exist
        if os.environ.get("TAG_MANAGER_SUPPRESS_STARTUP_STATE") != "1":
            self.local_cache_file.parent.mkdir(parents=True, exist_ok=True)

        # Don't initialize DynamoDB here - wait until first use

    def _ensure_dynamodb_initialized(self) -> bool:
        """Ensure DynamoDB is initialized (lazy initialization)"""
        if self._dynamodb_initialized:
            return self.dynamodb_available

        self._dynamodb_initialized = True
        return self._initialize_dynamodb()

    def _initialize_dynamodb(self) -> bool:
        """Initialize DynamoDB client and check table availability"""
        try:
            # Get current identity to check if we're in management account
            identity = aws_auth.get_caller_identity()
            current_account = identity['Account']

            # Try to get DynamoDB client for management account
            self.dynamodb_client = aws_auth.get_client('dynamodb')

            # Check if table exists
            try:
                response = self.dynamodb_client.describe_table(TableName=self.table_name)
                self.dynamodb_available = True
                logger.info(f"DynamoDB table '{self.table_name}' is available")
                return True
            except ClientError as e:
                if e.response['Error']['Code'] == 'ResourceNotFoundException':
                    logger.warning(f"DynamoDB table '{self.table_name}' not found. Using local storage only.")
                else:
                    logger.error(f"Error checking DynamoDB table: {str(e)}")
                self.dynamodb_available = False
                return False

        except Exception as e:
            logger.warning(f"Could not initialize DynamoDB: {str(e)}. Using local storage.")
            self.dynamodb_available = False
            return False

    def _get_dynamodb_key(self, account_id: str) -> Dict:
        """Generate DynamoDB key for account state"""
        return {
            'pk': {'S': f'ACCOUNT#{account_id}'},
            'sk': {'S': 'CONFIG#STATE'}
        }

    def enable_accounts(self, account_ids: List[str], enabled_by: str = None) -> Dict[str, Any]:
        """
        Enable accounts for discovery and tagging.

        Args:
            account_ids: List of account IDs to enable
            enabled_by: User or process that enabled the accounts

        Returns:
            Dict with success status and details
        """
        result = {
            'success': True,
            'enabled_count': 0,
            'failed_accounts': [],
            'errors': []
        }

        if not enabled_by:
            # Only get caller identity if we need it
            try:
                enabled_by = aws_auth.get_caller_identity().get('Arn', 'unknown')
            except:
                enabled_by = 'unknown'

        timestamp = datetime.now(timezone.utc).isoformat()

        # Lazily initialize DynamoDB if needed
        self._ensure_dynamodb_initialized()

        # Update DynamoDB if available
        if self.dynamodb_available:
            for account_id in account_ids:
                try:
                    # Get account details from Organizations if available
                    account_name = None
                    ou_id = None
                    try:
                        org_accounts = aws_auth.get_organization_accounts()
                        for acc in org_accounts:
                            if acc['Id'] == account_id:
                                account_name = acc.get('Name')
                                # Get OU would require additional API call
                                break
                    except Exception:
                        pass

                    # Store in DynamoDB
                    item = {
                        'pk': {'S': f'ACCOUNT#{account_id}'},
                        'sk': {'S': 'CONFIG#STATE'},
                        'account_id': {'S': account_id},
                        'enabled_for_discovery': {'BOOL': True},
                        'enabled_for_tagging': {'BOOL': True},
                        'enabled_by': {'S': enabled_by},
                        'enabled_at': {'S': timestamp},
                        'ttl': {'N': str(int(time.time()) + 86400 * 365)},  # 1 year TTL
                        'gsi1pk': {'S': 'ENABLED'},
                        'gsi1sk': {'S': f'ACCOUNT#{account_id}'}
                    }

                    if account_name:
                        item['account_name'] = {'S': account_name}
                    if ou_id:
                        item['organizational_unit_id'] = {'S': ou_id}

                    self.dynamodb_client.put_item(
                        TableName=self.table_name,
                        Item=item
                    )

                    result['enabled_count'] += 1
                    logger.info(f"Enabled account {account_id} in DynamoDB")

                except Exception as e:
                    logger.error(f"Failed to enable account {account_id} in DynamoDB: {str(e)}")
                    result['failed_accounts'].append(account_id)
                    result['errors'].append(str(e))

        # Always update local cache (for offline support)
        self._update_local_cache(account_ids, enabled=True, enabled_by=enabled_by, timestamp=timestamp)

        # Update core account-status records
        self._update_core_accounts(account_ids, enabled=True, enabled_by=enabled_by)

        # If DynamoDB failed but local succeeded, count those
        if not self.dynamodb_available:
            result['enabled_count'] = len(account_ids)
            result['errors'].append("DynamoDB not available, using local storage only")

        return result

    def disable_accounts(self, account_ids: List[str], disabled_by: str = None) -> Dict[str, Any]:
        """
        Disable accounts from discovery and tagging.

        Args:
            account_ids: List of account IDs to disable
            disabled_by: User or process that disabled the accounts

        Returns:
            Dict with success status and details
        """
        result = {
            'success': True,
            'disabled_count': 0,
            'failed_accounts': [],
            'errors': []
        }

        if not disabled_by:
            try:
                disabled_by = aws_auth.get_caller_identity().get('Arn', 'unknown')
            except:
                disabled_by = 'unknown'

        timestamp = datetime.now(timezone.utc).isoformat()

        # Lazily initialize DynamoDB if needed
        self._ensure_dynamodb_initialized()

        # Update DynamoDB if available
        if self.dynamodb_available:
            for account_id in account_ids:
                try:
                    # Update item in DynamoDB (don't delete, just mark disabled)
                    self.dynamodb_client.update_item(
                        TableName=self.table_name,
                        Key=self._get_dynamodb_key(account_id),
                        UpdateExpression="SET enabled_for_discovery = :disabled, "
                                       "enabled_for_tagging = :disabled, "
                                       "disabled_by = :user, "
                                       "disabled_at = :ts, "
                                       "gsi1pk = :status",
                        ExpressionAttributeValues={
                            ':disabled': {'BOOL': False},
                            ':user': {'S': disabled_by},
                            ':ts': {'S': timestamp},
                            ':status': {'S': 'DISABLED'}
                        }
                    )

                    result['disabled_count'] += 1
                    logger.info(f"Disabled account {account_id} in DynamoDB")

                except Exception as e:
                    logger.error(f"Failed to disable account {account_id} in DynamoDB: {str(e)}")
                    result['failed_accounts'].append(account_id)
                    result['errors'].append(str(e))

        # Always update local cache
        self._update_local_cache(account_ids, enabled=False, disabled_by=disabled_by, timestamp=timestamp)

        # Update core account-status records
        self._update_core_accounts(account_ids, enabled=False, disabled_by=disabled_by)

        # If DynamoDB failed but local succeeded, count those
        if not self.dynamodb_available:
            result['disabled_count'] = len(account_ids)
            result['errors'].append("DynamoDB not available, using local storage only")

        return result

    def get_enabled_accounts(self, force_refresh: bool = False) -> List[str]:
        """
        Get list of enabled account IDs.

        Args:
            force_refresh: Force refresh from DynamoDB

        Returns:
            List of enabled account IDs
        """
        # Check if we need to sync with DynamoDB
        current_time = time.time()
        needs_sync = (current_time - self.last_sync_time) > self.sync_interval or force_refresh

        # Only initialize DynamoDB if we need to sync
        if needs_sync:
            self._ensure_dynamodb_initialized()

        if self.dynamodb_available and needs_sync:
            try:
                self._sync_from_dynamodb()
                self.last_sync_time = current_time
            except Exception as e:
                logger.warning(f"Failed to sync from DynamoDB: {str(e)}")

        # Read from local cache
        return self._read_local_cache()

    def get_account_states(self, account_ids: Optional[List[str]] = None) -> Dict[str, AccountState]:
        """
        Get detailed state for accounts.

        Args:
            account_ids: Optional list of specific account IDs to retrieve

        Returns:
            Dict mapping account IDs to AccountState objects
        """
        states = {}

        # Lazily initialize DynamoDB if needed
        self._ensure_dynamodb_initialized()

        # Try DynamoDB first
        if self.dynamodb_available:
            try:
                if account_ids:
                    # Batch get specific accounts
                    for account_id in account_ids:
                        try:
                            response = self.dynamodb_client.get_item(
                                TableName=self.table_name,
                                Key=self._get_dynamodb_key(account_id)
                            )
                            if 'Item' in response:
                                states[account_id] = self._parse_dynamodb_item(response['Item'])
                        except Exception as e:
                            logger.error(f"Failed to get state for account {account_id}: {str(e)}")
                else:
                    # Scan all enabled accounts
                    response = self.dynamodb_client.query(
                        TableName=self.table_name,
                        IndexName='gsi1',
                        KeyConditionExpression='gsi1pk = :pk',
                        ExpressionAttributeValues={
                            ':pk': {'S': 'ENABLED'}
                        }
                    )
                    for item in response.get('Items', []):
                        account_id = item['account_id']['S']
                        states[account_id] = self._parse_dynamodb_item(item)
            except Exception as e:
                logger.error(f"Failed to get account states from DynamoDB: {str(e)}")

        # Fall back to local state file if DynamoDB unavailable or incomplete
        if not states and self.local_state_file.exists():
            try:
                with open(self.local_state_file, 'r') as f:
                    local_states = json.load(f)
                    for account_id, state_dict in local_states.items():
                        if not account_ids or account_id in account_ids:
                            states[account_id] = AccountState(**state_dict)
            except Exception as e:
                logger.error(f"Failed to read local state file: {str(e)}")

        return states

    def _sync_from_dynamodb(self):
        """Sync enabled accounts from DynamoDB to local cache"""
        try:
            # Query all enabled accounts
            response = self.dynamodb_client.query(
                TableName=self.table_name,
                IndexName='gsi1',
                KeyConditionExpression='gsi1pk = :pk',
                ExpressionAttributeValues={
                    ':pk': {'S': 'ENABLED'}
                }
            )

            enabled_accounts = []
            account_states = {}

            for item in response.get('Items', []):
                account_id = item['account_id']['S']
                enabled_accounts.append(account_id)
                account_states[account_id] = asdict(self._parse_dynamodb_item(item))

            # Handle pagination
            while 'LastEvaluatedKey' in response:
                response = self.dynamodb_client.query(
                    TableName=self.table_name,
                    IndexName='gsi1',
                    KeyConditionExpression='gsi1pk = :pk',
                    ExpressionAttributeValues={
                        ':pk': {'S': 'ENABLED'}
                    },
                    ExclusiveStartKey=response['LastEvaluatedKey']
                )

                for item in response.get('Items', []):
                    account_id = item['account_id']['S']
                    enabled_accounts.append(account_id)
                    account_states[account_id] = asdict(self._parse_dynamodb_item(item))

            # Update local cache files only if DynamoDB has data
            # Don't overwrite local file if DynamoDB is empty but local has accounts
            if enabled_accounts:
                with open(self.local_cache_file, 'w') as f:
                    json.dump(sorted(enabled_accounts), f, indent=2)

                with open(self.local_state_file, 'w') as f:
                    json.dump(account_states, f, indent=2, default=str)

                logger.info(f"Synced {len(enabled_accounts)} enabled accounts from DynamoDB")
            else:
                # DynamoDB is empty - keep existing local data
                logger.debug("DynamoDB has no enabled accounts, keeping local cache")

        except Exception as e:
            logger.error(f"Failed to sync from DynamoDB: {str(e)}")
            raise

    def _parse_dynamodb_item(self, item: Dict) -> AccountState:
        """Parse DynamoDB item to AccountState object"""
        return AccountState(
            account_id=item['account_id']['S'],
            enabled_for_discovery=item.get('enabled_for_discovery', {}).get('BOOL', False),
            enabled_for_tagging=item.get('enabled_for_tagging', {}).get('BOOL', False),
            enabled_by=item.get('enabled_by', {}).get('S', 'unknown'),
            enabled_at=item.get('enabled_at', {}).get('S', ''),
            disabled_by=item.get('disabled_by', {}).get('S'),
            disabled_at=item.get('disabled_at', {}).get('S'),
            account_name=item.get('account_name', {}).get('S'),
            organizational_unit_id=item.get('organizational_unit_id', {}).get('S'),
            metadata=json.loads(item.get('metadata', {}).get('S', '{}'))
        )

    def _update_local_cache(self, account_ids: List[str], enabled: bool,
                          enabled_by: str = None, disabled_by: str = None,
                          timestamp: str = None):
        """Update local cache files"""
        # Update simple enabled list
        enabled_accounts = set(self._read_local_cache())

        if enabled:
            enabled_accounts.update(account_ids)
        else:
            enabled_accounts.difference_update(account_ids)

        with open(self.local_cache_file, 'w') as f:
            json.dump(sorted(list(enabled_accounts)), f, indent=2)

        # Update detailed state file
        states = {}
        if self.local_state_file.exists():
            try:
                with open(self.local_state_file, 'r') as f:
                    states = json.load(f)
            except Exception:
                pass

        for account_id in account_ids:
            if enabled:
                states[account_id] = {
                    'account_id': account_id,
                    'enabled_for_discovery': True,
                    'enabled_for_tagging': True,
                    'enabled_by': enabled_by,
                    'enabled_at': timestamp,
                    'disabled_by': None,
                    'disabled_at': None
                }
            elif account_id in states:
                states[account_id]['enabled_for_discovery'] = False
                states[account_id]['enabled_for_tagging'] = False
                states[account_id]['disabled_by'] = disabled_by
                states[account_id]['disabled_at'] = timestamp

        with open(self.local_state_file, 'w') as f:
            json.dump(states, f, indent=2, default=str)

    def _read_local_cache(self) -> List[str]:
        """Read enabled accounts from local cache"""
        if not self.local_cache_file.exists():
            return []

        try:
            with open(self.local_cache_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to read local cache: {str(e)}")
            return []

    def _update_core_accounts(self, account_ids: List[str], enabled: bool,
                              enabled_by: str = None, disabled_by: str = None):
        """Update account status records through bluearch-core storage."""
        try:
            now = datetime.now(timezone.utc).isoformat()
            org_account_names = self._get_org_account_names()
            for account_id in account_ids:
                existing = self._find_core_account_status(account_id)
                payload = dict(existing or {})
                payload.update({
                    'account_id': account_id,
                    'account_name': (
                        payload.get('account_name')
                        or org_account_names.get(account_id, account_id)
                    ),
                    'enabled_for_discovery': enabled,
                    'enabled_for_tagging': enabled,
                    'status': payload.get('status') or 'ACTIVE',
                })
                if enabled:
                    payload['enabled_at'] = now
                    payload['disabled_at'] = None
                else:
                    payload['disabled_at'] = now

                if existing:
                    request_core(
                        "PUT",
                        f"/api/v1/storage/core/account-status/{existing['id']}",
                        service_token=True,
                        json={"payload": payload},
                        timeout=10.0,
                    )
                else:
                    request_core(
                        "POST",
                        "/api/v1/storage/core/account-status",
                        service_token=True,
                        json={"payload": payload},
                        timeout=10.0,
                    )

            logger.info(f"Updated {len(account_ids)} accounts in bluearch-core")

        except Exception as e:
            logger.error(f"Failed to update bluearch-core account status: {str(e)}")

    def _find_core_account_status(self, account_id: str) -> Optional[Dict[str, Any]]:
        """Find an account-status record by account_id through core storage."""
        rows = request_core(
            "GET",
            "/api/v1/storage/core/account-status",
            service_token=True,
            params=[("filter", f"account_id={account_id}"), ("limit", 1)],
            timeout=10.0,
        )
        if not rows:
            return None
        return rows[0].get("payload", rows[0])

    def _get_org_account_names(self) -> Dict[str, str]:
        """Best-effort account name lookup from AWS Organizations."""
        try:
            return {
                account["Id"]: account.get("Name", account["Id"])
                for account in aws_auth.get_organization_accounts()
            }
        except Exception:
            return {}

    def check_table_exists(self) -> bool:
        """Check if DynamoDB table exists and is accessible"""
        self._ensure_dynamodb_initialized()
        return self.dynamodb_available

    def get_sync_status(self) -> Dict[str, Any]:
        """Get synchronization status"""
        # Don't initialize DynamoDB just for status check
        return {
            'dynamodb_available': self.dynamodb_available if self._dynamodb_initialized else None,
            'dynamodb_checked': self._dynamodb_initialized,
            'last_sync_time': self.last_sync_time,
            'sync_interval': self.sync_interval,
            'local_cache_exists': self.local_cache_file.exists(),
            'local_state_exists': self.local_state_file.exists(),
            'table_name': self.table_name
        }


# Singleton instance
dynamodb_state = DynamoDBStateService()
