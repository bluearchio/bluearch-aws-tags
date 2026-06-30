"""Resource Organization module."""

from rich.console import Console
from rich.table import Table
from rich.prompt import Prompt, Confirm
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.panel import Panel
from rich.tree import Tree
from typing import Dict, List, Optional, Tuple, DefaultDict
from collections import defaultdict
from botocore.exceptions import ClientError
import re

from ..utils.aws_auth import aws_auth

console = Console()


def get_all_resources_with_pagination() -> Dict:
    """Get all resources with full pagination support."""
    try:
        client = aws_auth.get_client('resourcegroupstaggingapi')
        all_resources = []
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            transient=True
        ) as progress:
            task = progress.add_task("Discovering AWS resources...", total=None)
            
            paginator = client.get_paginator('get_resources')
            page_count = 0
            
            for page in paginator.paginate(
                ResourcesPerPage=100,
                PaginationConfig={'PageSize': 100}
            ):
                page_count += 1
                resources = page.get('ResourceTagMappingList', [])
                all_resources.extend(resources)
                
                progress.update(
                    task, 
                    description=f"Discovered {len(all_resources)} resources across {page_count} pages..."
                )
        
        return {'ResourceTagMappingList': all_resources}
        
    except ClientError as e:
        console.print(f"[red]AWS API Error: {e}[/red]")
        return {}


def get_resources_by_tag(tag_key: str, tag_value: str = None) -> Dict:
    """Get resources filtered by tag using Resource Groups Tagging API."""
    try:
        client = aws_auth.get_client('resourcegroupstaggingapi')
        
        tag_filters = [{'Key': tag_key}]
        if tag_value:
            tag_filters[0]['Values'] = [tag_value]
        
        all_resources = []
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            transient=True
        ) as progress:
            task = progress.add_task(f"Searching for resources with tag {tag_key}...", total=None)
            
            paginator = client.get_paginator('get_resources')
            
            for page in paginator.paginate(
                TagFilters=tag_filters,
                ResourcesPerPage=100,
                PaginationConfig={'PageSize': 100}
            ):
                resources = page.get('ResourceTagMappingList', [])
                all_resources.extend(resources)
                
                progress.update(
                    task,
                    description=f"Found {len(all_resources)} matching resources..."
                )
        
        response = {'ResourceTagMappingList': all_resources}
        
        return response
        
    except ClientError as e:
        console.print(f"[red]AWS API Error: {e}[/red]")
        return {}


def get_untagged_resources() -> Dict:
    """Get resources that have no tags."""
    try:
        client = aws_auth.get_client('resourcegroupstaggingapi')
        all_resources = []
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            transient=True
        ) as progress:
            task = progress.add_task("Finding untagged resources...", total=None)
            
            paginator = client.get_paginator('get_resources')
            
            for page in paginator.paginate(
                TagFilters=[],
                ResourcesPerPage=100,
                PaginationConfig={'PageSize': 100}
            ):
                resources = page.get('ResourceTagMappingList', [])
                all_resources.extend(resources)
                
                progress.update(
                    task,
                    description=f"Scanning {len(all_resources)} resources..."
                )
        
        # Filter resources with no tags
        untagged = {
            'ResourceTagMappingList': [
                resource for resource in all_resources
                if not resource.get('Tags', [])
            ]
        }
        
        return untagged
        
    except ClientError as e:
        console.print(f"[red]AWS API Error: {e}[/red]")
        return {}


def extract_resource_info(arn: str) -> Tuple[str, str, str]:
    """Extract service, resource type, and short name from ARN."""
    if not arn or arn == 'Unknown':
        return 'Unknown', 'Unknown', 'Unknown'
    
    arn_parts = arn.split(':')
    if len(arn_parts) < 6:
        return 'Unknown', 'Unknown', 'Unknown'
    
    service = arn_parts[2]
    
    # Handle different ARN formats
    if service == 's3':
        # S3 buckets: arn:aws:s3:::bucket-name
        resource_part = arn_parts[5] if len(arn_parts) > 5 else ''
        return service, 'bucket', resource_part if resource_part else 'Unknown'
    elif len(arn_parts) >= 7:
        # Format: arn:aws:service:region:account:resource-type:resource-name
        resource_type = arn_parts[5]
        resource_name = arn_parts[6]
    else:
        # Format: arn:aws:service:region:account:resource-type/resource-name
        resource_part = arn_parts[5] if len(arn_parts) > 5 else ''
        if '/' in resource_part:
            resource_type, resource_name = resource_part.split('/', 1)
        elif ':' in resource_part:
            resource_type, resource_name = resource_part.split(':', 1)
        else:
            resource_type = resource_part if resource_part else 'Unknown'
            resource_name = resource_part if resource_part else 'Unknown'
    
    # Shorten long resource names
    if len(resource_name) > 30:
        resource_name = resource_name[:27] + '...'
    
    return service, resource_type, resource_name


