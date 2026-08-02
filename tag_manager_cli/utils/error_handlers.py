"""Reusable error handling decorators and utilities for Tag Manager CLI.

This module provides decorators that can be applied to command functions
to handle common error scenarios consistently across the CLI.
"""

import functools
import typer
from typing import Callable, Optional
from botocore.exceptions import (
    NoCredentialsError,
    ProfileNotFound,
    ClientError,
    EndpointConnectionError,
    TokenRetrievalError
)

from .console_safe import safe_print
from .core_client import request_core
from .exceptions import (
    AWSCredentialsError,
    AWSResourceNotFoundError,
    DatabaseEmptyError,
    DatabaseNotInitializedError,
    ValidationError,
    AWSServiceError,
    ConfigurationError,
    DiscoveryNotRunError,
    TagManagerError
)


def handle_permission_error(error: ClientError, context: Optional[str] = None):
    """Handle AWS permission errors (403, AccessDenied, etc.) with helpful guidance.

    This function provides consistent error messaging for permission-related errors
    across the entire application, suggesting the 'setup validate' command to check
    which specific permissions are missing.

    Args:
        error: The ClientError from boto3/botocore
        context: Optional context about what operation was being performed
    """
    error_code = error.response.get('Error', {}).get('Code', 'Unknown')
    error_message = error.response.get('Error', {}).get('Message', str(error))

    # Extract the specific AWS action that failed if available
    operation = None
    if hasattr(error, 'operation_name'):
        operation = error.operation_name

    # Display the main error
    safe_print("ERROR PERMISSION DENIED - AWS IAM permission error", "red")

    # Show context if provided
    if context:
        safe_print(f"\nContext: {context}", "dim")

    # Show the specific error details
    safe_print(f"\nError Code: {error_code}", "yellow")
    if operation:
        safe_print(f"Failed Operation: {operation}", "yellow")
    safe_print(f"Details: {error_message}", "dim")

    # Provide actionable guidance
    safe_print("\n" + "="*60, "dim")
    safe_print("\nACTION REQUIRED - Check your IAM permissions", "bold yellow")
    safe_print("\nYour AWS user/role is missing required permissions for this operation.", "yellow")

    safe_print("\nTo fix this issue:", "white")
    safe_print("\n1. Run the permission validator to see all missing permissions:", "cyan")
    safe_print("   bluearch-aws-tags setup validate", "bold cyan")

    safe_print("\n2. The validator will:", "white")
    safe_print("   - Check your current AWS credentials", "dim")
    safe_print("   - Compare your permissions against required ones", "dim")
    safe_print("   - Show exactly which permissions are missing", "dim")
    safe_print("   - Provide a JSON policy to add the missing permissions", "dim")

    safe_print("\n3. Copy the generated JSON policy and add it to your IAM user/role", "cyan")

    safe_print("\nNOTE If you see multiple permission errors, run 'setup validate' once", "yellow")
    safe_print("to get a complete list of all missing permissions.", "yellow")

    safe_print("\n" + "="*60, "dim")

    raise typer.Exit(code=1)


def require_aws_credentials(func: Callable) -> Callable:
    """Decorator that validates AWS credentials before running a command.

    Checks if AWS credentials are valid by calling aws_auth.check_aws_credentials().
    If credentials are invalid or expired, shows a helpful error message and exits.

    Usage:
        @require_aws_credentials
        def my_command():
            # AWS operations here
            pass
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        from .aws_auth import aws_auth

        if not aws_auth.check_aws_credentials():
            safe_print("ERROR AWS credentials are not valid or have expired!", "red")
            safe_print("\nPlease refresh your AWS credentials:", "yellow")
            safe_print("  1. For SSO: aws sso login --profile <your-profile>", "dim")
            safe_print("  2. For access keys: export AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY", "dim")
            safe_print("  3. Verify with: aws sts get-caller-identity", "dim")
            safe_print("  4. Then run this command again", "dim")
            raise typer.Exit(code=1)

        return func(*args, **kwargs)

    return wrapper


def require_database(func: Callable) -> Callable:
    """Decorator that ensures the database is initialized before running a command.

    Checks if database tables exist and are accessible.
    If not, shows error message about running 'database init'.

    Usage:
        @require_database
        def my_command():
            # Database operations here
            pass
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            health = request_core("GET", "/api/v1/core/health", service_token=False, timeout=2.0)
            if health.get("status") != "ok" or not health.get("db_ready", False):
                raise RuntimeError(health.get("status") or "database not ready")
            db_status = health.get("database") or health.get("db") or {}
            if isinstance(db_status, dict) and db_status.get("status") in {"error", "unavailable"}:
                raise RuntimeError(db_status.get("message") or db_status.get("status"))
        except Exception as e:
            safe_print("ERROR bluearch-aws-core database is not initialized or accessible!", "red")
            safe_print(f"\nDetails: {str(e)}", "dim")
            safe_print("\nStart the shared runtime first:", "yellow")
            safe_print("  bluearch-aws-core start --daemon", "cyan")
            raise typer.Exit(code=1)

        return func(*args, **kwargs)

    return wrapper


