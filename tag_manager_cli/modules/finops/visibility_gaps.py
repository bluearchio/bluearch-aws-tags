"""
Visibility Gaps Analyzer - Untagged resource cost analysis.

Identifies resources missing required tags and calculates the cost
impact, enabling data-driven tagging prioritization.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Set

from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from .cur_client import CostDataSource, QueryResult

console = Console()


@dataclass
class UntaggedResource:
    """A resource missing required tags."""
    resource_id: str
    service: str
    cost: float
    missing_tags: List[str]
    region: str = ''
    account_id: str = ''


@dataclass
class GapSummary:
    """Summary of tagging gaps by dimension."""
    dimension: str  # 'service', 'tag', 'account'
    value: str
    untagged_cost: float
    resource_count: int
    percentage_of_total: float = 0.0


@dataclass
class GapReport:
    """Complete visibility gap analysis report."""
    required_tags: List[str]
    start_date: date
    end_date: date
    total_untagged_cost: float
    total_cost: float
    untagged_percentage: float
    resources: List[UntaggedResource]
    by_service: List[GapSummary]
    by_missing_tag: List[GapSummary]
    generated_at: datetime = field(default_factory=datetime.utcnow)
    source: str = 'cur'
    tagging_roi: Optional['TaggingROI'] = None


@dataclass
class TaggingROI:
    """Return on investment analysis for tagging."""
    total_unattributed_cost: float
    estimated_tagging_effort_hours: float
    cost_per_resource: float
    high_value_resources: int  # Resources with cost > $10
    medium_value_resources: int  # Resources with cost $1-10
    low_value_resources: int  # Resources with cost < $1
    recommendation: str


class VisibilityGapAnalyzer:
    """
    Analyzes tagging gaps and their cost impact.

    Provides:
    - Identification of untagged resources
    - Cost attribution to missing tags
    - ROI analysis for tagging efforts
    - Prioritization recommendations
    """

    # Cost thresholds for ROI analysis
    HIGH_VALUE_THRESHOLD = 10.0
    MEDIUM_VALUE_THRESHOLD = 1.0

    # Estimated time per resource for tagging (in hours)
    EST_TIME_PER_RESOURCE = 0.1  # 6 minutes average

    def __init__(self, data_source: CostDataSource):
        """Initialize analyzer with a cost data source."""
        self.data_source = data_source

    def analyze_gaps(
        self,
        required_tags: List[str],
        start_date: date,
        end_date: date,
        min_cost: float = 0.01,
        services: Optional[List[str]] = None,
        calculate_roi: bool = True
    ) -> GapReport:
        """
        Analyze tagging gaps for required tags.

        Args:
            required_tags: List of tag keys that should be present
            start_date: Start of analysis period
            end_date: End of analysis period
            min_cost: Minimum cost to include in results
            services: Optional list of services to filter
            calculate_roi: Whether to calculate tagging ROI

        Returns:
            GapReport with analysis results
        """
        console.print(f"[blue]Analyzing tagging gaps for: {', '.join(required_tags)}...[/blue]")

        # Query untagged costs
        result = self.data_source.get_untagged_costs(
            required_tags=required_tags,
            start_date=start_date,
            end_date=end_date
        )

        # Transform results
        resources = []
        by_service: Dict[str, GapSummary] = {}
        by_tag: Dict[str, GapSummary] = {}

        for row in result.data:
            cost = float(row.get('cost', 0) or 0)
            if cost < min_cost:
                continue

            service = row.get('service', 'Unknown')
            resource_id = row.get('resource_id', 'Unknown')

            # Filter by services if specified
            if services and service not in services:
                continue

            # Determine which tags are missing (simplified - assumes all are missing)
            missing = row.get('missing_tag', None)
            missing_tags = [missing] if missing else required_tags

            resource = UntaggedResource(
                resource_id=resource_id,
                service=service,
                cost=cost,
                missing_tags=missing_tags
            )
            resources.append(resource)

            # Aggregate by service
            if service not in by_service:
                by_service[service] = GapSummary(
                    dimension='service',
                    value=service,
                    untagged_cost=0,
                    resource_count=0
                )
            by_service[service].untagged_cost += cost
            by_service[service].resource_count += 1

            # Aggregate by missing tag
            for tag in missing_tags:
                if tag not in by_tag:
                    by_tag[tag] = GapSummary(
                        dimension='tag',
                        value=tag,
                        untagged_cost=0,
                        resource_count=0
                    )
                by_tag[tag].untagged_cost += cost
                by_tag[tag].resource_count += 1

        # Get total cost for percentage calculation
        total_result = self.data_source.get_costs_by_service(start_date, end_date)
        total_cost = total_result.total_cost or 1  # Avoid division by zero

        # Calculate percentages
        untagged_cost = result.total_cost
        untagged_pct = (untagged_cost / total_cost * 100) if total_cost > 0 else 0

        for summary in by_service.values():
            summary.percentage_of_total = (summary.untagged_cost / total_cost * 100) if total_cost > 0 else 0

        for summary in by_tag.values():
            summary.percentage_of_total = (summary.untagged_cost / total_cost * 100) if total_cost > 0 else 0

        # Sort summaries by cost
        service_summaries = sorted(by_service.values(), key=lambda x: x.untagged_cost, reverse=True)
        tag_summaries = sorted(by_tag.values(), key=lambda x: x.untagged_cost, reverse=True)

        # Calculate ROI if requested
        tagging_roi = None
        if calculate_roi:
            tagging_roi = self._calculate_roi(resources, untagged_cost)

        report = GapReport(
            required_tags=required_tags,
            start_date=start_date,
            end_date=end_date,
            total_untagged_cost=untagged_cost,
            total_cost=total_cost,
            untagged_percentage=untagged_pct,
            resources=resources,
            by_service=service_summaries,
            by_missing_tag=tag_summaries,
            source=result.source,
            tagging_roi=tagging_roi
        )

        console.print(f"[green][OK] Analysis complete: {len(resources)} untagged resources[/green]")
        console.print(f"[green]    ${untagged_cost:,.2f} ({untagged_pct:.1f}%) not attributable[/green]")

        return report

    def _calculate_roi(self, resources: List[UntaggedResource], total_untagged: float) -> TaggingROI:
        """Calculate ROI for tagging untagged resources."""
        high_value = sum(1 for r in resources if r.cost >= self.HIGH_VALUE_THRESHOLD)
        medium_value = sum(1 for r in resources if self.MEDIUM_VALUE_THRESHOLD <= r.cost < self.HIGH_VALUE_THRESHOLD)
        low_value = sum(1 for r in resources if r.cost < self.MEDIUM_VALUE_THRESHOLD)

        total_resources = len(resources)
        est_hours = total_resources * self.EST_TIME_PER_RESOURCE
        cost_per_resource = total_untagged / total_resources if total_resources > 0 else 0

        # Generate recommendation
        if high_value > 10 and total_untagged > 1000:
            recommendation = "HIGH PRIORITY: Significant cost visibility gap. Focus on high-value resources first."
        elif high_value > 0 or total_untagged > 500:
            recommendation = "MEDIUM PRIORITY: Notable unattributed costs. Implement tagging for top resources."
        else:
            recommendation = "LOW PRIORITY: Minimal impact. Consider automated tagging rules."

        return TaggingROI(
            total_unattributed_cost=total_untagged,
            estimated_tagging_effort_hours=est_hours,
            cost_per_resource=cost_per_resource,
            high_value_resources=high_value,
            medium_value_resources=medium_value,
            low_value_resources=low_value,
            recommendation=recommendation
        )

    def display_report(self, report: GapReport, show_resources: bool = False) -> None:
        """Display the gap analysis report."""
        # Summary panel
        summary = f"""