def group_resources_by_tag(resources_data: Dict, group_by_tag: str) -> DefaultDict[str, List[Dict]]:
    """Group resources by a specific tag value."""
    grouped = defaultdict(list)
    
    for resource in resources_data.get('ResourceTagMappingList', []):
        tags = {tag['Key']: tag['Value'] for tag in resource.get('Tags', [])}
        
        group_value = tags.get(group_by_tag, 'Untagged')
        grouped[group_value].append(resource)
    
    return grouped


def display_grouped_resources(grouped_resources: DefaultDict[str, List[Dict]], group_by_tag: str):
    """Display resources grouped by tag in a tree structure."""
    tree = Tree(f"Resources grouped by [bold cyan]{group_by_tag}[/bold cyan]")
    
    # Sort groups by name, with 'Untagged' last
    sorted_groups = sorted(grouped_resources.keys(), key=lambda x: (x == 'Untagged', x))
    
    total_resources = 0
    for group_name in sorted_groups:
        resources = grouped_resources[group_name]
        total_resources += len(resources)
        
        # Create group node with count
        group_style = "red" if group_name == 'Untagged' else "green"
        group_node = tree.add(f"[{group_style}]{group_name}[/{group_style}] ({len(resources)} resources)")
        
        # Add resources to group
        for resource in resources[:10]:  # Limit to first 10 for readability
            arn = resource.get('ResourceARN', 'Unknown')
            service, resource_type, resource_name = extract_resource_info(arn)
            
            tags = resource.get('Tags', [])
            tag_count = len(tags)
            
            resource_display = f"[cyan]{service}[/cyan] {resource_type}: {resource_name}"
            if tag_count > 1:
                resource_display += f" [dim]({tag_count} tags)[/dim]"
            
            group_node.add(resource_display)
        
        # Show if there are more resources
        if len(resources) > 10:
            group_node.add(f"[dim]... and {len(resources) - 10} more resources[/dim]")
    
    console.print(tree)
    console.print(f"\n[blue]Total: {total_resources} resources across {len(grouped_resources)} groups[/blue]")


def display_resources_table(resources_data: Dict, title: str, show_detailed: bool = False):
    """Display resources in a formatted table."""
    table = Table(title=title, show_header=True, header_style="bold magenta")
    
    if show_detailed:
        table.add_column("Service", style="cyan", width=12)
        table.add_column("Resource Type", style="white", width=15)
        table.add_column("Resource Name", style="yellow", width=25)
        table.add_column("Tags", style="green")
    else:
        table.add_column("Resource ARN", style="cyan", max_width=60)
        table.add_column("Resource Type", style="white")
        table.add_column("Tags", style="green", max_width=40)
    
    if 'ResourceTagMappingList' in resources_data:
        for resource in resources_data['ResourceTagMappingList']:
            arn = resource.get('ResourceARN', 'Unknown')
            service, resource_type, resource_name = extract_resource_info(arn)
            
            # Format tags
            tags = resource.get('Tags', [])
            tag_str = ', '.join([f"{tag['Key']}={tag['Value']}" for tag in tags[:3]])
            if len(tags) > 3:
                tag_str += f" (+{len(tags)-3} more)"
            
            if show_detailed:
                table.add_row(service, resource_type, resource_name, tag_str or "No tags")
            else:
                table.add_row(arn, f"{service} {resource_type}", tag_str or "No tags")
    
    console.print(table)
    
    # Show summary
    total_resources = len(resources_data.get('ResourceTagMappingList', []))
    console.print(f"\n[blue]Total resources found: {total_resources}[/blue]")


def tag_resource(resource_arn: str, tags: Dict[str, str]):
    """Apply tags to a specific resource."""
    try:
        client = aws_auth.get_client('resourcegroupstaggingapi')
        
        tag_list = [{'Key': k, 'Value': v} for k, v in tags.items()]
        
        response = client.tag_resources(
            ResourceARNList=[resource_arn],
            Tags=tag_list
        )
        
        if response.get('FailedResourcesMap'):
            console.print(f"[red]Failed to tag resource: {response['FailedResourcesMap']}[/red]")
            return False
        else:
            console.print(f"[green]OK Successfully tagged resource[/green]")
            return True
            
    except ClientError as e:
        console.print(f"[red]AWS API Error: {e}[/red]")
        return False


