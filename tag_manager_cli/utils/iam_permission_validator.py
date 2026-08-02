"""
IAM Permission Validator

Validates current AWS user/role permissions against required IAM policy.
Uses AWS IAM Policy Simulator to check permissions without making actual API calls.
Maps missing permissions to affected CLI commands for actionable feedback.
"""

import json
import os
import sys
from typing import Dict, List, Set, Tuple, Optional
from dataclasses import dataclass, field
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

from tag_manager_cli.utils.display_utils import print_safe

# Import the appropriate resource loader
if sys.version_info >= (3, 9):
    from importlib import resources
else:
    import importlib_resources as resources

# Enable debug logging if TAG_MANAGER_DEBUG is set
DEBUG = os.getenv("TAG_MANAGER_DEBUG", "0") == "1"

def debug_print(message: str):
    """Print debug message if debug mode is enabled"""
    if DEBUG:
        print_safe(f"[dim][DEBUG IAM] {message}[/dim]")


@dataclass
class PermissionGap:
    """Represents a missing permission and its impact"""
    action: str
    resource: str = "*"
    affected_features: List[str] = field(default_factory=list)
    severity: str = "WARNING"  # CRITICAL, WARNING, INFO
    reason: str = ""


@dataclass
class ValidationReport:
    """Complete validation report for IAM permissions"""
    all_passed: bool = False
    total_required: int = 0
    total_granted: int = 0
    granted_actions: List[str] = field(default_factory=list)
    missing_actions: List[PermissionGap] = field(default_factory=list)
    affected_commands: Dict[str, List[str]] = field(default_factory=dict)
    error_message: Optional[str] = None
    policy_doc: Optional[Dict] = None


