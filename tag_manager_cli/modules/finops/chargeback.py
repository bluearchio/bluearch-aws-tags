"""
Chargeback Reporter - Tag-based cost allocation and reporting.

Generates cost reports grouped by tag dimensions for chargeback,
showback, and cost attribution workflows.
"""

import csv
import json
from dataclasses import dataclass, field
from datetime import date, datetime
from io import StringIO
from typing import Any, Dict, List, Optional

from rich.console import Console
from rich.table import Table

from .cur_client import CostDataSource, QueryResult

console = Console()


@dataclass
class ChargebackItem:
    """Individual chargeback line item."""
    period: str
    tag_value: str
    cost: float
    blended_cost: float = 0.0
    additional_dimensions: Dict[str, str] = field(default_factory=dict)
    resource_count: int = 0
    service_breakdown: Dict[str, float] = field(default_factory=dict)


@dataclass
class ChargebackReport:
    """Complete chargeback report."""
    tag_key: str
    start_date: date
    end_date: date
    granularity: str
    items: List[ChargebackItem]
    total_cost: float
    total_blended_cost: float = 0.0
    generated_at: datetime = field(default_factory=datetime.utcnow)
    source: str = 'cur'
    additional_group_by: List[str] = field(default_factory=list)

    @property
    def by_period(self) -> Dict[str, List[ChargebackItem]]:
        """Group items by period."""
        result = {}
        for item in self.items:
            if item.period not in result:
                result[item.period] = []
            result[item.period].append(item)
        return result

    @property
    def by_tag_value(self) -> Dict[str, List[ChargebackItem]]:
        """Group items by tag value."""
        result = {}
        for item in self.items:
            key = item.tag_value or '(untagged)'
            if key not in result:
                result[key] = []
            result[key].append(item)
        return result

    @property
    def totals_by_tag(self) -> Dict[str, float]:
        """Calculate total cost per tag value."""
        result = {}
        for item in self.items:
            key = item.tag_value or '(untagged)'
            result[key] = result.get(key, 0) + item.cost
        return dict(sorted(result.items(), key=lambda x: x[1], reverse=True))