def get_common_tag_keys(resources_data: Dict) -> List[str]:
    """Get most common tag keys across all resources."""
    tag_frequency = defaultdict(int)
    
    for resource in resources_data.get('ResourceTagMappingList', []):
        for tag in resource.get('Tags', []):
            tag_frequency[tag['Key']] += 1
    
    # Return top 10 most common tags
    return [tag for tag, _ in sorted(tag_frequency.items(), key=lambda x: x[1], reverse=True)[:10]]


def run_dynamic_grouping_menu():
    """Interactive menu for dynamic resource grouping."""
    console.print("\n[bold blue]Dynamic Resource Grouping[/bold blue]")
    console.print("Group resources by common tags for inventory purposes\n")
    
    # Get all resources first
    console.print("[blue]Loading all AWS resources...[/blue]")
    all_resources = get_all_resources_with_pagination()
    
    if not all_resources.get('ResourceTagMappingList'):
        console.print("[yellow]No resources found or unable to fetch resources.[/yellow]")
        return
    
    # Get common tag keys
    common_tags = get_common_tag_keys(all_resources)
    
    if not common_tags:
        console.print("[yellow]No common tags found across resources.[/yellow]")
        return
    
    console.print("[green]Most common tag keys found:[/green]")
    for i, tag_key in enumerate(common_tags, 1):
        console.print(f"  {i}. {tag_key}")
    
    # Let user choose grouping tag
    choice_options = [str(i) for i in range(1, len(common_tags) + 1)] + ["c", "b"]
    
    console.print("\n[cyan]Options:[/cyan]")
    console.print("  [1-10] - Group by corresponding tag")
    console.print("  c - Enter custom tag key")
    console.print("  b - Back to previous menu")
    
    choice = Prompt.ask("Select grouping option", choices=choice_options, default="b")
    
    if choice == "b":
        return
    elif choice == "c":
        group_by_tag = Prompt.ask("Enter custom tag key")
    else:
        group_by_tag = common_tags[int(choice) - 1]
    
    # Group resources and display
    console.print(f"\n[blue]Grouping resources by tag: {group_by_tag}[/blue]")
    grouped_resources = group_resources_by_tag(all_resources, group_by_tag)
    
    if not grouped_resources:
        console.print(f"[yellow]No resources found with tag '{group_by_tag}'.[/yellow]")
        return
    
    display_grouped_resources(grouped_resources, group_by_tag)
    
    # Ask if user wants to see details of a specific group
    if Confirm.ask("\nWould you like to see details of a specific group?"):
        group_names = list(grouped_resources.keys())
        console.print("\nAvailable groups:")
        for i, group_name in enumerate(group_names, 1):
            console.print(f"  {i}. {group_name} ({len(grouped_resources[group_name])} resources)")
        
        try:
            group_choice = int(Prompt.ask("Enter group number", default="1")) - 1
            if 0 <= group_choice < len(group_names):
                selected_group = group_names[group_choice]
                group_resources = {'ResourceTagMappingList': grouped_resources[selected_group]}
                display_resources_table(group_resources, f"Resources in group: {selected_group}", show_detailed=True)
        except (ValueError, IndexError):
            console.print("[red]Invalid group selection.[/red]")