class IAMPermissionValidator:
    """Validates IAM permissions for AWS Tag Manager CLI"""

    # Map CLI commands/features to required IAM actions
    FEATURE_PERMISSIONS = {
        'discover resources': [
            'ec2:DescribeInstances',
            'ec2:DescribeVolumes',
            'ec2:DescribeVpcs',
            'ec2:DescribeSubnets',
            's3:ListAllMyBuckets',
            's3:GetBucketLocation',
            'lambda:ListFunctions',
            'rds:DescribeDBInstances'
        ],
        'lifecycle scan': [
            'tag:GetResources',
            'ec2:DescribeInstances',
            'ec2:DescribeVolumes',
            's3:ListAllMyBuckets',
            's3:GetBucketTagging',
            'lambda:ListFunctions',
            'lambda:ListTags'
        ],
        'lifecycle set-ttl': [
            'tag:TagResources',
            's3:PutBucketTagging',
            's3:PutObjectTagging',
            'lambda:TagResource'
        ],
        'resource tag removal': [
            'lambda:UntagResource'
        ],
        'cost report': [
            'ce:GetCostAndUsage',
            'ce:GetCostForecast',
            'ce:GetTags',
            'athena:StartQueryExecution',
            'athena:GetQueryExecution',
            'athena:GetQueryResults'
        ],
        'cost gaps': [
            'ce:GetCostAndUsage',
            'athena:StartQueryExecution',
            'athena:GetQueryExecution',
            'athena:GetQueryResults'
        ],
        'cost anomalies': [
            'ce:GetCostAndUsage'
        ],
        'policy view': [
            'organizations:DescribeOrganization',
            'organizations:ListRoots',
            'organizations:ListPolicies',
            'organizations:DescribePolicy',
            'organizations:ListTargetsForPolicy',
            'organizations:DescribeEffectivePolicy'
        ],
        'policy create': [
            'organizations:CreatePolicy',
            'organizations:AttachPolicy'
        ],
        'policy update': [
            'organizations:UpdatePolicy'
        ],
        'policy delete': [
            'organizations:DeletePolicy',
            'organizations:DetachPolicy'
        ],
        'policy enable': [
            'organizations:EnablePolicyType',
            'organizations:EnableAWSServiceAccess'
        ],
        'policy disable': [
            'organizations:DisablePolicyType'
        ],
        'policy compliance': [
            'tag:GetComplianceSummary',
            'organizations:DescribeEffectivePolicy'
        ],
        'organizations list': [
            'organizations:ListAccounts',
            'organizations:ListAccountsForParent',
            'organizations:ListOrganizationalUnitsForParent'
        ],
        'ai assistant': [
            'bedrock:ListFoundationModels',
            'bedrock:ListFoundationModelAgreementOffers',
            'bedrock:InvokeModel',
            'bedrock:InvokeModelWithResponseStream',
            'bedrock:Converse',
            'bedrock:ConverseStream'
        ],
        'iam audit': [
            'iam:ListUsers',
            'iam:ListAccessKeys'
        ],
        'authentication': [
            'sts:GetCallerIdentity'
        ],
        'setup validate': [
            'iam:SimulatePrincipalPolicy'
        ],
        'setup assume-role deploy': [
            'sts:GetCallerIdentity',
            'cloudformation:CreateStack',
            'cloudformation:DescribeStacks',
            'cloudformation:DescribeStackEvents',
            'cloudformation:DeleteStack',
            'iam:CreateRole',
            'iam:PutRolePolicy',
            'iam:GetRole',
            'iam:CreatePolicy',
            'iam:AttachRolePolicy',
            'iam:DetachRolePolicy',
            'iam:DeletePolicy',
            'iam:TagRole',
        ]
    }

    # Permissions required for setting up assume-role (bootstrap).
    # These are checked separately from the full policy because a
    # minimal IAM user only needs these to deploy the role, after
    # which all other permissions come from the assumed role.
    # The CFN template creates an IAM role + 3 managed policies.
    ASSUME_ROLE_BOOTSTRAP_POLICY = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "TagManagerCLIBootstrapIdentity",
                "Effect": "Allow",
                "Action": [
                    "sts:GetCallerIdentity",
                    "iam:SimulatePrincipalPolicy"
                ],
                "Resource": "*"
            },
            {
                "Sid": "TagManagerCLIBootstrapCloudFormation",
                "Effect": "Allow",
                "Action": [
                    "cloudformation:CreateStack",
                    "cloudformation:DeleteStack",
                    "cloudformation:DescribeStacks",
                    "cloudformation:DescribeStackEvents"
                ],
                "Resource": "arn:aws:cloudformation:*:*:stack/BlueArchCLI-*/*"
            },
            {
                "Sid": "TagManagerCLIBootstrapIAMRole",
                "Effect": "Allow",
                "Action": [
                    "iam:CreateRole",
                    "iam:GetRole",
                    "iam:DeleteRole",
                    "iam:PutRolePolicy",
                    "iam:DeleteRolePolicy",
                    "iam:AttachRolePolicy",
                    "iam:DetachRolePolicy",
                    "iam:TagRole",
                    "iam:UntagRole"
                ],
                "Resource": "arn:aws:iam::*:role/TagManagerCLI*"
            },
            {
                "Sid": "TagManagerCLIBootstrapIAMPolicy",
                "Effect": "Allow",
                "Action": [
                    "iam:CreatePolicy",
                    "iam:DeletePolicy",
                    "iam:GetPolicy",
                    "iam:ListPolicyVersions",
                    "iam:DeletePolicyVersion"
                ],
                "Resource": "arn:aws:iam::*:policy/BlueArchCLI-*"
            }
        ]
    }

    def __init__(self, session=None):
        """Initialize the validator with an optional boto3 session"""
        self.session = session or boto3.Session()
        self.iam_client = self.session.client('iam')
        self.sts_client = self.session.client('sts')

    def _load_policy_from_package(self) -> str:
        """Load the IAM policy JSON from package resources (works in binary)"""
        try:
            # Try to load from package resources (works in binary and source)
            if sys.version_info >= (3, 9):
                # Python 3.9+ - use files() API
                integrations = resources.files("tag_manager_cli.integrations")
                policy_file = integrations / "iam-policy.json"
                return policy_file.read_text()
            else:
                # Python 3.7-3.8 - use read_text() API
                return resources.read_text("tag_manager_cli.integrations", "iam-policy.json")
        except (ImportError, FileNotFoundError, ModuleNotFoundError) as e:
            debug_print(f"Failed to load policy from package resources: {e}")
            return None

    def _load_policy_from_filesystem(self) -> str:
        """Fallback: Load the IAM policy JSON from filesystem (development mode)"""
        # Try multiple locations where the file might be during development
        possible_paths = []

        # Check if running in PyInstaller bundle
        if getattr(sys, '_MEIPASS', None):
            # PyInstaller extracts files to sys._MEIPASS
            meipass = Path(sys._MEIPASS)
            possible_paths.extend([
                meipass / "tag_manager_cli" / "integrations" / "iam-policy.json",
                meipass / "integrations" / "iam-policy.json",
            ])

        # Standard development/source locations
        possible_paths.extend([
            # In integrations folder (new location)
            Path(__file__).parent.parent / "integrations" / "iam-policy.json",
            # In root directory
            Path(__file__).parent.parent.parent / "iam-policy.json",
            # Relative to current working directory
            Path.cwd() / "tag_manager_cli" / "integrations" / "iam-policy.json",
            Path.cwd() / "iam-policy.json",
        ])

        for path in possible_paths:
            if path.exists():
                debug_print(f"Loading policy from filesystem: {path}")
                try:
                    with open(path, 'r') as f:
                        return f.read()
                except Exception as e:
                    debug_print(f"Failed to read policy from {path}: {e}")
                    continue

        return None

    def load_policy_json(self) -> Dict:
        """Load the IAM policy JSON file from package or filesystem"""
        # First try to load from package resources (works in binary)
        policy_content = self._load_policy_from_package()

        # If that fails, try filesystem (development mode)
        if policy_content is None:
            policy_content = self._load_policy_from_filesystem()

        # If still not found, raise error
        if policy_content is None:
            raise FileNotFoundError(
                "IAM policy file (iam-policy.json) not found. "
                "Ensure it's included in tag_manager_cli/integrations/"
            )

        try:
            return json.loads(policy_content)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in IAM policy file: {e}")

    def extract_actions_from_policy(self, policy_doc: Dict) -> Set[str]:
        """Extract all IAM actions from the policy document"""
        actions = set()

        for statement in policy_doc.get('Statement', []):
            if statement.get('Effect') == 'Allow':
                statement_actions = statement.get('Action', [])
                if isinstance(statement_actions, str):
                    statement_actions = [statement_actions]
                actions.update(statement_actions)

        return actions

    def extract_action_resource_map(self, policy_doc: Dict) -> Dict[str, List[str]]:
        """Extract a mapping of action -> resource ARNs from the policy document.

        Actions that appear in multiple statements get the union of all resources.
        If any statement grants an action on '*', that subsumes all other resources
        (the IAM simulator rejects mixing '*' with specific ARNs).
        """
        action_resources: Dict[str, set] = {}

        for statement in policy_doc.get('Statement', []):
            if statement.get('Effect') != 'Allow':
                continue

            statement_actions = statement.get('Action', [])
            if isinstance(statement_actions, str):
                statement_actions = [statement_actions]

            stmt_resources = statement.get('Resource', '*')
            if isinstance(stmt_resources, str):
                stmt_resources = [stmt_resources]

            for action in statement_actions:
                if action not in action_resources:
                    action_resources[action] = set()
                action_resources[action].update(stmt_resources)

        # Normalize: if '*' is present, it subsumes all other ARNs.
        # The IAM simulator rejects lists containing both '*' and specific ARNs.
        result: Dict[str, List[str]] = {}
        for action, res in action_resources.items():
            if '*' in res:
                result[action] = ['*']
            else:
                result[action] = sorted(res)

        return result

    def extract_action_conditions_map(self, policy_doc: Dict) -> Dict[str, List[Dict]]:
        """Extract a mapping of action -> ContextEntries for the IAM simulator.

        For actions that have a Condition block with StringEquals on a
        ResourceTag key, this builds the ContextEntries list that tells the
        simulator to assume the resource carries the required tag.
        """
        action_conditions: Dict[str, List[Dict]] = {}

        for statement in policy_doc.get('Statement', []):
            if statement.get('Effect') != 'Allow':
                continue

            condition = statement.get('Condition')
            if not condition:
                continue

            # Build context entries from StringEquals conditions on resource tags
            context_entries = []
            string_equals = condition.get('StringEquals', {})
            for key, value in string_equals.items():
                # Match patterns like "ec2:ResourceTag/ManagedBy" or "aws:ResourceTag/ManagedBy"
                if 'ResourceTag/' in key:
                    if isinstance(value, str):
                        value = [value]
                    context_entries.append({
                        'ContextKeyName': key,
                        'ContextKeyType': 'string',
                        'ContextKeyValues': value,
                    })

            if not context_entries:
                continue

            statement_actions = statement.get('Action', [])
            if isinstance(statement_actions, str):
                statement_actions = [statement_actions]

            for action in statement_actions:
                if action not in action_conditions:
                    action_conditions[action] = []
                # Merge entries, avoiding duplicates
                for entry in context_entries:
                    if entry not in action_conditions[action]:
                        action_conditions[action].append(entry)

        return action_conditions

    def get_current_principal(self) -> Tuple[str, str]:
        """Get the current AWS principal ARN and type"""
        try:
            identity = self.sts_client.get_caller_identity()
            arn = identity['Arn']
            debug_print(f"Current identity ARN: {arn}")

            # Determine principal type from ARN
            if ':user/' in arn:
                principal_type = 'user'
                policy_source_arn = arn
                debug_print(f"Principal type: IAM User")
            elif ':role/' in arn:
                principal_type = 'role'
                policy_source_arn = arn
                debug_print(f"Principal type: IAM Role")
            elif ':assumed-role/' in arn:
                principal_type = 'assumed-role'
                # Convert assumed-role ARN to role ARN for SimulatePrincipalPolicy
                # From: arn:aws:sts::123456789012:assumed-role/RoleName/SessionName
                # To:   arn:aws:iam::123456789012:role/RoleName
                parts = arn.split(':')
                if len(parts) >= 6:
                    account = parts[4]
                    role_session = parts[5].split('/')
                    if len(role_session) >= 2 and role_session[0] == 'assumed-role':
                        role_name = role_session[1]
                        policy_source_arn = f"arn:aws:iam::{account}:role/{role_name}"
                        debug_print(f"Principal type: Assumed Role (converted to role ARN)")
                        debug_print(f"Converted ARN for simulation: {policy_source_arn}")
                    else:
                        policy_source_arn = arn
                else:
                    policy_source_arn = arn
            else:
                principal_type = 'unknown'
                policy_source_arn = arn
                debug_print(f"Principal type: Unknown")

            return policy_source_arn, principal_type

        except ClientError as e:
            raise RuntimeError(f"Failed to get current identity: {e}")

    def simulate_permissions(
        self,
        actions: List[str],
        principal_arn: str,
        action_resource_map: Optional[Dict[str, List[str]]] = None,
        action_conditions_map: Optional[Dict[str, List[Dict]]] = None,
    ) -> Dict[str, bool]:
        """
        Simulate IAM permissions for the given actions.
        Returns a dict mapping action to granted (True/False).

        When action_resource_map is provided, actions whose policy statements
        use resource-scoped ARNs (not just '*') are simulated with those
        specific ARNs. This avoids false negatives from the IAM simulator
        when a principal has broad access but the reference policy restricts
        resources.

        When action_conditions_map is provided, actions with tag-based
        conditions are simulated with ContextEntries that tell the simulator
        to assume the resource carries the required tags (e.g. ManagedBy).
        """
        results = {}
        conditions_map = action_conditions_map or {}
        debug_print(f"Starting permission simulation for {len(actions)} actions")
        debug_print(f"Using principal ARN: {principal_arn}")
        if conditions_map:
            debug_print(f"Condition context entries for {len(conditions_map)} actions")

        # Separate actions into wildcard-resource vs scoped-resource groups
        wildcard_actions = []
        scoped_groups: Dict[tuple, List[str]] = {}  # resource_arns_tuple -> actions

        for action in actions:
            resource_arns = (action_resource_map or {}).get(action, ['*'])
            if resource_arns == ['*']:
                wildcard_actions.append(action)
            else:
                key = tuple(resource_arns)
                if key not in scoped_groups:
                    scoped_groups[key] = []
                scoped_groups[key].append(action)

        if scoped_groups:
            debug_print(
                f"Split into {len(wildcard_actions)} wildcard actions and "
                f"{sum(len(a) for a in scoped_groups.values())} resource-scoped actions "
                f"across {len(scoped_groups)} resource groups"
            )

        # Helper to run a batch simulation
        def _simulate_batch(
            batch_actions: List[str],
            resource_arns: List[str],
            context_entries: Optional[List[Dict]] = None,
        ) -> Optional[Dict[str, bool]]:
            batch_results = {}
            batch_size = 100
            for i in range(0, len(batch_actions), batch_size):
                chunk = batch_actions[i:i + batch_size]
                debug_print(f"  Simulating {len(chunk)} actions with resources: {resource_arns[:3]}{'...' if len(resource_arns) > 3 else ''}")

                try:
                    kwargs = dict(
                        PolicySourceArn=principal_arn,
                        ActionNames=chunk,
                        ResourceArns=resource_arns,
                    )
                    if context_entries:
                        kwargs['ContextEntries'] = context_entries
                        debug_print(f"  With {len(context_entries)} context entries")

                    response = self.iam_client.simulate_principal_policy(**kwargs)

                    for eval_result in response.get('EvaluationResults', []):
                        action = eval_result['EvalActionName']
                        decision = eval_result['EvalDecision']
                        batch_results[action] = (decision == 'allowed')
                        if DEBUG and decision != 'allowed':
                            debug_print(f"    - {action}: {decision}")

                except ClientError as e:
                    error_code = e.response['Error']['Code']
                    debug_print(f"Error during simulation: {error_code} - {str(e)}")

                    if error_code in ['AccessDenied', 'UnauthorizedOperation']:
                        debug_print("User lacks permission to simulate policies (iam:SimulatePrincipalPolicy)")
                        return None
                    else:
                        raise RuntimeError(f"Failed to simulate permissions: {e}")

            return batch_results

        # Further split actions: those with conditions need separate simulation
        def _split_by_conditions(action_list: List[str]) -> Tuple[List[str], Dict[tuple, List[str]]]:
            """Split actions into unconditioned and conditioned groups."""
            unconditioned = []
            conditioned: Dict[tuple, List[str]] = {}
            for action in action_list:
                entries = conditions_map.get(action)
                if entries:
                    # Use a hashable key from the context entries
                    key = tuple(
                        (e['ContextKeyName'], tuple(e['ContextKeyValues']))
                        for e in entries
                    )
                    if key not in conditioned:
                        conditioned[key] = []
                    conditioned[key].append(action)
                else:
                    unconditioned.append(action)
            return unconditioned, conditioned

        def _entries_from_key(key: tuple) -> List[Dict]:
            """Reconstruct ContextEntries from the hashable key."""
            return [
                {
                    'ContextKeyName': name,
                    'ContextKeyType': 'string',
                    'ContextKeyValues': list(values),
                }
                for name, values in key
            ]

        # Simulate wildcard-resource actions
        if wildcard_actions:
            unconditioned, conditioned = _split_by_conditions(wildcard_actions)

            if unconditioned:
                debug_print(f"Simulating {len(unconditioned)} wildcard-resource actions (no conditions)")
                batch_result = _simulate_batch(unconditioned, ['*'])
                if batch_result is None:
                    return None
                results.update(batch_result)

            for cond_key, cond_actions in conditioned.items():
                entries = _entries_from_key(cond_key)
                debug_print(f"Simulating {len(cond_actions)} wildcard-resource actions with conditions")
                batch_result = _simulate_batch(cond_actions, ['*'], context_entries=entries)
                if batch_result is None:
                    return None
                results.update(batch_result)

        # Simulate each scoped-resource group with its specific ARNs
        for resource_arns_tuple, group_actions in scoped_groups.items():
            resource_arns = list(resource_arns_tuple)
            unconditioned, conditioned = _split_by_conditions(group_actions)

            if unconditioned:
                debug_print(f"Simulating {len(unconditioned)} scoped actions for resources: {resource_arns}")
                batch_result = _simulate_batch(unconditioned, resource_arns)
                if batch_result is None:
                    return None
                results.update(batch_result)

            for cond_key, cond_actions in conditioned.items():
                entries = _entries_from_key(cond_key)
                debug_print(f"Simulating {len(cond_actions)} scoped actions with conditions for resources: {resource_arns}")
                batch_result = _simulate_batch(cond_actions, resource_arns, context_entries=entries)
                if batch_result is None:
                    return None
                results.update(batch_result)

        debug_print(f"Simulation complete: {len([v for v in results.values() if v])} allowed, {len([v for v in results.values() if not v])} denied")
        return results

    def check_permission_fallback(self, action: str) -> Optional[bool]:
        """
        Fallback method to check a single permission by attempting a dry-run.
        Only works for certain read operations.
        """
        # This is a limited fallback for when SimulatePrincipalPolicy isn't available
        # We can only test a few safe read operations

        safe_test_operations = {
            'sts:GetCallerIdentity': lambda: self.sts_client.get_caller_identity(),
            'ec2:DescribeRegions': lambda: self.session.client('ec2').describe_regions(DryRun=True),
            'iam:ListUsers': lambda: self.iam_client.list_users(MaxItems=1),
            # Add more safe operations as needed
        }

        if action not in safe_test_operations:
            return None  # Can't test this action

        try:
            safe_test_operations[action]()
            return True
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code in ['AccessDenied', 'UnauthorizedOperation']:
                return False
            elif error_code == 'DryRunOperation':
                return True  # Dry run succeeded, permission is granted
            else:
                return None  # Unknown error, can't determine

    def map_actions_to_features(self, missing_actions: List[str]) -> Dict[str, List[str]]:
        """Map missing IAM actions to affected CLI features"""
        affected_features = {}

        for action in missing_actions:
            affected_features[action] = []

            for feature, required_actions in self.FEATURE_PERMISSIONS.items():
                if action in required_actions:
                    affected_features[action].append(feature)

        return affected_features

    def check_assume_role_bootstrap(self, principal_arn: str) -> Tuple[bool, List[str], List[str]]:
        """Check if the user has permissions to deploy the assume-role stack.

        Uses the structured ASSUME_ROLE_BOOTSTRAP_POLICY which includes
        resource-scoped ARNs (CloudFormation stacks and IAM roles).

        Returns:
            (can_bootstrap, granted_actions, missing_actions)
        """
        policy = self.ASSUME_ROLE_BOOTSTRAP_POLICY
        actions = list(self.extract_actions_from_policy(policy))
        action_resource_map = self.extract_action_resource_map(policy)

        results = self.simulate_permissions(
            actions, principal_arn, action_resource_map
        )
        if results is None:
            # Can't simulate at all
            return False, [], actions

        granted = [a for a, v in results.items() if v]
        missing = [a for a, v in results.items() if not v]
        return len(missing) == 0, granted, missing

    def validate(self) -> ValidationReport:
        """
        Perform complete validation of IAM permissions.
        Returns a ValidationReport with detailed results.
        """
        report = ValidationReport()
        debug_print("Starting IAM permission validation")

        try:
            # Load the policy
            debug_print("Loading IAM policy from package resources")
            policy_doc = self.load_policy_json()
            report.policy_doc = policy_doc
            required_actions = self.extract_actions_from_policy(policy_doc)
            action_resource_map = self.extract_action_resource_map(policy_doc)
            action_conditions_map = self.extract_action_conditions_map(policy_doc)
            report.total_required = len(required_actions)
            debug_print(f"Found {report.total_required} required actions in policy")
            if action_conditions_map:
                debug_print(f"Found conditions for {len(action_conditions_map)} actions")

            # Get current principal
            principal_arn, _ = self.get_current_principal()

            # Simulate permissions with resource-aware and condition-aware checking
            simulation_results = self.simulate_permissions(
                list(required_actions), principal_arn, action_resource_map, action_conditions_map
            )

            if simulation_results is None:
                # Can't simulate - user lacks the critical permission
                report.error_message = (
                    "Cannot validate IAM permissions: Missing 'iam:SimulatePrincipalPolicy' permission. "
                    "This permission is required for the validator to check your AWS permissions. "
                    "Please add this permission to your IAM policy and try again."
                )

                # Still try to check basic connectivity
                critical_actions = ['sts:GetCallerIdentity']
                simulation_results = {}

                for action in critical_actions:
                    result = self.check_permission_fallback(action)
                    if result is not None:
                        simulation_results[action] = result

                # Mark other permissions as unknown
                for action in required_actions:
                    if action not in simulation_results:
                        simulation_results[action] = None

                # Add a special permission gap for the simulator permission itself
                simulator_gap = PermissionGap(
                    action="iam:SimulatePrincipalPolicy",
                    affected_features=["setup validate - IAM permission checking"],
                    severity="CRITICAL",
                    reason="Required for permission validation to work"
                )
                report.missing_actions.append(simulator_gap)

            # Process results
            for action, granted in simulation_results.items():
                if granted is True:
                    report.granted_actions.append(action)
                elif granted is False:
                    # Find affected features
                    affected = []
                    for feature, actions in self.FEATURE_PERMISSIONS.items():
                        if action in actions:
                            affected.append(feature)

                    gap = PermissionGap(
                        action=action,
                        affected_features=affected,
                        severity="CRITICAL" if len(affected) > 2 else "WARNING"
                    )
                    report.missing_actions.append(gap)

                    # Update affected commands mapping
                    for feature in affected:
                        if action not in report.affected_commands:
                            report.affected_commands[action] = []
                        report.affected_commands[action].append(feature)

            # Calculate summary
            report.total_granted = len(report.granted_actions)
            report.all_passed = (len(report.missing_actions) == 0 and report.error_message is None)

        except Exception as e:
            report.error_message = str(e)
            report.all_passed = False

        return report

    def format_report(self, report: ValidationReport) -> str:
        """Format the validation report for display"""
        lines = []

        if report.all_passed:
            lines.append(f"[OK] All {report.total_required} required IAM permissions are granted")
        else:
            if report.error_message:
                lines.append(f"[WARN] {report.error_message}")

            if report.missing_actions:
                lines.append(f"[ERROR] Missing {len(report.missing_actions)} required permissions:")
                lines.append("")

                # Group by affected features for cleaner display
                feature_to_actions = {}
                for gap in report.missing_actions:
                    for feature in gap.affected_features:
                        if feature not in feature_to_actions:
                            feature_to_actions[feature] = []
                        feature_to_actions[feature].append(gap.action)

                for feature, actions in sorted(feature_to_actions.items()):
                    lines.append(f"  {feature}:")
                    for action in sorted(actions):
                        lines.append(f"    - {action}")

        return "\n".join(lines)

    def generate_missing_permissions_json(
        self,
        missing_actions: List[PermissionGap],
        policy_doc: Optional[Dict] = None,
    ) -> str:
        """Generate JSON policy statements for missing permissions.

        When policy_doc is provided, the generated statements preserve the
        original resource scoping and conditions (e.g. tag-based conditions
        on destructive actions). Otherwise falls back to a single
        Resource:'*' statement.
        """
        if not missing_actions:
            return ""

        missing_set = {gap.action for gap in missing_actions}

        if policy_doc:
            # Reconstruct statements from the original policy, keeping only
            # actions that are missing. This preserves Resource and Condition.
            statements = []
            for stmt in policy_doc.get('Statement', []):
                if stmt.get('Effect') != 'Allow':
                    continue
                stmt_actions = stmt.get('Action', [])
                if isinstance(stmt_actions, str):
                    stmt_actions = [stmt_actions]
                overlap = sorted(set(stmt_actions) & missing_set)
                if not overlap:
                    continue
                new_stmt = {
                    "Sid": stmt.get('Sid', 'TagManagerCLIMissing'),
                    "Effect": "Allow",
                    "Action": overlap if len(overlap) > 1 else overlap[0],
                    "Resource": stmt.get('Resource', '*'),
                }
                if 'Condition' in stmt:
                    new_stmt['Condition'] = stmt['Condition']
                statements.append(new_stmt)

            if statements:
                policy = {"Version": "2012-10-17", "Statement": statements}
                return json.dumps(policy, indent=2)

        # Fallback: single flat statement
        actions = sorted(missing_set)
        policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Sid": "TagManagerCLIMissingPermissions",
                    "Effect": "Allow",
                    "Action": actions,
                    "Resource": "*"
                }
            ]
        }
        return json.dumps(policy, indent=2)
