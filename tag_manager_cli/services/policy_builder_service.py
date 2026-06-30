"""Interactive policy builder service for creating AWS Organizations tag policies."""

import json
from typing import Dict, List, Optional, Any
from rich.console import Console
from rich.prompt import Prompt, Confirm, IntPrompt
from rich.syntax import Syntax
from rich.panel import Panel
from rich.table import Table

from ..data.resource_types import (
    get_common_resource_types,
    get_all_resource_types,
    RESOURCE_TYPES,
    search_resource_types
)

console = Console()


class TagRule:
    """Represents a single tag rule in a tag policy."""

    def __init__(self, tag_key: str):
        """Initialize a tag rule.

        Args:
            tag_key: The AWS tag key that will be enforced
        """
        self.tag_key = tag_key  # This is the actual AWS tag key
        self.enforce_case: bool = False  # Whether to enforce specific capitalization
        self.case_treatment: Optional[str] = None  # Specific case to enforce (if different)
        self.include_tag_key: bool = False  # Include tag_key field even without case enforcement
        self.tag_values: List[str] = []
        self.use_regex: bool = False
        self.operator: str = "@@assign"
        self.enforcement_enabled: bool = False
        self.enforced_resources: List[str] = []

        # Child control operators
        self.tag_key_child_operators: Optional[List[str]] = None
        self.tag_value_child_operators: Optional[List[str]] = None
        self.enforced_for_child_operators: Optional[List[str]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert tag rule to policy JSON format.

        Returns:
            Dictionary representing the tag rule in AWS policy format
        """
        rule = {}

        # Add tag_key if:
        # 1. Case enforcement is enabled with specific treatment, OR
        # 2. User explicitly wants to include it (for child control operators or explicit definition)
        if (self.enforce_case and self.case_treatment) or self.include_tag_key:
            tag_key_value = self.case_treatment if self.case_treatment else self.tag_key

            # Build tag_key field
            tag_key_field = {self.operator: tag_key_value}

            # Add child control operators if specified
            if self.tag_key_child_operators:
                tag_key_field["@@operators_allowed_for_child_policies"] = self.tag_key_child_operators

            rule["tag_key"] = tag_key_field

        # Add tag values
        if self.tag_values:
            # AWS requires tag_value to always be a list for @@assign, @@append, @@remove
            # Even for single values or regex patterns
            tag_value_field = {self.operator: self.tag_values}

            # Add child control operators if specified
            if self.tag_value_child_operators:
                tag_value_field["@@operators_allowed_for_child_policies"] = self.tag_value_child_operators

            rule["tag_value"] = tag_value_field

        # Add enforcement
        if self.enforcement_enabled and self.enforced_resources:
            enforced_for_field = {self.operator: self.enforced_resources}

            # Add child control operators if specified
            if self.enforced_for_child_operators:
                enforced_for_field["@@operators_allowed_for_child_policies"] = self.enforced_for_child_operators

            rule["enforced_for"] = enforced_for_field

        return rule

    def summary(self) -> str:
        """Get a human-readable summary of the tag rule.

        Returns:
            Formatted string summary of the rule
        """
        lines = []
        lines.append(f"Tag Key: {self.tag_key}")

        if self.enforce_case and self.case_treatment:
            lines.append(f"  Case enforcement: {self.case_treatment}")
        elif self.include_tag_key:
            lines.append(f"  Include tag_key field: Yes")

        if self.tag_key_child_operators:
            lines.append(f"  Tag key child control: {', '.join(self.tag_key_child_operators)}")

        if self.tag_values:
            if self.use_regex:
                lines.append(f"  Pattern: {self.tag_values[0]}")
            else:
                lines.append(f"  Allowed values: {', '.join(self.tag_values)}")
        else:
            lines.append("  Allowed values: Any")

        if self.tag_value_child_operators:
            lines.append(f"  Tag value child control: {', '.join(self.tag_value_child_operators)}")

        lines.append(f"  Operator: {self.operator}")

        if self.enforcement_enabled:
            lines.append(f"  Enforced on: {', '.join(self.enforced_resources)}")
            if self.enforced_for_child_operators:
                lines.append(f"  Enforcement child control: {', '.join(self.enforced_for_child_operators)}")
        else:
            lines.append("  Enforcement: Disabled")

        return "\n".join(lines)


class PolicyBuilder:
    """Interactive builder for AWS Organizations tag policies."""

    def __init__(self):
        """Initialize the policy builder."""
        self.policy_name: Optional[str] = None
        self.policy_description: Optional[str] = None
        self.tag_rules: Dict[str, TagRule] = {}
        self.metadata_set: bool = False  # Track if metadata has been collected

    def load_from_policy(self, policy_content: Dict[str, Any]):
        """Load existing policy content into the builder.

        Args:
            policy_content: The policy content dict with 'tags' key
        """
        tags = policy_content.get('tags', {})

        for tag_key, tag_rule_dict in tags.items():
            # Create a new TagRule for this tag
            rule = TagRule(tag_key)

            # Parse tag_key field if present
            if 'tag_key' in tag_rule_dict:
                tag_key_field = tag_rule_dict['tag_key']

                # Extract operator and value
                for op in ['@@assign', '@@append', '@@remove']:
                    if op in tag_key_field:
                        rule.operator = op
                        case_value = tag_key_field[op]
                        if case_value != tag_key:
                            rule.enforce_case = True
                            rule.case_treatment = case_value
                        else:
                            rule.include_tag_key = True
                        break

                # Extract child control operators
                if '@@operators_allowed_for_child_policies' in tag_key_field:
                    rule.tag_key_child_operators = tag_key_field['@@operators_allowed_for_child_policies']

            # Parse tag_value field if present
            if 'tag_value' in tag_rule_dict:
                tag_value_field = tag_rule_dict['tag_value']

                # Extract operator and values
                for op in ['@@assign', '@@append', '@@remove']:
                    if op in tag_value_field:
                        rule.operator = op
                        values = tag_value_field[op]
                        if isinstance(values, list):
                            rule.tag_values = values
                        else:
                            rule.tag_values = [values]
                        break

                # Extract child control operators
                if '@@operators_allowed_for_child_policies' in tag_value_field:
                    rule.tag_value_child_operators = tag_value_field['@@operators_allowed_for_child_policies']

            # Parse enforced_for field if present
            if 'enforced_for' in tag_rule_dict:
                enforced_for_field = tag_rule_dict['enforced_for']

                # Extract operator and resources
                for op in ['@@assign', '@@append', '@@remove']:
                    if op in enforced_for_field:
                        rule.operator = op
                        resources = enforced_for_field[op]
                        if isinstance(resources, list):
                            rule.enforced_resources = resources
                        else:
                            rule.enforced_resources = [resources]
                        rule.enforcement_enabled = True
                        break

                # Extract child control operators
                if '@@operators_allowed_for_child_policies' in enforced_for_field:
                    rule.enforced_for_child_operators = enforced_for_field['@@operators_allowed_for_child_policies']

            # Add the rule to our collection
            self.tag_rules[tag_key] = rule

    def collect_metadata(self):
        """Collect policy metadata from user."""
        console.print("\n[bold cyan]Policy Metadata[/bold cyan]")
        console.print("=" * 50)

        self.policy_name = Prompt.ask(
            "[cyan]Policy name[/cyan]",
            default=self.policy_name or "my-tag-policy"
        )

        self.policy_description = Prompt.ask(
            "[cyan]Description[/cyan]",
            default=self.policy_description or "Tag policy created with tag-manager"
        )

        self.metadata_set = True
        console.print(f"\n[green]OK[/green] Policy name: {self.policy_name}")

    def _ask_child_control_operators(self, field_name: str) -> Optional[List[str]]:
        """Ask user about child control operators for a field.

        Args:
            field_name: Name of the field (e.g., "tag_key", "tag_value", "enforced_for")

        Returns:
            List of allowed operators, or None if user wants default (all)
        """
        console.print(f"\n[cyan]Child Policy Control for {field_name} (Advanced):[/cyan]")
        console.print("[dim]Controls what child policies (lower in org tree) can do with this field[/dim]")
        console.print("[1] Allow all operators (default - children can modify)")
        console.print("    [dim]Child policies have full flexibility[/dim]")
        console.print("[2] Lock down (@@none - children cannot modify)")
        console.print("    [dim]Prevents child policies from changing this field[/dim]")
        console.print("[3] Allow append only")
        console.print("    [dim]Children can add values but not remove or replace[/dim]")
        console.print("[4] Allow remove only")
        console.print("    [dim]Children can remove values but not add or replace[/dim]")
        console.print("[5] Custom (select specific operators)")
        console.print("    [dim]Choose which operators children can use[/dim]")
        console.print("[S] Skip (use default)")

        choice_str = Prompt.ask("Choice", choices=["1", "2", "3", "4", "5", "s", "S"], default="s")

        # Skip/default
        if choice_str.lower() == 's' or choice_str == "1":
            return None  # Default is @@all, so we don't need to specify it

        # Lock down
        if choice_str == "2":
            return ["@@none"]

        # Append only
        if choice_str == "3":
            return ["@@append"]

        # Remove only
        if choice_str == "4":
            return ["@@remove"]

        # Custom
        if choice_str == "5":
            console.print("\n[cyan]Select allowed operators:[/cyan]")
            console.print("[dim]Enter numbers comma-separated (e.g., 1,2,3)[/dim]")
            console.print("[1] @@assign")
            console.print("[2] @@append")
            console.print("[3] @@remove")

            custom_choice = Prompt.ask("Operators", default="1,2,3")

            operators = []
            if '1' in custom_choice:
                operators.append("@@assign")
            if '2' in custom_choice:
                operators.append("@@append")
            if '3' in custom_choice:
                operators.append("@@remove")

            return operators if operators else None

        return None

    def add_tag_rule_interactive(self):
        """Interactively add a new tag rule."""
        console.print("\n[bold yellow]Adding New Tag Rule[/bold yellow]")
        console.print("=" * 50)

        # Get tag key
        console.print("\n[cyan]Tag Key:[/cyan]")
        console.print("[dim]This is the AWS tag key that will be enforced (e.g., 'Environment', 'CostCenter')[/dim]")
        console.print("[dim]Type 'back' or 'b' to return to main menu[/dim]")
        tag_key = Prompt.ask(
            "[cyan]Enter tag key[/cyan]"
        )

        # Check for back navigation
        if tag_key.lower() in ['back', 'b']:
            console.print("[yellow]Returning to main menu[/yellow]")
            return

        if tag_key in self.tag_rules:
            if not Confirm.ask(f"[yellow]Tag '{tag_key}' already exists. Replace it?[/yellow]"):
                return

        rule = TagRule(tag_key)

        # Case enforcement (advanced feature)
        console.print("\n[cyan]Case Enforcement (Advanced):[/cyan]")
        console.print("[dim]By default, tag keys are case-sensitive and must match exactly[/dim]")
        console.print("[dim]You can enforce a specific capitalization even if users tag with different cases[/dim]")
        console.print("[dim]Example: Accept 'environment', 'ENVIRONMENT', etc., but enforce 'Environment'[/dim]")

        rule.enforce_case = Confirm.ask(
            "[cyan]Enable case enforcement (allow case-insensitive tagging)?[/cyan]",
            default=False
        )

        if rule.enforce_case:
            console.print("[dim]Type 'back' or 'b' to cancel[/dim]")
            rule.case_treatment = Prompt.ask(
                "[cyan]Enter the specific capitalization to enforce[/cyan]",
                default=tag_key
            )

            # Check for back navigation
            if rule.case_treatment and rule.case_treatment.lower() in ['back', 'b']:
                console.print("[yellow]Tag rule cancelled[/yellow]")
                return

            # Validate that case_treatment matches tag_key (except for case)
            if rule.case_treatment and rule.case_treatment.lower() != tag_key.lower():
                console.print(f"[red]ERROR: Case treatment must be a case variant of '{tag_key}'[/red]")
                console.print(f"[yellow]'{rule.case_treatment}' is not the same as '{tag_key}' (ignoring case)[/yellow]")
                console.print("[yellow]Tag rule cancelled[/yellow]")
                return
        else:
            # If not using case enforcement, ask if they want to include tag_key anyway
            console.print("\n[cyan]Include tag_key field (Advanced):[/cyan]")
            console.print("[dim]Useful for locking down tag key with child control operators[/dim]")
            console.print("[dim]Or for explicit policy definition even when case-sensitive[/dim]")
            rule.include_tag_key = Confirm.ask(
                "[cyan]Include tag_key field in policy?[/cyan]",
                default=False
            )

        # Child control operators for tag_key (if it will be included)
        if rule.enforce_case or rule.include_tag_key:
            rule.tag_key_child_operators = self._ask_child_control_operators("tag_key")

        # Tag values
        console.print("\n[cyan]Tag values:[/cyan]")
        console.print("[1] Enter allowed values (list)")
        console.print("    [dim]Example: prod,staging,dev - Only these specific values are allowed[/dim]")
        console.print("[2] Enter regex pattern")
        console.print("    [dim]Example: CC-[0-9]{{4}} - Match values like CC-1234, CC-5678[/dim]")
        console.print("[3] Any value allowed")
        console.print("    [dim]No restrictions - Any value can be used for this tag[/dim]")
        console.print("[B] Go back")

        value_choice_str = Prompt.ask("Choice", choices=["1", "2", "3", "b", "B"], default="1")

        # Check for back navigation
        if value_choice_str.lower() == 'b':
            console.print("[yellow]Tag rule cancelled[/yellow]")
            return

        value_choice = int(value_choice_str)

        if value_choice == 1:
            # List of allowed values
            values_input = Prompt.ask(
                "[cyan]Enter allowed values (comma-separated)[/cyan]"
            )
            rule.tag_values = [v.strip() for v in values_input.split(",") if v.strip()]
            rule.use_regex = False
            console.print(f"[green]Values: {rule.tag_values}[/green]")

        elif value_choice == 2:
            # Regex pattern
            pattern = Prompt.ask("[cyan]Enter regex pattern[/cyan]")
            rule.tag_values = [pattern]
            rule.use_regex = True
            console.print(f"[green]Pattern: {pattern}[/green]")

        else:
            # Any value
            rule.tag_values = []
            console.print("[green]Any value allowed[/green]")

        # Inheritance operator
        console.print("\n[cyan]Inheritance operator:[/cyan]")
        console.print("[dim]These operators control how this policy interacts with parent policies[/dim]")
        console.print("[1] @@assign (replace inherited values)")
        console.print("    [dim]Replace any parent values - this policy takes full control[/dim]")
        console.print("[2] @@append (add to inherited values)")
        console.print("    [dim]Add to parent values - combine with inherited rules[/dim]")
        console.print("[3] @@remove (remove from inherited values)")
        console.print("    [dim]Remove from parent values - exclude specific inherited values[/dim]")
        console.print("[B] Go back")

        operator_choice_str = Prompt.ask("Choice", choices=["1", "2", "3", "b", "B"], default="1")

        # Check for back navigation
        if operator_choice_str.lower() == 'b':
            console.print("[yellow]Tag rule cancelled[/yellow]")
            return

        operator_choice = int(operator_choice_str)

        if operator_choice == 1:
            rule.operator = "@@assign"
        elif operator_choice == 2:
            rule.operator = "@@append"
        else:
            rule.operator = "@@remove"

        console.print(f"[green]Operator: {rule.operator}[/green]")

        # Child control operators for tag_value (if tag values are specified)
        if rule.tag_values:
            rule.tag_value_child_operators = self._ask_child_control_operators("tag_value")

        # Enforcement
        console.print("\n[cyan]Enforcement:[/cyan]")
        console.print("[dim]When enabled, AWS will PREVENT noncompliant tagging operations[/dim]")
        console.print("[dim]When disabled, policy is for reporting only (no blocking)[/dim]")

        rule.enforcement_enabled = Confirm.ask(
            "[cyan]Enable enforcement?[/cyan]",
            default=True
        )

        if rule.enforcement_enabled:
            enforced_resources = self._select_resource_types()
            # Check if user went back
            if enforced_resources is None:
                console.print("[yellow]Tag rule cancelled[/yellow]")
                return
            rule.enforced_resources = enforced_resources

            # Child control operators for enforced_for
            rule.enforced_for_child_operators = self._ask_child_control_operators("enforced_for")

        # Show summary and confirm
        console.print("\n[bold]Summary:[/bold]")
        console.print(Panel(rule.summary(), title="Tag Rule", border_style="green"))

        if Confirm.ask("\n[cyan]Add this tag rule?[/cyan]", default=True):
            self.tag_rules[tag_key] = rule
            console.print(f"[green]OK Tag rule '{tag_key}' added![/green]")
        else:
            console.print("[yellow]Tag rule discarded[/yellow]")

    def _select_resource_types(self) -> Optional[List[str]]:
        """Interactively select resource types for enforcement.

        Returns:
            List of selected resource types, or None if user wants to go back
        """
        console.print("\n[cyan]Select resource types to enforce:[/cyan]")
        console.print("[dim]Choose which AWS resources this tag rule applies to[/dim]")
        console.print("[1] Choose from common types")
        console.print("    [dim]Quick selection of popular resource types (EC2, S3, etc.)[/dim]")
        console.print("[2] Choose by service")
        console.print("    [dim]Browse all resource types by AWS service[/dim]")
        console.print("[3] Enter custom types")
        console.print("    [dim]Manually type specific resource types[/dim]")
        console.print("[4] Use wildcard (all supported)")
        console.print("    [dim]Apply to ALL supported AWS resources[/dim]")
        console.print("[B] Go back")

        choice_str = Prompt.ask("Choice", choices=["1", "2", "3", "4", "b", "B"], default="1")

        # Check for back navigation
        if choice_str.lower() == 'b':
            return None

        choice = int(choice_str)

        if choice == 1:
            return self._select_from_common_types()
        elif choice == 2:
            return self._select_by_service()
        elif choice == 3:
            return self._enter_custom_types()
        else:
            return ["*:*"]  # All supported resources

    def _select_from_common_types(self) -> Optional[List[str]]:
        """Select from common resource types.

        Returns:
            List of selected resource types, or None if user wants to go back
        """
        common_types = get_common_resource_types()

        console.print("\n[cyan]Common resource types:[/cyan]")
        for idx, resource_type in enumerate(common_types, 1):
            console.print(f"[{idx}] {resource_type}")

        console.print("\nEnter numbers (comma-separated), 'all', 'back', or type custom:")
        selection = Prompt.ask("Selection")

        # Check for back navigation
        if selection.lower() in ['back', 'b']:
            return None

        if selection.lower() == "all":
            return common_types

        # Parse selection
        selected = []
        for part in selection.split(","):
            part = part.strip()
            if part.isdigit():
                idx = int(part) - 1
                if 0 <= idx < len(common_types):
                    selected.append(common_types[idx])
            else:
                # Custom type entered
                selected.append(part)

        return selected if selected else None

    def _select_by_service(self) -> Optional[List[str]]:
        """Select resource types by service.

        Returns:
            List of selected resource types, or None if user wants to go back
        """
        services = list(RESOURCE_TYPES.keys())

        console.print("\n[cyan]Available services:[/cyan]")
        for idx, service in enumerate(services, 1):
            console.print(f"[{idx}] {service}")
        console.print("[B] Go back")

        service_choice = Prompt.ask(
            "Select service",
            choices=[str(i) for i in range(1, len(services) + 1)] + ["b", "B"]
        )

        # Check for back navigation
        if service_choice.lower() == 'b':
            return None

        service_idx = int(service_choice)
        service_name = services[service_idx - 1]
        resource_types = RESOURCE_TYPES[service_name]

        console.print(f"\n[cyan]{service_name} resource types:[/cyan]")
        for idx, resource_type in enumerate(resource_types, 1):
            console.print(f"[{idx}] {resource_type}")

        console.print("\nEnter numbers (comma-separated), 'all', or 'back':")
        selection = Prompt.ask("Selection")

        # Check for back navigation
        if selection.lower() in ['back', 'b']:
            return None

        if selection.lower() == "all":
            # Return all non-wildcard types
            return [rt for rt in resource_types if not rt.endswith(":*")]

        # Parse selection
        selected = []
        for part in selection.split(","):
            part = part.strip()
            if part.isdigit():
                idx = int(part) - 1
                if 0 <= idx < len(resource_types):
                    selected.append(resource_types[idx])

        return selected if selected else None

    def _enter_custom_types(self) -> Optional[List[str]]:
        """Enter custom resource types.

        Returns:
            List of entered resource types, or None if user wants to go back
        """
        console.print("\n[cyan]Enter resource types (comma-separated):[/cyan]")
        console.print("[dim]Examples: ec2:instance, s3:bucket, ec2:*[/dim]")
        console.print("[dim]Type 'back' or 'b' to return[/dim]")

        types_input = Prompt.ask("Resource types")

        # Check for back navigation
        if types_input.lower() in ['back', 'b']:
            return None

        result = [t.strip() for t in types_input.split(",") if t.strip()]
        return result if result else None

    def edit_tag_rule(self):
        """Edit an existing tag rule."""
        if not self.tag_rules:
            console.print("[yellow]No tag rules to edit[/yellow]")
            return

        console.print("\n[bold cyan]Edit Tag Rule[/bold cyan]")
        console.print("=" * 50)

        # Show available tags
        console.print("\n[cyan]Available tag keys:[/cyan]")
        tag_keys = list(self.tag_rules.keys())
        for idx, tag_key in enumerate(tag_keys, 1):
            console.print(f"[{idx}] {tag_key}")
        console.print("[B] Go back")

        choice_str = Prompt.ask(
            "Select tag to edit",
            choices=[str(i) for i in range(1, len(tag_keys) + 1)] + ["b", "B"]
        )

        # Check for back navigation
        if choice_str.lower() == 'b':
            console.print("[yellow]Returning to main menu[/yellow]")
            return

        choice = int(choice_str)
        tag_key = tag_keys[choice - 1]
        console.print(f"\n[cyan]Editing tag: {tag_key}[/cyan]")

        # Show current rule
        rule = self.tag_rules[tag_key]
        console.print("\n[bold]Current configuration:[/bold]")
        console.print(Panel(rule.summary(), border_style="yellow"))

        # Offer to replace or cancel
        if Confirm.ask("\n[cyan]Replace this rule?[/cyan]", default=True):
            # Remove old rule
            del self.tag_rules[tag_key]
            # Add new rule (will ask all questions again)
            self.add_tag_rule_interactive()
        else:
            console.print("[yellow]Edit cancelled[/yellow]")

    def remove_tag_rule(self):
        """Remove a tag rule."""
        if not self.tag_rules:
            console.print("[yellow]No tag rules to remove[/yellow]")
            return

        console.print("\n[bold red]Remove Tag Rule[/bold red]")
        console.print("=" * 50)

        # Show available tags
        console.print("\n[cyan]Available tag keys:[/cyan]")
        tag_keys = list(self.tag_rules.keys())
        for idx, tag_key in enumerate(tag_keys, 1):
            console.print(f"[{idx}] {tag_key}")
        console.print("[B] Go back")

        choice_str = Prompt.ask(
            "Select tag to remove",
            choices=[str(i) for i in range(1, len(tag_keys) + 1)] + ["b", "B"]
        )

        # Check for back navigation
        if choice_str.lower() == 'b':
            console.print("[yellow]Returning to main menu[/yellow]")
            return

        choice = int(choice_str)
        tag_key = tag_keys[choice - 1]

        if Confirm.ask(f"\n[red]Remove tag '{tag_key}'?[/red]", default=False):
            del self.tag_rules[tag_key]
            console.print(f"[green]OK Tag '{tag_key}' removed[/green]")
        else:
            console.print("[yellow]Removal cancelled[/yellow]")

    def preview_policy(self):
        """Preview the generated policy JSON."""
        console.print("\n[bold cyan]Policy Preview[/bold cyan]")
        console.print("=" * 50)

        policy_json = self.to_json()
        syntax = Syntax(policy_json, "json", theme="monokai", line_numbers=True)
        console.print(syntax)

    def validate_policy(self) -> bool:
        """Validate the policy structure.

        Returns:
            True if policy is valid, False otherwise
        """
        console.print("\n[bold cyan]Validating Policy[/bold cyan]")
        console.print("=" * 50)

        errors = []

        # Check metadata
        if not self.policy_name:
            errors.append("Policy name is required")

        # Check tags
        if not self.tag_rules:
            errors.append("At least one tag rule is required")

        # Check each tag rule
        for tag_key, rule in self.tag_rules.items():
            if not rule.tag_key:
                errors.append(f"Tag '{tag_key}': tag_key is required")

            # Validate case enforcement if enabled
            if rule.enforce_case:
                if not rule.case_treatment:
                    errors.append(f"Tag '{tag_key}': case enforcement enabled but no case treatment specified")
                elif rule.case_treatment.lower() != tag_key.lower():
                    errors.append(f"Tag '{tag_key}': case treatment '{rule.case_treatment}' must match tag key (ignoring case)")

            if rule.enforcement_enabled and not rule.enforced_resources:
                errors.append(f"Tag '{tag_key}': enforcement enabled but no resources specified")

        if errors:
            console.print("[red]Validation failed:[/red]")
            for error in errors:
                console.print(f"  - {error}")
            return False
        else:
            console.print("[green]OK Policy is valid![/green]")
            return True

    def to_dict(self) -> Dict[str, Any]:
        """Convert the policy to dictionary format.

        Returns:
            Policy as dictionary
        """
        policy = {
            "tags": {}
        }

        for tag_key, rule in self.tag_rules.items():
            # Use the tag_key as the policy key in the JSON
            # If case enforcement is enabled, use lowercase version as policy key
            policy_key = tag_key.lower() if rule.enforce_case else tag_key
            policy["tags"][policy_key] = rule.to_dict()

        return policy

    def to_json(self, indent: int = 2) -> str:
        """Convert the policy to JSON string.

        Args:
            indent: Indentation level for JSON

        Returns:
            Policy as JSON string
        """
        return json.dumps(self.to_dict(), indent=indent)

    def show_main_menu(self):
        """Display the main menu."""
        console.print("\n[bold cyan]Main Menu[/bold cyan]")
        console.print("=" * 50)

        if self.policy_name:
            tag_count = len(self.tag_rules)
            console.print(f"Current Policy: [cyan]{self.policy_name}[/cyan] ({tag_count} tag(s) defined)\n")

        console.print("[1] Add new tag rule")
        console.print("[2] Edit existing tag rule")
        console.print("[3] Remove tag rule")
        console.print("[4] Preview policy JSON")
        console.print("[5] Validate policy")
        console.print("[6] Edit policy metadata (name and description)")
        console.print("[7] Save and create policy")
        console.print("[Q] Quit without saving")

    def run_interactive_loop(self):
        """Run the main interactive loop."""
        console.print("\n[bold green]Welcome to the Tag Policy Builder![/bold green]")
        console.print("=" * 50)

        # Collect metadata first (unless already set)
        if not self.metadata_set:
            self.collect_metadata()
        else:
            console.print(f"\n[dim]Using existing metadata:[/dim]")
            console.print(f"  Name: {self.policy_name}")
            console.print(f"  Description: {self.policy_description}")

        # Main menu loop
        while True:
            self.show_main_menu()

            choice = Prompt.ask(
                "\n[cyan]Choice[/cyan]",
                choices=["1", "2", "3", "4", "5", "6", "7", "q", "Q"],
                default="1"
            )

            if choice == "1":
                self.add_tag_rule_interactive()
            elif choice == "2":
                self.edit_tag_rule()
            elif choice == "3":
                self.remove_tag_rule()
            elif choice == "4":
                self.preview_policy()
            elif choice == "5":
                self.validate_policy()
            elif choice == "6":
                # Edit metadata
                self.collect_metadata()
            elif choice == "7":
                # Validate before proceeding
                if self.validate_policy():
                    break
                else:
                    console.print("\n[yellow]Fix validation errors before saving[/yellow]")
            elif choice.upper() == "Q":
                if Confirm.ask("\n[yellow]Quit without saving?[/yellow]", default=False):
                    console.print("[yellow]Exited without saving[/yellow]")
                    return None

        # Return the completed policy
        return {
            "name": self.policy_name,
            "description": self.policy_description,
            "content": self.to_dict()
        }