class ChargebackReporter:
    """
    Generates tag-based chargeback reports from cost data.

    Supports:
    - Single and multi-tag grouping
    - Daily and monthly granularity
    - Multiple export formats (table, CSV, JSON)
    - Cost Explorer fallback when CUR unavailable
    """

    def __init__(self, data_source: CostDataSource):
        """Initialize reporter with a cost data source."""
        self.data_source = data_source

    def generate_report(
        self,
        tag_key: str,
        start_date: date,
        end_date: date,
        granularity: str = 'MONTHLY',
        group_by: Optional[List[str]] = None,
        tag_value: Optional[str] = None
    ) -> ChargebackReport:
        """
        Generate a chargeback report for a tag dimension.

        Args:
            tag_key: Primary tag key to group costs by
            start_date: Start of reporting period
            end_date: End of reporting period
            granularity: 'DAILY' or 'MONTHLY'
            group_by: Additional tag keys for multi-dimensional grouping
            tag_value: Optional filter to specific tag value

        Returns:
            ChargebackReport with all cost items
        """
        console.print(f"[blue]Generating chargeback report for {tag_key}...[/blue]")

        # Query cost data
        result = self.data_source.get_costs_by_tag(
            tag_key=tag_key,
            start_date=start_date,
            end_date=end_date,
            granularity=granularity,
            tag_value=tag_value,
            additional_group_by=group_by
        )

        # Transform to chargeback items
        items = []
        total_blended = 0.0

        for row in result.data:
            cost = float(row.get('cost', 0) or 0)
            blended = float(row.get('blended_cost', 0) or 0)

            # Extract additional dimensions
            additional = {}
            if group_by:
                for dim in group_by:
                    dim_key = dim.lower()
                    if dim_key in row:
                        additional[dim] = row[dim_key] or '(untagged)'

            item = ChargebackItem(
                period=row.get('period', 'Unknown'),
                tag_value=row.get('tag_value', '(untagged)') or '(untagged)',
                cost=cost,
                blended_cost=blended,
                additional_dimensions=additional
            )
            items.append(item)
            total_blended += blended

        report = ChargebackReport(
            tag_key=tag_key,
            start_date=start_date,
            end_date=end_date,
            granularity=granularity,
            items=items,
            total_cost=result.total_cost,
            total_blended_cost=total_blended,
            source=result.source,
            additional_group_by=group_by or []
        )

        console.print(f"[green][OK] Report generated: {len(items)} items, ${result.total_cost:,.2f} total[/green]")

        return report

    def display_table(self, report: ChargebackReport, show_all: bool = False) -> None:
        """
        Display report as a Rich table.

        Args:
            report: The chargeback report to display
            show_all: Show all rows (default limits to top 20)
        """
        title = f"Chargeback Report: {report.tag_key}"
        if report.additional_group_by:
            title += f" (grouped by {', '.join(report.additional_group_by)})"

        table = Table(title=title, show_header=True, header_style="bold cyan")

        # Build columns
        table.add_column("Period", style="dim")
        table.add_column(report.tag_key, style="white")

        for dim in report.additional_group_by:
            table.add_column(dim, style="white")

        table.add_column("Cost (USD)", style="green", justify="right")
        table.add_column("% of Total", style="cyan", justify="right")

        # Sort items by cost descending
        sorted_items = sorted(report.items, key=lambda x: x.cost, reverse=True)

        # Limit rows unless show_all
        display_items = sorted_items if show_all else sorted_items[:20]

        for item in display_items:
            row = [
                item.period,
                item.tag_value
            ]

            # Add additional dimensions
            for dim in report.additional_group_by:
                row.append(item.additional_dimensions.get(dim, '-'))

            # Add cost and percentage
            pct = (item.cost / report.total_cost * 100) if report.total_cost > 0 else 0
            row.extend([
                f"${item.cost:,.2f}",
                f"{pct:.1f}%"
            ])

            table.add_row(*row)

        # Add total row
        table.add_row(
            "TOTAL",
            "-",
            *["-" for _ in report.additional_group_by],
            f"${report.total_cost:,.2f}",
            "100.0%",
            style="bold"
        )

        console.print(table)

        if not show_all and len(sorted_items) > 20:
            console.print(f"[dim]Showing top 20 of {len(sorted_items)} items. Use --all to show all.[/dim]")

        # Show source info
        console.print(f"[dim]Data source: {report.source.upper()}[/dim]")

    def display_summary(self, report: ChargebackReport) -> None:
        """Display a summary table grouped by tag value."""
        table = Table(
            title=f"Cost Summary by {report.tag_key}",
            show_header=True,
            header_style="bold cyan"
        )

        table.add_column(report.tag_key, style="white")
        table.add_column("Total Cost (USD)", style="green", justify="right")
        table.add_column("% of Total", style="cyan", justify="right")

        for tag_value, cost in report.totals_by_tag.items():
            pct = (cost / report.total_cost * 100) if report.total_cost > 0 else 0
            table.add_row(
                tag_value,
                f"${cost:,.2f}",
                f"{pct:.1f}%"
            )

        table.add_row(
            "TOTAL",
            f"${report.total_cost:,.2f}",
            "100.0%",
            style="bold"
        )

        console.print(table)

    def export_csv(self, report: ChargebackReport, output_path: str = None) -> str:
        """
        Export report to CSV format.

        Args:
            report: The chargeback report to export
            output_path: Optional file path (returns string if None)

        Returns:
            CSV string if no output_path, otherwise writes to file
        """
        output = StringIO()
        writer = csv.writer(output)

        # Header
        header = ['Period', report.tag_key]
        header.extend(report.additional_group_by)
        header.extend(['Cost_USD', 'Blended_Cost_USD', 'Percent_of_Total'])
        writer.writerow(header)

        # Data rows
        for item in sorted(report.items, key=lambda x: (x.period, -x.cost)):
            row = [item.period, item.tag_value]

            for dim in report.additional_group_by:
                row.append(item.additional_dimensions.get(dim, ''))

            pct = (item.cost / report.total_cost * 100) if report.total_cost > 0 else 0
            row.extend([
                f"{item.cost:.2f}",
                f"{item.blended_cost:.2f}",
                f"{pct:.2f}"
            ])
            writer.writerow(row)

        # Total row
        total_row = ['TOTAL', 'ALL']
        total_row.extend(['ALL'] * len(report.additional_group_by))
        total_row.extend([f"{report.total_cost:.2f}", f"{report.total_blended_cost:.2f}", "100.00"])
        writer.writerow(total_row)

        csv_content = output.getvalue()

        if output_path:
            with open(output_path, 'w', newline='') as f:
                f.write(csv_content)
            console.print(f"[green][OK] Report exported to {output_path}[/green]")
            return output_path
        else:
            return csv_content

    def export_json(self, report: ChargebackReport, output_path: str = None) -> str:
        """
        Export report to JSON format.

        Args:
            report: The chargeback report to export
            output_path: Optional file path (returns string if None)

        Returns:
            JSON string if no output_path, otherwise writes to file
        """
        data = {
            "metadata": {
                "tag_key": report.tag_key,
                "start_date": report.start_date.isoformat(),
                "end_date": report.end_date.isoformat(),
                "granularity": report.granularity,
                "generated_at": report.generated_at.isoformat(),
                "source": report.source,
                "additional_dimensions": report.additional_group_by
            },
            "summary": {
                "total_cost": round(report.total_cost, 2),
                "total_blended_cost": round(report.total_blended_cost, 2),
                "item_count": len(report.items),
                "by_tag_value": {k: round(v, 2) for k, v in report.totals_by_tag.items()}
            },
            "items": [
                {
                    "period": item.period,
                    "tag_value": item.tag_value,
                    "cost": round(item.cost, 2),
                    "blended_cost": round(item.blended_cost, 2),
                    "additional_dimensions": item.additional_dimensions
                }
                for item in report.items
            ]
        }

        json_content = json.dumps(data, indent=2)

        if output_path:
            with open(output_path, 'w') as f:
                f.write(json_content)
            console.print(f"[green][OK] Report exported to {output_path}[/green]")
            return output_path
        else:
            return json_content
