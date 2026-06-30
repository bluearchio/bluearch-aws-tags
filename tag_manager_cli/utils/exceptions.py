"""Custom exception classes for Tag Manager CLI.

This module provides specific exception types for different error scenarios,
enabling better error handling and more helpful error messages.
"""


class TagManagerError(Exception):
    """Base exception for all Tag Manager CLI errors."""
    pass


class AWSCredentialsError(TagManagerError):
    """Raised when AWS credentials are missing, invalid, or expired.

    This exception indicates that the user needs to refresh their credentials
    or configure AWS authentication properly.
    """

    def __init__(self, message: str = None, profile: str = None):
        self.profile = profile
        if message is None:
            if profile:
                message = f"AWS credentials for profile '{profile}' are invalid or expired"
            else:
                message = "AWS credentials are not valid or have expired"
        super().__init__(message)


class AWSResourceNotFoundError(TagManagerError):
    """Raised when an AWS resource cannot be found.

    This could be due to incorrect ARN, resource deleted, or insufficient permissions.
    """

    def __init__(self, resource_id: str = None, resource_type: str = None):
        self.resource_id = resource_id
        self.resource_type = resource_type
        message = "AWS resource not found"
        if resource_type and resource_id:
            message = f"{resource_type} '{resource_id}' not found"
        elif resource_id:
            message = f"Resource '{resource_id}' not found"
        super().__init__(message)


class DatabaseEmptyError(TagManagerError):
    """Raised when the database has no resources and discovery is needed.

    This indicates the user needs to run 'discover all' to populate
    the database with AWS resources.
    """

    def __init__(self, message: str = None):
        if message is None:
            message = "No resources found in database - run discovery first"
        super().__init__(message)


class DatabaseNotInitializedError(TagManagerError):
    """Raised when the database hasn't been initialized.

    This indicates database schema needs to be created or migrations need to run.
    """

    def __init__(self, message: str = None):
        if message is None:
            message = "Database not initialized - run 'database init'"
        super().__init__(message)


class ValidationError(TagManagerError):
    """Raised when input validation fails.

    This could be invalid tag keys, malformed ARNs, invalid configuration, etc.
    """

    def __init__(self, field: str = None, message: str = None):
        self.field = field
        if message is None and field:
            message = f"Invalid value for '{field}'"
        elif message is None:
            message = "Validation failed"
        super().__init__(message)


class AWSServiceError(TagManagerError):
    """Raised when an AWS API call fails.

    This wraps AWS service exceptions with more context.
    """

    def __init__(self, service: str, operation: str, original_error: Exception = None):
        self.service = service
        self.operation = operation
        self.original_error = original_error

        message = f"AWS {service} operation '{operation}' failed"
        if original_error:
            message += f": {str(original_error)}"
        super().__init__(message)


class ConfigurationError(TagManagerError):
    """Raised when configuration is invalid or missing.

    This could be missing environment variables, invalid settings, etc.
    """

    def __init__(self, setting: str = None, message: str = None):
        self.setting = setting
        if message is None and setting:
            message = f"Configuration error: '{setting}' is not properly configured"
        elif message is None:
            message = "Configuration error"
        super().__init__(message)


class DiscoveryNotRunError(TagManagerError):
    """Raised when an operation requires discovered resources but none exist.

    Similar to DatabaseEmptyError but specifically for operations that
    require recent resource discovery.
    """

    def __init__(self, message: str = None):
        if message is None:
            message = "Resource discovery has not been run - run 'discover all'"
        super().__init__(message)


class CredentialConflictError(TagManagerError):
    """Raised when both AWS_PROFILE and credential environment variables are set.

    This indicates a conflict in authentication methods that could lead to
    unexpected behavior.
    """

    def __init__(self, profile: str = None, message: str = None):
        self.profile = profile
        if message is None:
            if profile:
                message = (
                    f"Credential conflict detected: AWS_PROFILE='{profile}' is set "
                    "but AWS access keys are also in environment. "
                    "Clear one authentication method to avoid conflicts."
                )
            else:
                message = (
                    "Credential conflict: Both AWS_PROFILE and AWS credentials are set. "
                    "Clear one authentication method to avoid conflicts."
                )
        super().__init__(message)


class RegionNotConfiguredError(TagManagerError):
    """Raised when AWS region cannot be determined from any source.

    This indicates the region needs to be configured in AWS config file,
    environment variables, or passed explicitly.
    """

    def __init__(self, profile: str = None, message: str = None):
        self.profile = profile
        if message is None:
            if profile:
                message = (
                    f"AWS region not configured for profile '{profile}'. "
                    "Set region in ~/.aws/config, export AWS_DEFAULT_REGION, "
                    "or pass region explicitly."
                )
            else:
                message = (
                    "AWS region not configured. Set AWS_DEFAULT_REGION environment variable "
                    "or configure region in AWS config file."
                )
        super().__init__(message)