def require_discovery(func: Callable) -> Callable:
    """Decorator that ensures resources have been discovered before running a command.

    Checks if the database contains any resources. If not, prompts user to run
    'discover all' to populate the database.

    Usage:
        @require_discovery
        def my_command():
            # Operate on discovered resources
            pass
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            summary = request_core("GET", "/api/v1/resources/summary", timeout=5.0)
            resource_count = int(summary.get("total") or 0)
            if resource_count == 0:
                safe_print("WARN No resources found in bluearch-aws-core inventory!", "yellow")
                safe_print("\nIt looks like you haven't discovered AWS resources yet.", "yellow")
                safe_print("Run resource discovery first:", "white")
                safe_print("  bluearch-aws-tags discover all", "cyan")
                safe_print("\nThis will scan your AWS accounts and populate the shared inventory.", "dim")
                raise typer.Exit(code=1)
        except typer.Exit:
            # Re-raise typer.Exit to propagate it
            raise
        except Exception as e:
            safe_print(f"ERROR Could not check bluearch-aws-core inventory: {str(e)}", "red")
            raise typer.Exit(code=1)

        return func(*args, **kwargs)

    return wrapper


def handle_aws_errors(func: Callable) -> Callable:
    """Decorator that catches and formats AWS-specific errors.

    Catches common AWS exceptions and provides helpful error messages with
    recovery suggestions.

    Usage:
        @handle_aws_errors
        def my_command():
            # AWS operations that might fail
            pass
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)

        except AWSCredentialsError as e:
            safe_print(f"ERROR {str(e)}", "red")
            safe_print("\nPlease refresh your AWS credentials:", "yellow")
            safe_print("  aws sso login --profile <your-profile>", "cyan")
            raise typer.Exit(code=1)

        except (NoCredentialsError, ProfileNotFound) as e:
            safe_print("ERROR AWS credentials not found!", "red")
            safe_print(f"\nDetails: {str(e)}", "dim")
            safe_print("\nPlease configure AWS credentials:", "yellow")
            safe_print("  1. Set AWS_PROFILE environment variable, OR", "dim")
            safe_print("  2. Export AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY", "dim")
            raise typer.Exit(code=1)

        except TokenRetrievalError as e:
            safe_print("ERROR AWS SSO token has expired!", "red")
            safe_print(f"\nDetails: {str(e)}", "dim")
            safe_print("\nPlease refresh your SSO session:", "yellow")
            safe_print("  aws sso login --profile <your-profile>", "cyan")
            raise typer.Exit(code=1)

        except EndpointConnectionError as e:
            safe_print("ERROR Cannot connect to AWS!", "red")
            safe_print(f"\nDetails: {str(e)}", "dim")
            safe_print("\nPossible causes:", "yellow")
            safe_print("  1. No internet connection", "dim")
            safe_print("  2. AWS service outage", "dim")
            safe_print("  3. Firewall blocking AWS endpoints", "dim")
            raise typer.Exit(code=1)

        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            error_message = e.response.get('Error', {}).get('Message', str(e))

            # Handle permission errors with specific guidance
            if error_code in ['AccessDenied', 'UnauthorizedOperation', 'AccessDeniedException', 'Forbidden']:
                handle_permission_error(e)
            else:
                safe_print(f"ERROR AWS operation failed: {error_code}", "red")
                safe_print(f"\nDetails: {error_message}", "dim")

                # Provide specific guidance based on error code
                if error_code == 'ResourceNotFoundException':
                    safe_print("\nThe requested AWS resource does not exist.", "yellow")
                elif error_code == 'ExpiredToken':
                    safe_print("\nYour AWS session has expired.", "yellow")
                    safe_print("Run: aws sso login --profile <your-profile>", "cyan")

                raise typer.Exit(code=1)

        except AWSServiceError as e:
            safe_print(f"ERROR {str(e)}", "red")
            safe_print(f"\nService: {e.service}, Operation: {e.operation}", "dim")
            if e.original_error:
                safe_print(f"Underlying error: {str(e.original_error)}", "dim")
            raise typer.Exit(code=1)

    return wrapper


