"""
Parallel Role Manager - Efficient cross-account role assumption.

This module provides utilities for parallel role assumption across multiple AWS accounts,
significantly improving performance when working with many accounts.
"""

import concurrent.futures
from typing import Dict, List, Optional, Tuple, Any, Callable
from dataclasses import dataclass
from datetime import datetime
import time

import boto3
from rich.console import Console
from rich.tree import Tree
from rich.live import Live
from rich.progress import Progress, SpinnerColumn, TextColumn

console = Console()


@dataclass
class RoleAssumptionResult:
    """Result of a role assumption attempt."""
    account_id: str
    account_name: Optional[str] = None
    success: bool = False
    session: Optional[Any] = None  # boto3.Session
    error_message: Optional[str] = None
    duration_ms: int = 0
    role_arn: Optional[str] = None


@dataclass
class AccountInfo:
    """Information about an AWS account."""
    account_id: str
    account_name: Optional[str] = None
    role_name: str = "BlueArchRole"
    external_id: Optional[str] = None
    region: Optional[str] = None


class ParallelRoleManager:
    """Manages parallel role assumption across multiple AWS accounts."""

    def __init__(
        self,
        aws_auth,  # AWSAuth instance
        max_workers: int = 10,
        show_progress: bool = True
    ):
        """
        Initialize the ParallelRoleManager.

        Args:
            aws_auth: Instance of AWSAuth for authentication
            max_workers: Maximum number of parallel workers
            show_progress: Whether to show progress indicators
        """
        self.aws_auth = aws_auth
        self.max_workers = max_workers
        self.show_progress = show_progress
        self._cache: Dict[str, RoleAssumptionResult] = {}

    def assume_roles_parallel(
        self,
        accounts: List[AccountInfo],
        progress_callback: Optional[Callable[[RoleAssumptionResult], None]] = None,
        use_tree_display: bool = True
    ) -> Dict[str, RoleAssumptionResult]:
        """
        Assume roles in multiple accounts in parallel.

        Args:
            accounts: List of AccountInfo objects
            progress_callback: Optional callback for progress updates
            use_tree_display: Whether to use Rich tree display for progress

        Returns:
            Dictionary mapping account_id to RoleAssumptionResult
        """
        results = {}

        if use_tree_display and self.show_progress:
            return self._assume_with_tree_display(accounts, progress_callback)
        elif self.show_progress:
            return self._assume_with_simple_progress(accounts, progress_callback)
        else:
            return self._assume_without_progress(accounts, progress_callback)

    def _assume_with_tree_display(
        self,
        accounts: List[AccountInfo],
        progress_callback: Optional[Callable[[RoleAssumptionResult], None]] = None
    ) -> Dict[str, RoleAssumptionResult]:
        """Assume roles with Rich tree display."""
        results = {}
        pending_accounts = {acc.account_id: acc for acc in accounts}
        successful_accounts = {}
        failed_accounts = {}

        def update_tree():
            tree = Tree("[bold]Assuming Roles Across Accounts[/bold]")

            # Successful accounts
            if successful_accounts:
                success_branch = tree.add("[green]✓ Successful[/green] ({})".format(
                    len(successful_accounts)
                ))
                for acc_id, acc in successful_accounts.items():
                    name = acc.account_name or "Unknown"
                    success_branch.add(f"[green]{acc_id}[/green] - {name}")

            # Failed accounts
            if failed_accounts:
                failed_branch = tree.add("[red]✗ Failed[/red] ({})".format(
                    len(failed_accounts)
                ))
                for acc_id, (acc, error) in failed_accounts.items():
                    name = acc.account_name or "Unknown"
                    failed_branch.add(f"[red]{acc_id}[/red] - {name}: {error[:50]}...")

            # Progress
            total = len(accounts)
            completed = len(successful_accounts) + len(failed_accounts)
            tree.add(f"Progress: {completed}/{total} accounts processed")

            return tree

        def assume_single_role(account: AccountInfo) -> RoleAssumptionResult:
            """Assume role for a single account."""
            start_time = time.time()
            result = RoleAssumptionResult(
                account_id=account.account_id,
                account_name=account.account_name
            )

            try:
                # Check cache first
                cache_key = f"{account.account_id}:{account.role_name}"
                if cache_key in self._cache:
                    cached = self._cache[cache_key]
                    # Return cached if still valid (within last 50 minutes)
                    if cached.success and (time.time() - cached.duration_ms / 1000) < 3000:
                        return cached

                # Build role ARN
                role_arn = f"arn:aws:iam::{account.account_id}:role/{account.role_name}"
                result.role_arn = role_arn

                # Get ExternalId if not provided
                external_id = account.external_id
                if not external_id:
                    external_id = self.aws_auth.get_cross_account_external_id()

                # Assume the role
                session = self.aws_auth.assume_role(
                    role_arn=role_arn,
                    external_id=external_id,
                    session_name=f"tag-manager-{account.account_id}"
                )

                result.success = True
                result.session = session
                console.print(f"[green]Successfully assumed role {role_arn}[/green]")

                # Cache the result
                self._cache[cache_key] = result

            except Exception as e:
                result.success = False
                result.error_message = str(e)
                console.print(f"[red]Failed to assume role for {account.account_id}: {str(e)}[/red]")

            result.duration_ms = int((time.time() - start_time) * 1000)
            return result

        # Process accounts in parallel with live display
        with Live(update_tree(), console=console, refresh_per_second=4) as live:
            with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                # Submit all tasks
                future_to_account = {
                    executor.submit(assume_single_role, account): account
                    for account in accounts
                }

                # Process completed futures
                for future in concurrent.futures.as_completed(future_to_account):
                    account = future_to_account[future]
                    try:
                        result = future.result()
                        results[account.account_id] = result

                        # Update display categories
                        if result.success:
                            successful_accounts[account.account_id] = account
                        else:
                            failed_accounts[account.account_id] = (account, result.error_message or "Unknown error")

                        # Remove from pending
                        pending_accounts.pop(account.account_id, None)

                        # Call progress callback if provided
                        if progress_callback:
                            progress_callback(result)

                        # Update display
                        live.update(update_tree())

                    except Exception as e:
                        # Handle unexpected errors
                        result = RoleAssumptionResult(
                            account_id=account.account_id,
                            account_name=account.account_name,
                            success=False,
                            error_message=str(e)
                        )
                        results[account.account_id] = result
                        failed_accounts[account.account_id] = (account, str(e))
                        pending_accounts.pop(account.account_id, None)
                        live.update(update_tree())

        return results

    def _assume_with_simple_progress(
        self,
        accounts: List[AccountInfo],
        progress_callback: Optional[Callable[[RoleAssumptionResult], None]] = None
    ) -> Dict[str, RoleAssumptionResult]:
        """Assume roles with simple progress bar."""
        results = {}

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
            transient=True
        ) as progress:
            task = progress.add_task(
                f"Assuming roles in {len(accounts)} accounts...",
                total=len(accounts)
            )

            def assume_single_role(account: AccountInfo) -> RoleAssumptionResult:
                """Assume role for a single account."""
                start_time = time.time()
                result = RoleAssumptionResult(
                    account_id=account.account_id,
                    account_name=account.account_name
                )

                try:
                    # Build role ARN
                    role_arn = f"arn:aws:iam::{account.account_id}:role/{account.role_name}"
                    result.role_arn = role_arn

                    # Get ExternalId if not provided
                    external_id = account.external_id
                    if not external_id:
                        external_id = self.aws_auth.get_cross_account_external_id()

                    # Assume the role
                    session = self.aws_auth.assume_role(
                        role_arn=role_arn,
                        external_id=external_id,
                        session_name=f"tag-manager-{account.account_id}"
                    )

                    result.success = True
                    result.session = session

                except Exception as e:
                    result.success = False
                    result.error_message = str(e)

                result.duration_ms = int((time.time() - start_time) * 1000)
                progress.advance(task)
                return result

            with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = [executor.submit(assume_single_role, account) for account in accounts]

                for future, account in zip(futures, accounts):
                    try:
                        result = future.result()
                        results[account.account_id] = result

                        if progress_callback:
                            progress_callback(result)

                    except Exception as e:
                        result = RoleAssumptionResult(
                            account_id=account.account_id,
                            account_name=account.account_name,
                            success=False,
                            error_message=str(e)
                        )
                        results[account.account_id] = result

        return results

    def _assume_without_progress(
        self,
        accounts: List[AccountInfo],
        progress_callback: Optional[Callable[[RoleAssumptionResult], None]] = None
    ) -> Dict[str, RoleAssumptionResult]:
        """Assume roles without progress display."""
        results = {}

        def assume_single_role(account: AccountInfo) -> RoleAssumptionResult:
            """Assume role for a single account."""
            start_time = time.time()
            result = RoleAssumptionResult(
                account_id=account.account_id,
                account_name=account.account_name
            )

            try:
                # Build role ARN
                role_arn = f"arn:aws:iam::{account.account_id}:role/{account.role_name}"
                result.role_arn = role_arn

                # Get ExternalId if not provided
                external_id = account.external_id
                if not external_id:
                    external_id = self.aws_auth.get_cross_account_external_id()

                # Assume the role
                session = self.aws_auth.assume_role(
                    role_arn=role_arn,
                    external_id=external_id,
                    session_name=f"tag-manager-{account.account_id}"
                )

                result.success = True
                result.session = session

            except Exception as e:
                result.success = False
                result.error_message = str(e)

            result.duration_ms = int((time.time() - start_time) * 1000)
            return result

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {executor.submit(assume_single_role, account): account for account in accounts}

            for future in concurrent.futures.as_completed(futures):
                account = futures[future]
                try:
                    result = future.result()
                    results[account.account_id] = result

                    if progress_callback:
                        progress_callback(result)

                except Exception as e:
                    result = RoleAssumptionResult(
                        account_id=account.account_id,
                        account_name=account.account_name,
                        success=False,
                        error_message=str(e)
                    )
                    results[account.account_id] = result

        return results

    def get_session_for_account(
        self,
        account_id: str,
        role_name: str = "BlueArchRole",
        external_id: Optional[str] = None
    ) -> Optional[Any]:  # Returns boto3.Session or None
        """
        Get a cached or new session for an account.

        Args:
            account_id: AWS account ID
            role_name: IAM role name
            external_id: Optional external ID

        Returns:
            boto3.Session or None if assumption fails
        """
        cache_key = f"{account_id}:{role_name}"

        # Check cache
        if cache_key in self._cache:
            cached = self._cache[cache_key]
            if cached.success:
                return cached.session

        # Assume new role
        account = AccountInfo(
            account_id=account_id,
            role_name=role_name,
            external_id=external_id
        )

        results = self._assume_without_progress([account])
        if account_id in results and results[account_id].success:
            return results[account_id].session

        return None

    def clear_cache(self):
        """Clear the session cache."""
        self._cache.clear()

    def get_cache_stats(self) -> Dict[str, int]:
        """Get cache statistics."""
        return {
            "total_cached": len(self._cache),
            "successful_cached": sum(1 for r in self._cache.values() if r.success),
            "failed_cached": sum(1 for r in self._cache.values() if not r.success)
        }


# Convenience function for quick parallel role assumption
def assume_roles_for_accounts(
    aws_auth,
    account_ids: List[str],
    role_name: str = "BlueArchRole",
    external_id: Optional[str] = None,
    max_workers: int = 10,
    show_progress: bool = True
) -> Dict[str, RoleAssumptionResult]:
    """
    Convenience function to assume roles for multiple accounts in parallel.

    Args:
        aws_auth: AWSAuth instance
        account_ids: List of AWS account IDs
        role_name: IAM role name to assume
        external_id: Optional external ID
        max_workers: Maximum parallel workers
        show_progress: Whether to show progress

    Returns:
        Dictionary mapping account_id to RoleAssumptionResult
    """
    manager = ParallelRoleManager(aws_auth, max_workers, show_progress)

    accounts = [
        AccountInfo(
            account_id=account_id,
            role_name=role_name,
            external_id=external_id
        )
        for account_id in account_ids
    ]

    return manager.assume_roles_parallel(accounts)