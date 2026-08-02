"""CloudFormation URL generation utilities for Tag Manager CLI."""

import urllib.parse
from typing import Optional


# Base URL for CloudFormation Quick Create
CLOUDFORMATION_QUICK_CREATE_BASE = "https://console.aws.amazon.com/cloudformation/home"

RAW_TEMPLATE_BASE = (
    "https://raw.githubusercontent.com/bluearchio/bluearch-aws-core/main/"
    "bluearch_core/templates"
)

# All available CloudFormation templates
TEMPLATE_NAMES = [
    "single_account_role.yaml",
    "cross_account_stack.yaml",
    "management_account_resources.yaml",
    "event_tracking_stack.yaml",
    "cur_stack.yaml",
]

# Backward-compatible alias (used by get_template_url)
TEMPLATE_URLS = {"prod": f"{RAW_TEMPLATE_BASE}/single_account_role.yaml", "dev": f"{RAW_TEMPLATE_BASE}/single_account_role.yaml"}

# Default stack name
DEFAULT_STACK_NAME = "BlueArchCLI-Role"

# Default role name
DEFAULT_ROLE_NAME = "BlueArchCLIRole"


def get_template_url(stage: str = "prod") -> str:
    """Get the S3 template URL for the given stage.

    Args:
        stage: The deployment stage ('prod' or 'dev')

    Returns:
        The S3 URL for the CloudFormation template
    """
    return TEMPLATE_URLS.get(stage, TEMPLATE_URLS["prod"])


def get_template_url_by_name(template_name: str, stage: str = "prod", cdn: bool = False) -> str:
    """Get the URL for a specific CloudFormation template.

    Args:
        template_name: Template filename (e.g. 'single_account_role.yaml')
        stage: The deployment stage ('prod' or 'dev')
        cdn: If True, return CloudFront CDN URL (for public download links).
             If False, return S3 URL (for CloudFormation TemplateURL).

    Returns:
        The URL for the CloudFormation template
    """
    return f"{RAW_TEMPLATE_BASE}/{template_name}"


def get_quick_create_url(
    region: str = "us-east-1",
    trusted_principal_mode: str = "AnyPrincipal",
    specific_principal_arn: Optional[str] = None,
    external_id: Optional[str] = None,
    deploying_user_arn: Optional[str] = None,
    stack_name: str = DEFAULT_STACK_NAME,
    stage: str = "prod",
) -> str:
    """Generate a CloudFormation Quick Create URL.

    This URL, when opened in a browser, will pre-populate the CloudFormation
    console with the template and parameters for deploying the TagManagerCLI role.

    Args:
        region: AWS region for the CloudFormation console
        trusted_principal_mode: Trust policy mode ('CurrentUser', 'AnyPrincipal', or 'SpecificArn')
        specific_principal_arn: IAM ARN for SpecificArn mode (required if mode is SpecificArn)
        external_id: Optional external ID for additional security
        deploying_user_arn: ARN of the user deploying (for CurrentUser mode)
        stack_name: Name for the CloudFormation stack
        stage: Deployment stage ('prod' or 'dev')

    Returns:
        A fully-formed CloudFormation Quick Create URL
    """
    template_url = get_template_url(stage)

    # Build query parameters
    params = {
        "templateURL": template_url,
        "stackName": stack_name,
        "param_TrustedPrincipalMode": trusted_principal_mode,
    }

    # Add specific principal ARN if mode is SpecificArn
    if trusted_principal_mode == "SpecificArn" and specific_principal_arn:
        params["param_SpecificPrincipalArn"] = specific_principal_arn
    else:
        params["param_SpecificPrincipalArn"] = ""

    # Add deploying user ARN if mode is CurrentUser
    if trusted_principal_mode == "CurrentUser" and deploying_user_arn:
        params["param_DeployingUserArn"] = deploying_user_arn
    else:
        params["param_DeployingUserArn"] = ""

    # Add external ID if provided
    if external_id:
        params["param_ExternalId"] = external_id
    else:
        params["param_ExternalId"] = ""

    # Build the URL
    query_string = urllib.parse.urlencode(params)
    url = f"{CLOUDFORMATION_QUICK_CREATE_BASE}?region={region}#/stacks/quickcreate?{query_string}"

    return url


def format_quick_create_instructions(
    url: str,
    region: str,
    trusted_principal_mode: str,
    current_user_arn: Optional[str] = None,
) -> str:
    """Format instructions for using the Quick Create URL.

    Args:
        url: The Quick Create URL
        region: AWS region
        trusted_principal_mode: Trust policy mode
        current_user_arn: Current user's ARN (if available)

    Returns:
        Formatted instructions string (ASCII-safe, no emojis)
    """
    mode_descriptions = {
        "CurrentUser": "Only your current IAM identity can assume this role",
        "AnyPrincipal": "Any IAM principal in your account can assume this role",
        "SpecificArn": "Only the specified IAM ARN can assume this role",
    }

    lines = [
        "",
        "=" * 70,
        "CloudFormation Quick Create URL",
        "=" * 70,
        "",
        f"Region: {region}",
        f"Trust Mode: {trusted_principal_mode}",
        f"Description: {mode_descriptions.get(trusted_principal_mode, 'Unknown mode')}",
    ]

    if trusted_principal_mode == "CurrentUser" and current_user_arn:
        lines.append(f"Trusted Principal: {current_user_arn}")

    lines.extend([
        "",
        "Instructions:",
        "1. Click the URL below (or copy and paste into your browser)",
        "2. Review the stack parameters in the CloudFormation console",
        "3. Check 'I acknowledge that AWS CloudFormation might create IAM resources'",
        "4. Click 'Create stack'",
        "5. Wait for the stack to complete (usually 1-2 minutes)",
        "6. Run 'bluearch-aws-tags setup assume-role' to configure the CLI",
        "",
        "Quick Create URL:",
        "-" * 70,
        url,
        "-" * 70,
        "",
    ])

    return "\n".join(lines)


def get_stack_console_url(region: str, stack_name: str = DEFAULT_STACK_NAME) -> str:
    """Get the CloudFormation console URL for viewing a stack.

    Args:
        region: AWS region
        stack_name: Name of the CloudFormation stack

    Returns:
        URL to view the stack in the CloudFormation console
    """
    encoded_stack = urllib.parse.quote(stack_name)
    return f"https://{region}.console.aws.amazon.com/cloudformation/home?region={region}#/stacks/stackinfo?filteringText={encoded_stack}"
