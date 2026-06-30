"""
AWS Account Iterator for Cross-Account Operations

This module provides utilities for iterating through AWS Organization accounts
with support for filtering, parallel execution, and error handling.
"""

import logging
from typing import List, Dict, Optional, Callable, Any, Set
from dataclasses import dataclass
from enum import Enum
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import time

from botocore.exceptions import ClientError
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
from rich.table import Table

from ..utils.aws_auth import aws_auth
from ..utils.error_handlers import handle_aws_errors

logger = logging.getLogger(__name__)
console = Console()


class AccountStatus(Enum):
    """AWS Account status"""
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    PENDING_CLOSURE = "PENDING_CLOSURE"
    CLOSED = "CLOSED"


@dataclass
class AccountInfo:
    """Information about an AWS account"""
    account_id: str
    account_name: str
    email: str
    status: AccountStatus
    arn: str
    joined_timestamp: Optional[datetime] = None
    role_configured: Optional[bool] = None
    last_scan_timestamp: Optional[datetime] = None
    error_message: Optional[str] = None


@dataclass
class IterationResult:
    """Result of iterating through accounts"""
    total_accounts: int
    processed_accounts: int
    successful_accounts: List[str]
    failed_accounts: List[str]
    skipped_accounts: List[str]
    results: Dict[str, Any]
    errors: Dict[str, str]