def handle_database_errors(func: Callable) -> Callable:
    """Decorator that catches and formats database-specific errors.

    Catches database exceptions and provides helpful error messages with
    recovery suggestions.

    Usage:
        @handle_database_errors
        def my_command():
            # Database operations that might fail
            pass
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)

        except DatabaseEmptyError as e:
            safe_print(f"WARN {str(e)}", "yellow")
            safe_print("\nRun resource discovery to populate the database:", "white")
            safe_print("  bluearch-aws-tags discover all", "cyan")
            raise typer.Exit(code=1)

        except DatabaseNotInitializedError as e:
            safe_print(f"ERROR {str(e)}", "red")
            safe_print("\nInitialize the database:", "yellow")
            safe_print("  bluearch-aws-tags setup database", "cyan")
            raise typer.Exit(code=1)

        except typer.Exit:
            # Re-raise typer.Exit without treating it as an error
            raise

        except (SystemExit, KeyboardInterrupt):
            # Re-raise system exits and keyboard interrupts
            raise

        except Exception as e:
            # Catch SQLAlchemy and other database errors
            error_str = str(e).lower()
            if 'no such table' in error_str or 'does not exist' in error_str:
                safe_print("ERROR Database tables not found!", "red")
                safe_print("\nRun database migrations:", "yellow")
                safe_print("  bluearch-aws-tags setup database", "cyan")
            elif 'locked' in error_str:
                safe_print("ERROR Database is locked!", "red")
                safe_print("\nAnother process may be using the database.", "yellow")
                safe_print("Wait a moment and try again.", "dim")
            else:
                safe_print(f"ERROR Database operation failed: {str(e)}", "red")
                safe_print("\nCheck database status:", "yellow")
                safe_print("  bluearch-aws-tags setup validate", "cyan")

            raise typer.Exit(code=1)

    return wrapper


def handle_validation_errors(func: Callable) -> Callable:
    """Decorator that catches and formats validation errors.

    Catches ValidationError and ConfigurationError exceptions.

    Usage:
        @handle_validation_errors
        def my_command():
            # Operations with validation
            pass
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)

        except ValidationError as e:
            safe_print(f"ERROR Validation failed: {str(e)}", "red")
            if e.field:
                safe_print(f"\nField: {e.field}", "dim")
            safe_print("\nPlease check your input and try again.", "yellow")
            raise typer.Exit(code=1)

        except ConfigurationError as e:
            safe_print(f"ERROR {str(e)}", "red")
            if e.setting:
                safe_print(f"\nSetting: {e.setting}", "dim")
            safe_print("\nCheck your configuration:", "yellow")
            safe_print("  bluearch-aws-tags setup validate", "cyan")
            raise typer.Exit(code=1)

    return wrapper


def handle_all_errors(func: Callable) -> Callable:
    """Decorator that provides comprehensive error handling for all error types.

    This is a convenience decorator that combines AWS, database, and validation
    error handling. Use this for commands that might encounter any type of error.

    Usage:
        @handle_all_errors
        def my_command():
            # Any operations
            pass
    """

    @functools.wraps(func)
    @handle_validation_errors
    @handle_database_errors
    @handle_aws_errors
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)

        except TagManagerError as e:
            # Catch any custom exceptions not handled by specific decorators
            safe_print(f"ERROR {str(e)}", "red")
            raise typer.Exit(code=1)

        except typer.Exit:
            # Re-raise typer.Exit to propagate exit codes
            raise

        except KeyboardInterrupt:
            safe_print("\n\nOperation cancelled by user.", "yellow")
            raise typer.Exit(code=130)

        except Exception as e:
            # Catch-all for unexpected errors
            safe_print(f"ERROR Unexpected error: {str(e)}", "red")
            safe_print("\nIf this problem persists, please contact your system administrator.", "yellow")
            raise typer.Exit(code=1)

    return wrapper


def format_error_message(error: Exception, context: Optional[str] = None) -> str:
    """Format an error message consistently.

    Args:
        error: The exception that occurred
        context: Optional context about what operation was being performed

    Returns:
        Formatted error message string
    """
    if isinstance(error, TagManagerError):
        message = str(error)
    else:
        message = f"Unexpected error: {str(error)}"

    if context:
        message = f"{context}: {message}"

    return message


def check_permission_error(error: Exception) -> bool:
    """Check if an exception is a permission-related error.

    Args:
        error: The exception to check

    Returns:
        True if this is a permission error, False otherwise
    """
    if isinstance(error, ClientError):
        error_code = error.response.get('Error', {}).get('Code', '')
        return error_code in ['AccessDenied', 'UnauthorizedOperation', 'AccessDeniedException', 'Forbidden']
    return False
