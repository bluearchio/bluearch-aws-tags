"""AWS Organizations service for tag policy management."""

import json
from typing import Dict, List, Optional, Any
from datetime import datetime
import boto3
from botocore.exceptions import ClientError, BotoCoreError
from rich.console import Console
from rich.table import Table

console = Console()


class OrganizationsService:
    """Service for interacting with AWS Organizations Tag Policies."""

    def __init__(self, session: Optional[boto3.Session] = None):
        """Initialize the Organizations service.

        Args:
            session: Boto3 session. If not provided, default session is used.
        """
        if session is None:
            session = boto3.Session()

        self.session = session
        self.org_client = session.client('organizations')
        self.sts_client = session.client('sts')
        self.tagging_client = session.client('resourcegroupstaggingapi')

    def check_access(self) -> Dict[str, Any]:
        """Check AWS Organizations access and tag policy status.

        Returns:
            Dictionary with access information:
            - has_access: Boolean indicating if Organizations is accessible
            - org_id: Organization ID (if accessible)
            - master_account: Master account ID
            - current_account: Current account ID
            - tag_policies_enabled: Boolean indicating if tag policies are enabled
            - error: Error message if access failed
        """
        try:
            # Get current account identity
            identity = self.sts_client.get_caller_identity()
            current_account = identity['Account']

            # Check organization access
            org_response = self.org_client.describe_organization()
            organization = org_response['Organization']

            # Check if tag policies are enabled
            roots_response = self.org_client.list_roots()
            root_id = roots_response['Roots'][0]['Id'] if roots_response['Roots'] else None

            # Initialize policy_types for later use
            policy_types = organization.get('AvailablePolicyTypes', [])

            # Check policy types on the root - this is the authoritative source
            tag_policies_enabled = False
            if roots_response.get('Roots'):
                root = roots_response['Roots'][0]
                root_policy_types = root.get('PolicyTypes', [])
                tag_policies_enabled = any(
                    p.get('Type') == 'TAG_POLICY' and p.get('Status') == 'ENABLED'
                    for p in root_policy_types
                )

            # Fallback to organization's available policy types if root doesn't have info
            if not tag_policies_enabled:
                tag_policies_enabled = any(
                    p['Type'] == 'TAG_POLICY' and p['Status'] == 'ENABLED'
                    for p in policy_types
                )

            # Try to list tag policies to confirm access and check if enabled
            policies_count = 0
            can_list_policies = False
            try:
                policies_response = self.org_client.list_policies(Filter='TAG_POLICY')
                policies_count = len(policies_response.get('Policies', []))
                can_list_policies = True
                # Don't override the status just because we can list policies
                # Only set to False if we get PolicyTypeNotEnabledException
            except ClientError as e:
                error_code = e.response.get('Error', {}).get('Code', '')
                # PolicyTypeNotEnabledException means tag policies are disabled
                if error_code == 'PolicyTypeNotEnabledException':
                    tag_policies_enabled = False
                    can_list_policies = False
                # Other errors mean we can't list but they might still be enabled
                pass

            # Final verification: Try to describe effective policy
            # This is the most reliable way to check if tag policies are truly enabled
            try:
                # Try to get effective policy for the current account
                result = self.org_client.describe_effective_policy(
                    TargetId=current_account,
                    PolicyType='TAG_POLICY'
                )
                # If this succeeds AND returns content, tag policies are likely enabled
                if result.get('EffectivePolicy', {}).get('PolicyContent'):
                    # Only set to enabled if we actually got policy content
                    if not tag_policies_enabled:
                        tag_policies_enabled = True
            except ClientError as e:
                error_code = e.response.get('Error', {}).get('Code', '')
                error_msg = str(e)
                # These errors indicate tag policies are disabled
                if error_code in ['PolicyTypeNotEnabledException', 'EffectivePolicyNotFoundException']:
                    tag_policies_enabled = False
                elif 'policy type is not enabled' in error_msg.lower():
                    tag_policies_enabled = False
                # Any other error, we keep the current status
                pass

            return {
                'has_access': True,
                'org_id': organization['Id'],
                'master_account': organization['MasterAccountId'],
                'current_account': current_account,
                'tag_policies_enabled': tag_policies_enabled,
                'policies_count': policies_count,
                'feature_set': organization.get('FeatureSet', 'UNKNOWN'),
                'available_policy_types': [p['Type'] for p in policy_types if p['Status'] == 'ENABLED']
            }

        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            error_message = e.response.get('Error', {}).get('Message', str(e))

            # Try to get current account at least
            current_account = None
            try:
                identity = self.sts_client.get_caller_identity()
                current_account = identity['Account']
            except:
                pass

            return {
                'has_access': False,
                'current_account': current_account,
                'error': f"{error_code}: {error_message}",
                'error_code': error_code,
                'required_permissions': [
                    'organizations:DescribeOrganization',
                    'organizations:ListRoots',
                    'organizations:ListPolicies',
                    'organizations:DescribePolicy'
                ]
            }
        except Exception as e:
            return {
                'has_access': False,
                'error': f"Unexpected error: {str(e)}",
                'error_code': 'UNKNOWN_ERROR'
            }

    def list_policies(self, detailed: bool = False) -> List[Dict[str, Any]]:
        """List all tag policies in the organization.

        Args:
            detailed: If True, fetch full policy details for each policy

        Returns:
            List of policy dictionaries with policy information
        """
        try:
            policies = []
            paginator = self.org_client.get_paginator('list_policies')

            # Get all tag policies
            for page in paginator.paginate(Filter='TAG_POLICY'):
                for policy_summary in page.get('Policies', []):
                    policy_info = {
                        'id': policy_summary['Id'],
                        'name': policy_summary['Name'],
                        'description': policy_summary.get('Description', ''),
                        'aws_managed': policy_summary.get('AwsManaged', False),
                        'type': policy_summary.get('Type', 'TAG_POLICY')
                    }

                    # Get detailed information if requested
                    if detailed:
                        try:
                            policy_details = self.get_policy_details(policy_summary['Id'])
                            policy_info.update(policy_details)
                        except Exception as e:
                            policy_info['error'] = f"Failed to get details: {str(e)}"

                    policies.append(policy_info)

            return policies

        except ClientError as e:
            console.print(f"[red]Error listing policies: {e}[/red]")
            return []
        except Exception as e:
            console.print(f"[red]Unexpected error: {e}[/red]")
            return []

    def get_policy_details(self, policy_id: str) -> Dict[str, Any]:
        """Get detailed information about a specific policy.

        Args:
            policy_id: The ID of the policy to retrieve

        Returns:
            Dictionary with detailed policy information
        """
        try:
            # Get policy content
            policy_response = self.org_client.describe_policy(PolicyId=policy_id)
            policy = policy_response['Policy']

            # Parse policy content
            content = {}
            if policy.get('Content'):
                try:
                    content = json.loads(policy['Content'])
                except json.JSONDecodeError:
                    content = {'raw': policy['Content']}

            # Get policy targets
            targets = []
            try:
                targets_response = self.org_client.list_targets_for_policy(PolicyId=policy_id)
                targets = targets_response.get('Targets', [])
            except ClientError:
                # May not have permission to list targets
                pass

            return {
                'id': policy['PolicySummary']['Id'],
                'name': policy['PolicySummary']['Name'],
                'description': policy['PolicySummary'].get('Description', ''),
                'aws_managed': policy['PolicySummary'].get('AwsManaged', False),
                'type': policy['PolicySummary'].get('Type', 'TAG_POLICY'),
                'content': content,
                'targets': targets,
                'target_count': len(targets),
                'arn': policy['PolicySummary'].get('Arn', ''),
                'create_date': policy['PolicySummary'].get('CreateDate'),
                'update_date': policy['PolicySummary'].get('UpdateDate')
            }

        except ClientError as e:
            error_msg = e.response.get('Error', {}).get('Message', str(e))
            return {
                'id': policy_id,
                'error': f"Failed to get policy details: {error_msg}"
            }
        except Exception as e:
            return {
                'id': policy_id,
                'error': f"Unexpected error: {str(e)}"
            }

    def get_effective_policy(self, target_id: Optional[str] = None) -> Dict[str, Any]:
        """Get the effective tag policy for a target (account/OU/root).

        Args:
            target_id: The target ID. If None, uses current account

        Returns:
            Dictionary with effective policy information
        """
        try:
            # Use current account if no target specified
            if target_id is None:
                identity = self.sts_client.get_caller_identity()
                target_id = identity['Account']

            # Get effective policy
            response = self.org_client.describe_effective_policy(
                TargetId=target_id,
                PolicyType='TAG_POLICY'
            )

            effective_policy = response.get('EffectivePolicy', {})

            # Parse policy content
            content = {}
            if effective_policy.get('PolicyContent'):
                try:
                    content = json.loads(effective_policy['PolicyContent'])
                except json.JSONDecodeError:
                    content = {'raw': effective_policy['PolicyContent']}

            return {
                'target_id': target_id,
                'policy_type': 'TAG_POLICY',
                'content': content,
                'last_updated': effective_policy.get('LastUpdatedTimestamp'),
                'target_id': effective_policy.get('TargetId', target_id),
                'policy_id': effective_policy.get('PolicyId')
            }

        except ClientError as e:
            error_msg = e.response.get('Error', {}).get('Message', str(e))
            return {
                'target_id': target_id,
                'error': f"Failed to get effective policy: {error_msg}"
            }
        except Exception as e:
            return {
                'target_id': target_id,
                'error': f"Unexpected error: {str(e)}"
            }

    def format_policy_content(self, content: Dict) -> str:
        """Format policy content for display.

        Args:
            content: Policy content dictionary

        Returns:
            Formatted string representation of policy
        """
        if not content:
            return "No policy content"

        # Handle raw content
        if 'raw' in content:
            return content['raw']

        # Format tags section
        formatted = []
        if 'tags' in content:
            for tag_key, tag_rules in content['tags'].items():
                formatted.append(f"Tag: {tag_key}")

                # Show tag key requirements
                if 'tag_key' in tag_rules:
                    tag_key_data = tag_rules['tag_key']
                    # Handle both string and dict types
                    if isinstance(tag_key_data, dict):
                        key_req = tag_key_data.get('@@assign', tag_key_data)
                    else:
                        key_req = tag_key_data
                    formatted.append(f"  Key: {key_req}")

                # Show tag value requirements
                if 'tag_value' in tag_rules:
                    tag_value_data = tag_rules['tag_value']
                    # Handle both string and dict types
                    if isinstance(tag_value_data, dict):
                        value_req = tag_value_data.get('@@assign', tag_value_data)
                    else:
                        value_req = tag_value_data

                    if isinstance(value_req, list):
                        formatted.append(f"  Allowed values: {', '.join(value_req)}")
                    else:
                        formatted.append(f"  Value pattern: {value_req}")

                # Show enforced resource types
                if 'enforced_for' in tag_rules:
                    enforced_data = tag_rules['enforced_for']
                    # Handle both string and dict types
                    if isinstance(enforced_data, dict):
                        enforced = enforced_data.get('@@assign', enforced_data)
                    else:
                        enforced = enforced_data

                    if isinstance(enforced, list):
                        formatted.append(f"  Enforced for: {', '.join(enforced)}")

                formatted.append("")

        return "\n".join(formatted) if formatted else json.dumps(content, indent=2)

    def enable_tag_policies(self) -> Dict[str, Any]:
        """Enable tag policies for the organization.

        Returns:
            Dictionary with the operation result:
            - success: Boolean indicating if the operation was successful
            - message: Success or error message
            - policy_type: The enabled policy type details
        """
        try:
            # First check if tag policies are already enabled
            check_result = self.check_access()
            if check_result.get('tag_policies_enabled'):
                return {
                    'success': False,
                    'already_enabled': True,
                    'message': "Tag policies are already enabled for this organization"
                }

            # Get the root ID
            roots_response = self.org_client.list_roots()
            if not roots_response.get('Roots'):
                return {
                    'success': False,
                    'message': "No organization root found"
                }

            root_id = roots_response['Roots'][0]['Id']

            # Enable tag policies for the organization
            response = self.org_client.enable_policy_type(
                RootId=root_id,
                PolicyType='TAG_POLICY'
            )

            # Get the enabled policy type details
            policy_type = response.get('Root', {}).get('PolicyTypes', [])
            tag_policy = next((p for p in policy_type if p['Type'] == 'TAG_POLICY'), None)

            if tag_policy and tag_policy.get('Status') == 'ENABLED':
                # Also enable the tag policies service access for compliance checking
                service_access_enabled = False
                try:
                    self.org_client.enable_aws_service_access(
                        ServicePrincipal='tagpolicies.tag.amazonaws.com'
                    )
                    service_access_enabled = True
                except ClientError as service_error:
                    # If already enabled, that's fine
                    if service_error.response.get('Error', {}).get('Code') == 'ConcurrentModificationException':
                        service_access_enabled = True
                    # Otherwise, we'll note it but still consider the policy type enablement successful

                return {
                    'success': True,
                    'message': "Tag policies successfully enabled for the organization",
                    'root_id': root_id,
                    'policy_type': tag_policy,
                    'service_access_enabled': service_access_enabled
                }
            else:
                return {
                    'success': False,
                    'message': "Tag policies were not enabled. Please check the response.",
                    'response': response
                }

        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            error_message = e.response.get('Error', {}).get('Message', str(e))

            # Handle specific error cases
            if error_code == 'PolicyTypeAlreadyEnabledException':
                return {
                    'success': False,
                    'already_enabled': True,
                    'message': "Tag policies are already enabled for this organization"
                }
            elif error_code == 'AccessDeniedException':
                return {
                    'success': False,
                    'message': f"Access denied. You must be signed in as the master account to enable policy types. Error: {error_message}"
                }
            elif error_code == 'InvalidInputException':
                return {
                    'success': False,
                    'message': f"Invalid input provided. {error_message}"
                }
            elif error_code == 'RootNotFoundException':
                return {
                    'success': False,
                    'message': "Organization root not found. Ensure you're in a valid organization."
                }
            else:
                return {
                    'success': False,
                    'message': f"Failed to enable tag policies: {error_code}: {error_message}"
                }

        except Exception as e:
            error_msg = str(e)
            # Provide more helpful error messages for common issues
            if "can be called only from the organization's management account" in error_msg:
                return {
                    'success': False,
                    'message': "This operation can only be performed from the organization's management account or by a delegated administrator. Please switch to the management account and try again."
                }
            elif "PolicyTypeNotAvailableForOrganization" in error_msg:
                return {
                    'success': False,
                    'message': "Tag policies are not available for your organization. This may be due to organization configuration or feature set limitations."
                }
            return {
                'success': False,
                'message': f"Unexpected error enabling tag policies: {error_msg}"
            }

    def disable_tag_policies(self) -> Dict[str, Any]:
        """Disable tag policies for the organization.

        Returns:
            Dictionary with the operation result:
            - success: Boolean indicating if the operation was successful
            - message: Success or error message
        """
        try:
            # First check if tag policies are already disabled
            check_result = self.check_access()
            if not check_result.get('tag_policies_enabled'):
                return {
                    'success': False,
                    'already_disabled': True,
                    'message': "Tag policies are already disabled for this organization"
                }

            # Get the root ID
            roots_response = self.org_client.list_roots()
            if not roots_response.get('Roots'):
                return {
                    'success': False,
                    'message': "No organization root found"
                }

            root_id = roots_response['Roots'][0]['Id']

            # Disable tag policies for the organization
            response = self.org_client.disable_policy_type(
                RootId=root_id,
                PolicyType='TAG_POLICY'
            )

            # Check the response
            root_info = response.get('Root', {})
            policy_types = root_info.get('PolicyTypes', [])

            # Check if tag policies are disabled
            tag_policy_disabled = not any(
                p['Type'] == 'TAG_POLICY' and p['Status'] == 'ENABLED'
                for p in policy_types
            )

            if tag_policy_disabled:
                return {
                    'success': True,
                    'message': "Tag policies successfully disabled for the organization",
                    'root_id': root_id
                }
            else:
                return {
                    'success': False,
                    'message': "Tag policies were not disabled. Please check the response.",
                    'response': response
                }

        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            error_message = e.response.get('Error', {}).get('Message', str(e))

            # Handle specific error cases
            if error_code == 'PolicyTypeNotEnabledException':
                return {
                    'success': False,
                    'already_disabled': True,
                    'message': "Tag policies are already disabled for this organization"
                }
            elif error_code == 'AccessDeniedException':
                return {
                    'success': False,
                    'message': f"Access denied. You must be signed in as the master account to disable policy types. Error: {error_message}"
                }
            elif error_code == 'InvalidInputException':
                return {
                    'success': False,
                    'message': f"Invalid input provided. {error_message}"
                }
            elif error_code == 'PolicyInUseException':
                return {
                    'success': False,
                    'message': "Cannot disable tag policies: There are still policies attached to targets. Remove all tag policies first."
                }
            elif error_code == 'RootNotFoundException':
                return {
                    'success': False,
                    'message': "Organization root not found. Ensure you're in a valid organization."
                }
            else:
                return {
                    'success': False,
                    'message': f"Failed to disable tag policies: {error_code}: {error_message}"
                }

        except Exception as e:
            error_msg = str(e)
            # Provide more helpful error messages for common issues
            if "can be called only from the organization's management account" in error_msg:
                return {
                    'success': False,
                    'message': "This operation can only be performed from the organization's management account or by a delegated administrator. Please switch to the management account and try again."
                }
            elif "PolicyTypeNotAvailableForOrganization" in error_msg:
                return {
                    'success': False,
                    'message': "Tag policies are not available for your organization. This may be due to organization configuration or feature set limitations."
                }
            return {
                'success': False,
                'message': f"Unexpected error disabling tag policies: {error_msg}"
            }

    def display_policies_table(self, policies: List[Dict]) -> None:
        """Display policies in a formatted table.

        Args:
            policies: List of policy dictionaries
        """
        if not policies:
            console.print("[yellow]No tag policies found[/yellow]")
            return

        table = Table(title="AWS Organizations Tag Policies", show_header=True, header_style="bold magenta")
        table.add_column("ID", style="cyan", width=20)
        table.add_column("Name", style="white", width=25)
        table.add_column("Type", style="green", width=12)
        table.add_column("AWS Managed", style="yellow", width=12)
        table.add_column("Targets", style="blue", width=10, justify="center")
        table.add_column("Description", style="dim", width=30)

        for policy in policies:
            table.add_row(
                policy.get('id', 'N/A'),
                policy.get('name', 'N/A'),
                policy.get('type', 'TAG_POLICY'),
                "Yes" if policy.get('aws_managed', False) else "No",
                str(policy.get('target_count', 0)) if 'target_count' in policy else "N/A",
                policy.get('description', '')[:30] + '...' if len(policy.get('description', '')) > 30 else policy.get('description', '')
            )

        console.print(table)
        console.print(f"\n[dim]Total policies: {len(policies)}[/dim]")

    # === COMPLIANCE CHECKING METHODS ===

    def get_compliance_summary(
        self,
        target_ids: Optional[List[str]] = None,
        region_filters: Optional[List[str]] = None,
        resource_type_filters: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Get organization-wide tag policy compliance summary.

        Note: This API must be called from the management account in us-east-1.
        Compliance evaluation runs every 48 hours, so data may not be real-time.

        Args:
            target_ids: List of account IDs or OU IDs to filter by
            region_filters: List of AWS regions to filter by
            resource_type_filters: List of resource types to filter by

        Returns:
            Dictionary with compliance summary data
        """
        try:
            # Ensure we're using us-east-1 for this API
            tagging_client = self.session.client('resourcegroupstaggingapi', region_name='us-east-1')

            params = {
                'MaxResults': 1000
            }

            if target_ids:
                params['TargetIdFilters'] = target_ids
            if region_filters:
                params['RegionFilters'] = region_filters
            if resource_type_filters:
                params['ResourceTypeFilters'] = resource_type_filters

            # Handle pagination
            all_summaries = []
            pagination_token = None

            while True:
                if pagination_token:
                    params['PaginationToken'] = pagination_token

                response = tagging_client.get_compliance_summary(**params)
                all_summaries.extend(response.get('SummaryList', []))

                pagination_token = response.get('PaginationToken')
                if not pagination_token:
                    break

            # Calculate totals
            total_noncompliant = sum(s.get('NonCompliantResources', 0) for s in all_summaries)
            total_resources = 0

            for summary in all_summaries:
                region = summary.get('Region', 'Unknown')
                resource_type = summary.get('ResourceType', 'Unknown')
                noncompliant = summary.get('NonCompliantResources', 0)
                total_resources += noncompliant

            return {
                'success': True,
                'summaries': all_summaries,
                'total_noncompliant': total_noncompliant,
                'total_resources': total_resources,
                'evaluation_note': 'Compliance data is evaluated every 48 hours and may not be real-time'
            }

        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            error_msg = e.response.get('Error', {}).get('Message', str(e))

            if error_code == 'InvalidParameterException':
                return {
                    'success': False,
                    'error': f'Invalid parameters: {error_msg}',
                    'suggestion': 'Ensure you are calling from the management account in us-east-1 region',
                    'error_code': error_code
                }
            elif error_code == 'ConstraintViolationException' and 'tagpolicies.tag.amazonaws.com' in error_msg:
                return {
                    'success': False,
                    'error': 'Tag policies service access is not enabled',
                    'suggestion': 'Enable tag policies service access using AWS CLI:\n  aws organizations enable-aws-service-access --service-principal tagpolicies.tag.amazonaws.com',
                    'error_code': error_code,
                    'raw_error': error_msg
                }
            elif 'ConstraintViolation' in error_msg or 'not enabled' in error_msg.lower():
                return {
                    'success': False,
                    'error': 'Tag policies are not enabled for this organization',
                    'suggestion': 'Run "policy enable" to enable tag policies first',
                    'error_code': error_code,
                    'raw_error': error_msg
                }
            else:
                return {
                    'success': False,
                    'error': f'Failed to get compliance summary: {error_msg}',
                    'error_code': error_code,
                    'raw_error': error_msg
                }

        except Exception as e:
            return {
                'success': False,
                'error': f'Unexpected error: {str(e)}'
            }

    def get_noncompliant_resources(
        self,
        resource_type_filters: Optional[List[str]] = None,
        region_filters: Optional[List[str]] = None,
        tag_key_filters: Optional[List[str]] = None,
        resource_arns: Optional[List[str]] = None,
        max_results: int = 100
    ) -> Dict[str, Any]:
        """Get detailed list of resources that are noncompliant with tag policies.

        Args:
            resource_type_filters: Filter by resource types (e.g., ['ec2:instance'])
            region_filters: Filter by regions
            tag_key_filters: Filter by tag keys
            resource_arns: Specific resource ARNs to check
            max_results: Maximum number of results to return

        Returns:
            Dictionary with noncompliant resources
        """
        try:
            params = {
                'IncludeComplianceDetails': True,
                'ExcludeCompliantResources': True,
                'ResourcesPerPage': min(max_results, 500)  # AWS max is 500
            }

            if resource_type_filters:
                params['ResourceTypeFilters'] = resource_type_filters
            if resource_arns:
                params['ResourceARNList'] = resource_arns

            # Handle pagination
            all_resources = []
            pagination_token = None
            total_fetched = 0

            while total_fetched < max_results:
                if pagination_token:
                    params['PaginationToken'] = pagination_token

                response = self.tagging_client.get_resources(**params)
                resources = response.get('ResourceTagMappingList', [])
                all_resources.extend(resources)
                total_fetched += len(resources)

                pagination_token = response.get('PaginationToken')
                if not pagination_token or total_fetched >= max_results:
                    break

            # Process compliance details
            noncompliant_resources = []
            for resource in all_resources[:max_results]:
                compliance = resource.get('ComplianceDetails', {})

                resource_info = {
                    'arn': resource.get('ResourceARN', 'N/A'),
                    'tags': resource.get('Tags', []),
                    'compliance_status': compliance.get('ComplianceStatus', False),
                    'noncompliant_keys': compliance.get('NoncompliantKeys', []),
                    'keys_with_noncompliant_values': compliance.get('KeysWithNoncompliantValues', [])
                }

                # Parse ARN to get service and resource type
                arn = resource_info['arn']
                if arn.startswith('arn:aws:'):
                    parts = arn.split(':')
                    resource_info['service'] = parts[2] if len(parts) > 2 else 'unknown'
                    resource_info['region'] = parts[3] if len(parts) > 3 else 'unknown'
                    resource_info['resource_id'] = parts[-1] if len(parts) > 0 else 'unknown'
                else:
                    resource_info['service'] = 'unknown'
                    resource_info['region'] = 'unknown'
                    resource_info['resource_id'] = 'unknown'

                noncompliant_resources.append(resource_info)

            return {
                'success': True,
                'resources': noncompliant_resources,
                'count': len(noncompliant_resources),
                'has_more': pagination_token is not None
            }

        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            error_msg = e.response.get('Error', {}).get('Message', str(e))

            return {
                'success': False,
                'error': f'Failed to get noncompliant resources: {error_msg}',
                'error_code': error_code
            }

        except Exception as e:
            return {
                'success': False,
                'error': f'Unexpected error: {str(e)}'
            }

    def check_resource_compliance(self, resource_arn: str) -> Dict[str, Any]:
        """Check compliance status of a specific resource.

        Args:
            resource_arn: ARN of the resource to check

        Returns:
            Dictionary with resource compliance details
        """
        try:
            response = self.tagging_client.get_resources(
                ResourceARNList=[resource_arn],
                IncludeComplianceDetails=True
            )

            resources = response.get('ResourceTagMappingList', [])

            if not resources:
                return {
                    'success': False,
                    'error': f'Resource not found: {resource_arn}',
                    'suggestion': 'Verify the ARN is correct and the resource exists'
                }

            resource = resources[0]
            compliance = resource.get('ComplianceDetails', {})

            return {
                'success': True,
                'arn': resource.get('ResourceARN'),
                'tags': resource.get('Tags', []),
                'compliance_status': compliance.get('ComplianceStatus', False),
                'noncompliant_keys': compliance.get('NoncompliantKeys', []),
                'keys_with_noncompliant_values': compliance.get('KeysWithNoncompliantValues', []),
                'is_compliant': compliance.get('ComplianceStatus', False)
            }

        except ClientError as e:
            error_msg = e.response.get('Error', {}).get('Message', str(e))
            return {
                'success': False,
                'error': f'Failed to check resource compliance: {error_msg}'
            }

        except Exception as e:
            return {
                'success': False,
                'error': f'Unexpected error: {str(e)}'
            }

    def display_compliance_summary(self, summary_data: Dict[str, Any], verbose: bool = False) -> None:
        """Display compliance summary in a formatted table.

        Args:
            summary_data: Compliance summary data from get_compliance_summary()
            verbose: Show additional debug information
        """
        if not summary_data.get('success'):
            console.print(f"[red]Error: {summary_data.get('error')}[/red]")
            if summary_data.get('suggestion'):
                console.print(f"[yellow]{summary_data['suggestion']}[/yellow]")
            if verbose:
                if summary_data.get('error_code'):
                    console.print(f"[dim]Error Code: {summary_data['error_code']}[/dim]")
                if summary_data.get('raw_error'):
                    console.print(f"[dim]Raw Error: {summary_data['raw_error']}[/dim]")
            return

        summaries = summary_data.get('summaries', [])

        if not summaries:
            console.print("[green]No noncompliant resources found! All resources are compliant.[/green]")
            return

        # Create summary table
        table = Table(title="Tag Policy Compliance Summary", show_header=True, header_style="bold cyan")
        table.add_column("Region", style="cyan", width=15)
        table.add_column("Resource Type", style="white", width=30)
        table.add_column("Noncompliant", style="red", width=15, justify="right")

        for summary in summaries:
            region = summary.get('Region', 'N/A')
            resource_type = summary.get('ResourceType', 'N/A')
            noncompliant = summary.get('NonCompliantResources', 0)

            if noncompliant > 0:
                table.add_row(region, resource_type, str(noncompliant))

        console.print(table)
        console.print(f"\n[bold]Total Noncompliant Resources: {summary_data.get('total_noncompliant', 0)}[/bold]")
        console.print(f"[dim]{summary_data.get('evaluation_note', '')}[/dim]")

    def display_noncompliant_resources(self, resources_data: Dict[str, Any]) -> None:
        """Display noncompliant resources in a detailed format.

        Args:
            resources_data: Noncompliant resources data from get_noncompliant_resources()
        """
        if not resources_data.get('success'):
            console.print(f"[red]Error: {resources_data.get('error')}[/red]")
            return

        resources = resources_data.get('resources', [])

        if not resources:
            console.print("[green]No noncompliant resources found! All resources are compliant.[/green]")
            return

        console.print(f"\n[bold cyan]Found {resources_data.get('count', 0)} Noncompliant Resources[/bold cyan]\n")

        for idx, resource in enumerate(resources, 1):
            console.print(f"[bold yellow]Resource #{idx}[/bold yellow]")
            console.print(f"[cyan]ARN:[/cyan] {resource.get('arn', 'N/A')}")

            # Service and region info
            service = resource.get('service', 'unknown')
            region = resource.get('region', 'N/A')
            if region and region != 'N/A':
                console.print(f"[cyan]Service:[/cyan] {service} [dim]({region})[/dim]")
            else:
                console.print(f"[cyan]Service:[/cyan] {service}")

            # Resource ID
            resource_id = resource.get('resource_id', 'N/A')
            console.print(f"[cyan]Resource ID:[/cyan] {resource_id}")

            # Compliance status
            is_compliant = resource.get('compliance_status', False)
            status_color = "green" if is_compliant else "red"
            status_text = "COMPLIANT" if is_compliant else "NONCOMPLIANT"
            console.print(f"[cyan]Compliance:[/cyan] [{status_color}]{status_text}[/{status_color}]")

            # Missing tags
            missing_tags = resource.get('noncompliant_keys', [])
            if missing_tags:
                console.print(f"[red]Missing Required Tags:[/red]")
                for tag in missing_tags:
                    console.print(f"  - {tag}")

            # Invalid tag values
            invalid_tags = resource.get('keys_with_noncompliant_values', [])
            if invalid_tags:
                console.print(f"[magenta]Tags with Invalid Values:[/magenta]")
                for tag in invalid_tags:
                    console.print(f"  - {tag}")

            # Current tags
            current_tags = resource.get('tags', [])
            if current_tags:
                console.print(f"[dim]Current Tags:[/dim]")
                for tag in current_tags:
                    key = tag.get('Key', 'N/A')
                    value = tag.get('Value', 'N/A')
                    console.print(f"  {key} = {value}")
            else:
                console.print(f"[dim]Current Tags: None[/dim]")

            # Separator between resources
            if idx < len(resources):
                console.print()

        console.print(f"\n[bold]Total: {resources_data.get('count', 0)} noncompliant resources shown[/bold]")

        if resources_data.get('has_more'):
            console.print("[yellow]Note: More results available. Use --limit to increase the number of results.[/yellow]")

    # === POLICY CRUD OPERATIONS ===

    def create_policy(self, name: str, description: str, content: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new tag policy in AWS Organizations.

        Args:
            name: Policy name
            description: Policy description
            content: Policy content as dictionary

        Returns:
            Dictionary with creation result:
            - success: Boolean indicating if creation was successful
            - policy_id: Created policy ID (if successful)
            - policy: Full policy details (if successful)
            - error: Error message (if failed)
        """
        try:
            # Convert content dict to JSON string
            content_str = json.dumps(content)

            # Create the policy
            response = self.org_client.create_policy(
                Content=content_str,
                Description=description,
                Name=name,
                Type='TAG_POLICY'
            )

            policy = response.get('Policy', {})
            policy_summary = policy.get('PolicySummary', {})

            return {
                'success': True,
                'policy_id': policy_summary.get('Id'),
                'policy': policy,
                'message': f"Successfully created policy '{name}'"
            }

        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            error_msg = e.response.get('Error', {}).get('Message', str(e))

            if error_code == 'AccessDeniedException':
                return {
                    'success': False,
                    'error': 'Access denied',
                    'suggestion': 'Policy creation requires organizations:CreatePolicy permission and must be run from the management account'
                }
            elif error_code == 'DuplicatePolicyException':
                return {
                    'success': False,
                    'error': f"A policy with the name '{name}' already exists",
                    'suggestion': 'Choose a different policy name or update the existing policy'
                }
            elif error_code == 'MalformedPolicyDocumentException':
                return {
                    'success': False,
                    'error': 'Policy document is malformed',
                    'suggestion': 'Check the policy JSON syntax and ensure it meets AWS tag policy requirements',
                    'details': error_msg
                }
            else:
                return {
                    'success': False,
                    'error': f"{error_code}: {error_msg}"
                }

        except Exception as e:
            return {
                'success': False,
                'error': f"Unexpected error creating policy: {str(e)}"
            }

    def update_policy(self, policy_id: str, content: Optional[Dict[str, Any]] = None,
                     name: Optional[str] = None, description: Optional[str] = None) -> Dict[str, Any]:
        """Update an existing tag policy.

        Args:
            policy_id: Policy ID to update
            content: New policy content (optional)
            name: New policy name (optional)
            description: New policy description (optional)

        Returns:
            Dictionary with update result
        """
        try:
            update_params = {'PolicyId': policy_id}

            if content is not None:
                update_params['Content'] = json.dumps(content)

            if name is not None:
                update_params['Name'] = name

            if description is not None:
                update_params['Description'] = description

            # Update the policy
            response = self.org_client.update_policy(**update_params)

            policy = response.get('Policy', {})

            return {
                'success': True,
                'policy': policy,
                'message': 'Successfully updated policy'
            }

        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            error_msg = e.response.get('Error', {}).get('Message', str(e))

            if error_code == 'PolicyNotFoundException':
                return {
                    'success': False,
                    'error': f"Policy '{policy_id}' not found"
                }
            elif error_code == 'MalformedPolicyDocumentException':
                return {
                    'success': False,
                    'error': 'Policy document is malformed',
                    'details': error_msg
                }
            else:
                return {
                    'success': False,
                    'error': f"{error_code}: {error_msg}"
                }

        except Exception as e:
            return {
                'success': False,
                'error': f"Unexpected error updating policy: {str(e)}"
            }

    def delete_policy(self, policy_id: str) -> Dict[str, Any]:
        """Delete a tag policy.

        Note: Policy must be detached from all targets before deletion.

        Args:
            policy_id: Policy ID to delete

        Returns:
            Dictionary with deletion result
        """
        try:
            self.org_client.delete_policy(PolicyId=policy_id)

            return {
                'success': True,
                'message': f"Successfully deleted policy '{policy_id}'"
            }

        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            error_msg = e.response.get('Error', {}).get('Message', str(e))

            if error_code == 'PolicyInUseException':
                return {
                    'success': False,
                    'error': 'Policy is still attached to one or more targets',
                    'suggestion': 'Detach the policy from all targets before deleting'
                }
            elif error_code == 'PolicyNotFoundException':
                return {
                    'success': False,
                    'error': f"Policy '{policy_id}' not found"
                }
            else:
                return {
                    'success': False,
                    'error': f"{error_code}: {error_msg}"
                }

        except Exception as e:
            return {
                'success': False,
                'error': f"Unexpected error deleting policy: {str(e)}"
            }

    def attach_policy(self, policy_id: str, target_id: str) -> Dict[str, Any]:
        """Attach a policy to a target (root, OU, or account).

        Args:
            policy_id: Policy ID to attach
            target_id: Target ID (r-xxxx for root, ou-xxxx for OU, account ID for account)

        Returns:
            Dictionary with attachment result
        """
        try:
            self.org_client.attach_policy(
                PolicyId=policy_id,
                TargetId=target_id
            )

            return {
                'success': True,
                'message': f"Successfully attached policy to target '{target_id}'"
            }

        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            error_msg = e.response.get('Error', {}).get('Message', str(e))

            if error_code == 'DuplicatePolicyAttachmentException':
                return {
                    'success': False,
                    'error': 'Policy is already attached to this target'
                }
            elif error_code == 'PolicyNotFoundException':
                return {
                    'success': False,
                    'error': f"Policy '{policy_id}' not found"
                }
            elif error_code == 'TargetNotFoundException':
                return {
                    'success': False,
                    'error': f"Target '{target_id}' not found"
                }
            else:
                return {
                    'success': False,
                    'error': f"{error_code}: {error_msg}"
                }

        except Exception as e:
            return {
                'success': False,
                'error': f"Unexpected error attaching policy: {str(e)}"
            }

    def detach_policy(self, policy_id: str, target_id: str) -> Dict[str, Any]:
        """Detach a policy from a target.

        Args:
            policy_id: Policy ID to detach
            target_id: Target ID to detach from

        Returns:
            Dictionary with detachment result
        """
        try:
            self.org_client.detach_policy(
                PolicyId=policy_id,
                TargetId=target_id
            )

            return {
                'success': True,
                'message': f"Successfully detached policy from target '{target_id}'"
            }

        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            error_msg = e.response.get('Error', {}).get('Message', str(e))

            if error_code == 'PolicyNotAttachedException':
                return {
                    'success': False,
                    'error': 'Policy is not attached to this target'
                }
            elif error_code == 'PolicyNotFoundException':
                return {
                    'success': False,
                    'error': f"Policy '{policy_id}' not found"
                }
            else:
                return {
                    'success': False,
                    'error': f"{error_code}: {error_msg}"
                }

        except Exception as e:
            return {
                'success': False,
                'error': f"Unexpected error detaching policy: {str(e)}"
            }

    # === HELPER METHODS FOR LISTING RESOURCES ===

    def list_targets_for_policy(self, policy_id: str) -> Dict[str, Any]:
        """List all targets where a policy is attached.

        Args:
            policy_id: Policy ID

        Returns:
            Dictionary with targets list
        """
        try:
            targets = []
            paginator = self.org_client.get_paginator('list_targets_for_policy')

            for page in paginator.paginate(PolicyId=policy_id):
                for target in page.get('Targets', []):
                    targets.append({
                        'target_id': target.get('TargetId'),
                        'arn': target.get('Arn'),
                        'name': target.get('Name'),
                        'type': target.get('Type')  # ROOT, ORGANIZATIONAL_UNIT, or ACCOUNT
                    })

            return {
                'success': True,
                'targets': targets,
                'count': len(targets)
            }

        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            error_msg = e.response.get('Error', {}).get('Message', str(e))

            return {
                'success': False,
                'error': f"{error_code}: {error_msg}",
                'targets': []
            }

        except Exception as e:
            return {
                'success': False,
                'error': f"Unexpected error listing targets: {str(e)}",
                'targets': []
            }

    def list_organizational_units(self, parent_id: Optional[str] = None) -> Dict[str, Any]:
        """List organizational units.

        Args:
            parent_id: Parent ID (root or OU). If None, lists OUs under root.

        Returns:
            Dictionary with OUs list
        """
        try:
            # If no parent_id provided, get the root
            if parent_id is None:
                roots_response = self.org_client.list_roots()
                if roots_response.get('Roots'):
                    parent_id = roots_response['Roots'][0]['Id']
                else:
                    return {
                        'success': False,
                        'error': 'No root found in organization',
                        'ous': []
                    }

            ous = []
            paginator = self.org_client.get_paginator('list_organizational_units_for_parent')

            for page in paginator.paginate(ParentId=parent_id):
                for ou in page.get('OrganizationalUnits', []):
                    ous.append({
                        'id': ou.get('Id'),
                        'arn': ou.get('Arn'),
                        'name': ou.get('Name')
                    })

            return {
                'success': True,
                'ous': ous,
                'count': len(ous),
                'parent_id': parent_id
            }

        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            error_msg = e.response.get('Error', {}).get('Message', str(e))

            return {
                'success': False,
                'error': f"{error_code}: {error_msg}",
                'ous': []
            }

        except Exception as e:
            return {
                'success': False,
                'error': f"Unexpected error listing OUs: {str(e)}",
                'ous': []
            }

    def list_accounts_for_parent(self, parent_id: Optional[str] = None) -> Dict[str, Any]:
        """List accounts under a parent (root or OU).

        Args:
            parent_id: Parent ID. If None, lists all accounts in organization.

        Returns:
            Dictionary with accounts list
        """
        try:
            accounts = []

            if parent_id is None:
                # List all accounts in organization
                paginator = self.org_client.get_paginator('list_accounts')

                for page in paginator.paginate():
                    for account in page.get('Accounts', []):
                        accounts.append({
                            'id': account.get('Id'),
                            'arn': account.get('Arn'),
                            'name': account.get('Name'),
                            'email': account.get('Email'),
                            'status': account.get('Status')
                        })
            else:
                # List accounts under specific parent
                paginator = self.org_client.get_paginator('list_accounts_for_parent')

                for page in paginator.paginate(ParentId=parent_id):
                    for account in page.get('Accounts', []):
                        accounts.append({
                            'id': account.get('Id'),
                            'arn': account.get('Arn'),
                            'name': account.get('Name'),
                            'email': account.get('Email'),
                            'status': account.get('Status')
                        })

            return {
                'success': True,
                'accounts': accounts,
                'count': len(accounts),
                'parent_id': parent_id
            }

        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            error_msg = e.response.get('Error', {}).get('Message', str(e))

            return {
                'success': False,
                'error': f"{error_code}: {error_msg}",
                'accounts': []
            }

        except Exception as e:
            return {
                'success': False,
                'error': f"Unexpected error listing accounts: {str(e)}",
                'accounts': []
            }

    def get_root_id(self) -> Optional[str]:
        """Get the organization root ID.

        Returns:
            Root ID or None if not found
        """
        try:
            roots_response = self.org_client.list_roots()
            if roots_response.get('Roots'):
                return roots_response['Roots'][0]['Id']
            return None
        except Exception:
            return None