class AccountIterator:
    """Iterate through AWS Organization accounts with filtering and parallel execution"""

    def __init__(self):
        self.accounts_cache: Optional[List[AccountInfo]] = None
        self.cache_timestamp: Optional[datetime] = None
        self.cache_ttl_seconds = 300  # 5 minutes
        self.default_role_name = "BlueArchRole"
        self.max_workers = 10  # Max parallel account operations
        self.retry_max_attempts = 3
        self.retry_delay_seconds = 2

    def _refresh_accounts_cache(self, force: bool = False):
        """Refresh the accounts cache if needed"""
        now = datetime.now()

        if not force and self.accounts_cache and self.cache_timestamp:
            if (now - self.cache_timestamp).total_seconds() < self.cache_ttl_seconds:
                return

        try:
            # Get accounts from Organizations
            org_accounts = aws_auth.get_organization_accounts()

            # Convert to AccountInfo objects
            self.accounts_cache = []
            for account in org_accounts:
                self.accounts_cache.append(
                    AccountInfo(
                        account_id=account['Id'],
                        account_name=account['Name'],
                        email=account['Email'],
                        status=AccountStatus(account['Status']),
                        arn=account['Arn'],
                        joined_timestamp=account.get('JoinedTimestamp')
                    )
                )

            self.cache_timestamp = now
            logger.info(f"Refreshed accounts cache: {len(self.accounts_cache)} accounts")

        except Exception as e:
            logger.error(f"Failed to refresh accounts cache: {str(e)}")
            raise

    def list_accounts(
        self,
        include_suspended: bool = False,
        validate_access: bool = False,
        role_name: Optional[str] = None
    ) -> List[AccountInfo]:
        """
        List all Organization accounts with optional filtering.

        Args:
            include_suspended: Include suspended accounts
            validate_access: Test role assumption for each account
            role_name: Role name to validate (default: BlueArchRole)

        Returns:
            List of AccountInfo objects
        """
        self._refresh_accounts_cache()

        if not self.accounts_cache:
            return []

        # Filter accounts
        filtered_accounts = []
        for account in self.accounts_cache:
            # Skip suspended accounts if requested
            if not include_suspended and account.status != AccountStatus.ACTIVE:
                continue

            filtered_accounts.append(account)

        # Validate access if requested
        if validate_access:
            role = role_name or self.default_role_name
            console.print(f"\n[bold]Testing access to {len(filtered_accounts)} accounts...[/bold]")

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
                transient=True
            ) as progress:
                task = progress.add_task(
                    f"Validating access...",
                    total=len(filtered_accounts)
                )

                for account in filtered_accounts:
                    account.role_configured = aws_auth.validate_cross_account_access(
                        account_id=account.account_id,
                        role_name=role
                    )
                    progress.advance(task)

        return filtered_accounts

    def iterate_accounts(
        self,
        function: Callable[[str], Any],
        account_ids: Optional[List[str]] = None,
        account_filter: Optional[Callable[[AccountInfo], bool]] = None,
        skip_suspended: bool = True,
        validate_access: bool = True,
        role_name: Optional[str] = None,
        max_workers: Optional[int] = None,
        continue_on_error: bool = True,
        show_progress: bool = True
    ) -> IterationResult:
        """
        Iterate through accounts and execute a function on each.

        Args:
            function: Function to execute for each account (receives account_id)
            account_ids: Specific account IDs to process (None = all)
            account_filter: Custom filter function for accounts
            skip_suspended: Skip suspended accounts
            validate_access: Validate role assumption before processing
            role_name: Role name to use for validation
            max_workers: Max parallel workers (default: 10)
            continue_on_error: Continue processing if an account fails
            show_progress: Show progress bar

        Returns:
            IterationResult with processing details
        """
        # Get accounts
        accounts = self.list_accounts(
            include_suspended=not skip_suspended,
            validate_access=validate_access,
            role_name=role_name
        )

        # Apply filters
        filtered_accounts = []
        skipped_accounts = []

        for account in accounts:
            # Check specific account IDs filter
            if account_ids and account.account_id not in account_ids:
                continue

            # Check custom filter
            if account_filter and not account_filter(account):
                skipped_accounts.append(account.account_id)
                continue

            # Check role configuration if validated
            if validate_access and not account.role_configured:
                skipped_accounts.append(account.account_id)
                logger.warning(f"Skipping account {account.account_id} - role not configured")
                continue

            filtered_accounts.append(account)

        if not filtered_accounts:
            return IterationResult(
                total_accounts=len(accounts),
                processed_accounts=0,
                successful_accounts=[],
                failed_accounts=[],
                skipped_accounts=skipped_accounts,
                results={},
                errors={}
            )

        # Process accounts
        successful = []
        failed = []
        results = {}
        errors = {}
        workers = max_workers or self.max_workers

        if show_progress:
            console.print(f"\n[bold]Processing {len(filtered_accounts)} accounts...[/bold]")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            console=console,
            disable=not show_progress
        ) as progress:
            task = progress.add_task(
                f"Processing accounts...",
                total=len(filtered_accounts)
            )

            with ThreadPoolExecutor(max_workers=workers) as executor:
                # Submit all tasks
                future_to_account = {
                    executor.submit(
                        self._process_account_with_retry,
                        function,
                        account.account_id
                    ): account
                    for account in filtered_accounts
                }

                # Process results as they complete
                for future in as_completed(future_to_account):
                    account = future_to_account[future]

                    try:
                        result = future.result()
                        successful.append(account.account_id)
                        results[account.account_id] = result
                    except Exception as e:
                        failed.append(account.account_id)
                        errors[account.account_id] = str(e)
                        logger.error(f"Failed processing account {account.account_id}: {str(e)}")

                        if not continue_on_error:
                            # Cancel remaining tasks
                            for f in future_to_account:
                                f.cancel()
                            break

                    progress.advance(task)

        return IterationResult(
            total_accounts=len(accounts),
            processed_accounts=len(successful) + len(failed),
            successful_accounts=successful,
            failed_accounts=failed,
            skipped_accounts=skipped_accounts,
            results=results,
            errors=errors
        )

    def _process_account_with_retry(self, function: Callable, account_id: str) -> Any:
        """Process an account with retry logic"""
        last_error = None

        for attempt in range(self.retry_max_attempts):
            try:
                return function(account_id)

            except ClientError as e:
                last_error = e
                error_code = e.response['Error']['Code']

                # Don't retry certain errors
                if error_code in ['AccessDenied', 'UnauthorizedOperation', 'InvalidParameterValue']:
                    raise

                # Retry with exponential backoff
                if attempt < self.retry_max_attempts - 1:
                    delay = self.retry_delay_seconds * (2 ** attempt)
                    logger.debug(f"Retrying account {account_id} after {delay} seconds...")
                    time.sleep(delay)

            except Exception as e:
                # Non-AWS errors, don't retry
                raise

        # All retries failed
        raise last_error

    def get_account_groups(
        self,
        group_by_ou: bool = True
    ) -> Dict[str, List[AccountInfo]]:
        """
        Get accounts grouped by organizational units or other criteria.

        Args:
            group_by_ou: Group by organizational unit

        Returns:
            Dictionary mapping group names to account lists
        """
        groups = {}

        if group_by_ou:
            try:
                org_client = aws_auth.get_client('organizations')

                # Get root ID
                roots = org_client.list_roots()
                root_id = roots['Roots'][0]['Id']

                # Get all OUs recursively
                ous = self._get_all_ous(root_id)

                # Group accounts by OU
                for ou_id, ou_name in ous.items():
                    accounts_in_ou = []

                    # Get accounts directly in this OU
                    paginator = org_client.get_paginator('list_accounts_for_parent')
                    for page in paginator.paginate(ParentId=ou_id):
                        for account in page['Accounts']:
                            if account['Status'] == 'ACTIVE':
                                accounts_in_ou.append(
                                    AccountInfo(
                                        account_id=account['Id'],
                                        account_name=account['Name'],
                                        email=account['Email'],
                                        status=AccountStatus(account['Status']),
                                        arn=account['Arn']
                                    )
                                )

                    if accounts_in_ou:
                        groups[ou_name] = accounts_in_ou

                # Add root accounts
                root_accounts = []
                paginator = org_client.get_paginator('list_accounts_for_parent')
                for page in paginator.paginate(ParentId=root_id):
                    for account in page['Accounts']:
                        if account['Status'] == 'ACTIVE':
                            root_accounts.append(
                                AccountInfo(
                                    account_id=account['Id'],
                                    account_name=account['Name'],
                                    email=account['Email'],
                                    status=AccountStatus(account['Status']),
                                    arn=account['Arn']
                                )
                            )

                if root_accounts:
                    groups['Root'] = root_accounts

            except Exception as e:
                logger.error(f"Failed to group accounts by OU: {str(e)}")
                # Fall back to single group
                self._refresh_accounts_cache()
                if self.accounts_cache:
                    groups['All Accounts'] = [
                        acc for acc in self.accounts_cache
                        if acc.status == AccountStatus.ACTIVE
                    ]

        return groups

    def _get_all_ous(self, parent_id: str, parent_path: str = "") -> Dict[str, str]:
        """Recursively get all OUs under a parent"""
        ous = {}

        try:
            org_client = aws_auth.get_client('organizations')

            # List OUs under this parent
            paginator = org_client.get_paginator('list_organizational_units_for_parent')
            for page in paginator.paginate(ParentId=parent_id):
                for ou in page['OrganizationalUnits']:
                    ou_path = f"{parent_path}/{ou['Name']}" if parent_path else ou['Name']
                    ous[ou['Id']] = ou_path

                    # Recursively get child OUs
                    child_ous = self._get_all_ous(ou['Id'], ou_path)
                    ous.update(child_ous)

        except Exception as e:
            logger.error(f"Failed to get OUs under {parent_id}: {str(e)}")

        return ous

    def display_accounts_table(
        self,
        accounts: Optional[List[AccountInfo]] = None,
        show_access_status: bool = True
    ):
        """Display accounts in a formatted table"""
        if accounts is None:
            accounts = self.list_accounts(
                include_suspended=True,
                validate_access=show_access_status
            )

        # Create table
        table = Table(title="AWS Organization Accounts")
        table.add_column("Account ID", style="cyan")
        table.add_column("Name", style="white")
        table.add_column("Status", justify="center")
        if show_access_status:
            table.add_column("Access", justify="center")
        table.add_column("Email", style="dim")

        # Add rows
        for account in accounts:
            # Status column
            if account.status == AccountStatus.ACTIVE:
                status = "[green]ACTIVE[/green]"
            elif account.status == AccountStatus.SUSPENDED:
                status = "[yellow]SUSPENDED[/yellow]"
            else:
                status = f"[red]{account.status.value}[/red]"

            # Access column
            access = ""
            if show_access_status and account.role_configured is not None:
                access = "[green]✓[/green]" if account.role_configured else "[red]✗[/red]"

            row = [account.account_id, account.account_name, status]
            if show_access_status:
                row.append(access)
            row.append(account.email)

            table.add_row(*row)

        console.print(table)

        # Summary
        active_count = sum(1 for a in accounts if a.status == AccountStatus.ACTIVE)
        suspended_count = sum(1 for a in accounts if a.status == AccountStatus.SUSPENDED)

        console.print(f"\n[bold]Summary:[/bold]")
        console.print(f"Total accounts: {len(accounts)}")
        console.print(f"Active: {active_count}")
        console.print(f"Suspended: {suspended_count}")

        if show_access_status:
            configured_count = sum(1 for a in accounts if a.role_configured)
            console.print(f"Role configured: {configured_count}/{active_count} active accounts")


# Singleton instance
account_iterator = AccountIterator()