[bold]Tagging Gap Analysis Summary[/bold]

Required Tags: {', '.join(report.required_tags)}
Period: {report.start_date} to {report.end_date}
Data Source: {report.source.upper()}

[bold cyan]Cost Impact:[/bold cyan]
  Total Spend: ${report.total_cost:,.2f}
  Untagged Cost: ${report.total_untagged_cost:,.2f}
  Visibility Gap: {report.untagged_percentage:.1f}%
  Resources Affected: {len(report.resources)}
"""
        console.print(Panel(summary, title="Visibility Gap Report", border_style="blue"))

        # By Service table
        if report.by_service:
            table = Table(title="Untagged Costs by Service", show_header=True, header_style="bold cyan")
            table.add_column("Service", style="white")
            table.add_column("Untagged Cost", style="red", justify="right")
            table.add_column("Resources", style="dim", justify="right")
            table.add_column("% of Total", style="cyan", justify="right")

            for summary in report.by_service[:10]:
                table.add_row(
                    summary.value,
                    f"${summary.untagged_cost:,.2f}",
                    str(summary.resource_count),
                    f"{summary.percentage_of_total:.1f}%"
                )

            console.print(table)

        # By Missing Tag table
        if report.by_missing_tag:
            table = Table(title="Cost Impact by Missing Tag", show_header=True, header_style="bold cyan")
            table.add_column("Missing Tag", style="white")
            table.add_column("Unattributed Cost", style="red", justify="right")
            table.add_column("Resources", style="dim", justify="right")

            for summary in report.by_missing_tag:
                table.add_row(
                    summary.value,
                    f"${summary.untagged_cost:,.2f}",
                    str(summary.resource_count)
                )

            console.print(table)

        # ROI Analysis
        if report.tagging_roi:
            self.display_roi(report.tagging_roi)

        # Individual resources (if requested)
        if show_resources and report.resources:
            table = Table(title="Top Untagged Resources by Cost", show_header=True, header_style="bold cyan")
            table.add_column("Resource ID", style="dim", max_width=50)
            table.add_column("Service", style="white")
            table.add_column("Cost", style="red", justify="right")
            table.add_column("Missing Tags", style="yellow")

            sorted_resources = sorted(report.resources, key=lambda x: x.cost, reverse=True)
            for resource in sorted_resources[:20]:
                table.add_row(
                    resource.resource_id[:50],
                    resource.service,
                    f"${resource.cost:,.2f}",
                    ', '.join(resource.missing_tags)
                )

            console.print(table)

            if len(report.resources) > 20:
                console.print(f"[dim]Showing top 20 of {len(report.resources)} resources[/dim]")

    def display_roi(self, roi: TaggingROI) -> None:
        """Display ROI analysis for tagging effort."""
        roi_text = f"""
[bold]Tagging ROI Analysis[/bold]

[bold cyan]Unattributed Cost:[/bold cyan] ${roi.total_unattributed_cost:,.2f}

[bold cyan]Resource Breakdown:[/bold cyan]
  High Value (>$10):  {roi.high_value_resources} resources
  Medium ($1-10):     {roi.medium_value_resources} resources
  Low (<$1):          {roi.low_value_resources} resources

[bold cyan]Effort Estimate:[/bold cyan]
  Resources to Tag: {roi.high_value_resources + roi.medium_value_resources + roi.low_value_resources}
  Estimated Time: {roi.estimated_tagging_effort_hours:.1f} hours
  Avg Cost/Resource: ${roi.cost_per_resource:.2f}

[bold yellow]Recommendation:[/bold yellow]
{roi.recommendation}
"""
        console.print(Panel(roi_text, title="Tagging Return on Investment", border_style="green"))

    def get_prioritized_resources(
        self,
        report: GapReport,
        limit: int = 50
    ) -> List[UntaggedResource]:
        """
        Get prioritized list of resources to tag.

        Prioritizes by cost (highest first) for maximum impact.
        """
        return sorted(report.resources, key=lambda x: x.cost, reverse=True)[:limit]