def run_resource_inventory_menu():
    """Interactive menu for comprehensive resource inventory."""
    console.print("\n[bold blue]Resource Inventory & Analysis[/bold blue]")
    console.print("Comprehensive inventory and analysis of AWS resources\n")
    
    options = [
        ("1", "Complete resource inventory"),
        ("2", "Resources by service type"),
        ("3", "Tag coverage analysis"),
        ("4", "Resource naming patterns"),
        ("b", "Back to previous menu")
    ]
    
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Option", width=8)
    table.add_column("Description")
    
    for option, description in options:
        table.add_row(option, description)
    
    console.print(table)
    
    choice = Prompt.ask("\nSelect an option", choices=[opt[0] for opt in options], default="b")
    
    if choice == "b":
        return
    
    # Get all resources
    console.print("[blue]Loading complete resource inventory...[/blue]")
    all_resources = get_all_resources_with_pagination()
    
    if not all_resources.get('ResourceTagMappingList'):
        console.print("[yellow]No resources found or unable to fetch resources.[/yellow]")
        return
    
    if choice == "1":
        display_resources_table(all_resources, "Complete AWS Resource Inventory", show_detailed=True)
    
    elif choice == "2":
        # Group by service
        service_groups = defaultdict(list)
        for resource in all_resources['ResourceTagMappingList']:
            arn = resource.get('ResourceARN', '')
            service, _, _ = extract_resource_info(arn)
            service_groups[service].append(resource)
        
        console.print("\n[green]Resources by AWS Service:[/green]")
        for service, resources in sorted(service_groups.items()):
            console.print(f"  {service}: {len(resources)} resources")
        
        if Confirm.ask("\nWould you like to see details for a specific service?"):
            service_name = Prompt.ask("Enter service name")
            if service_name in service_groups:
                service_resources = {'ResourceTagMappingList': service_groups[service_name]}
                display_resources_table(service_resources, f"{service_name} Resources", show_detailed=True)
    
    elif choice == "3":
        # Tag coverage analysis
        total_resources = len(all_resources['ResourceTagMappingList'])
        tagged_resources = len([r for r in all_resources['ResourceTagMappingList'] if r.get('Tags')])
        coverage_percent = (tagged_resources / total_resources * 100) if total_resources > 0 else 0
        
        console.print(Panel(
            f"Tag Coverage Analysis\n\n"
            f"Total Resources: {total_resources}\n"
            f"Tagged Resources: {tagged_resources}\n"
            f"Untagged Resources: {total_resources - tagged_resources}\n"
            f"Coverage: {coverage_percent:.1f}%",
            title="Tag Coverage Report",
            border_style="blue"
        ))
        
        # Show most common tags
        common_tags = get_common_tag_keys(all_resources)
        if common_tags:
            console.print("\n[green]Most Common Tag Keys:[/green]")
            for tag in common_tags:
                count = sum(1 for r in all_resources['ResourceTagMappingList'] 
                          for t in r.get('Tags', []) if t['Key'] == tag)
                console.print(f"  {tag}: {count} resources")
    
    elif choice == "4":
        # Resource naming patterns
        console.print("[yellow]Resource naming pattern analysis coming soon![/yellow]")


def run_resource_organization():
    """Main function for Resource Organization."""
    console.print("\n[bold blue]Resource Organization[/bold blue]")
    console.print("Organize and categorize AWS resources using tags\n")
    
    # Menu options
    options = [
        ("1", "Find resources by tag"),
        ("2", "List untagged resources"),
        ("3", "Tag a specific resource"),
        ("4", "Dynamic resource grouping"),
        ("5", "Resource inventory & analysis"),
        ("b", "Back to main menu")
    ]
    
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Option", width=8)
    table.add_column("Description")
    
    for option, description in options:
        table.add_row(option, description)
    
    console.print(table)
    
    choice = Prompt.ask("\nSelect an option", choices=[opt[0] for opt in options], default="b")
    
    if choice == "1":
        tag_key = Prompt.ask("Enter tag key to search for")
        tag_value = Prompt.ask("Enter tag value (or press Enter for any value)", default="")
        
        console.print(f"[blue]Searching for resources with tag {tag_key}{'=' + tag_value if tag_value else ''}...[/blue]")
        
        resources = get_resources_by_tag(tag_key, tag_value if tag_value else None)
        if resources:
            title = f"Resources with tag {tag_key}" + (f"={tag_value}" if tag_value else "")
            display_resources_table(resources, title)
        
    elif choice == "2":
        console.print("[blue]Finding untagged resources...[/blue]")
        
        untagged = get_untagged_resources()
        if untagged:
            display_resources_table(untagged, "Untagged Resources")
        
    elif choice == "3":
        resource_arn = Prompt.ask("Enter resource ARN")
        
        console.print("Enter tags to apply (press Enter with empty key to finish):")
        tags = {}
        while True:
            key = Prompt.ask("Tag key", default="")
            if not key:
                break
            value = Prompt.ask(f"Value for '{key}'")
            tags[key] = value
        
        if tags:
            tag_resource(resource_arn, tags)
        else:
            console.print("[yellow]No tags provided.[/yellow]")
        
    elif choice == "4":
        run_dynamic_grouping_menu()
        
    elif choice == "5":
        run_resource_inventory_menu()
    
    # Pause before returning to main menu
    if choice != "b":
        Prompt.ask("\nPress Enter to continue...")


if __name__ == "__main__":
    run_resource_organization()