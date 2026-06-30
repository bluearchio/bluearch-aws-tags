"""
Cost Trends Analyzer - Historical cost trend analysis by tag.

Provides trend visualization and period-over-period comparisons
for tag-based cost analysis.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from .cur_client import CostDataSource, QueryResult

console = Console()


@dataclass
class PeriodCost:
    """Cost data for a single period."""
    period: str
    start_date: date
    end_date: date
    cost: float
    previous_cost: Optional[float] = None
    change_absolute: Optional[float] = None
    change_percent: Optional[float] = None


@dataclass
class TagTrend:
    """Trend data for a single tag value."""
    tag_value: str
    periods: List[PeriodCost]
    total_cost: float
    average_cost: float
    trend_direction: str  # 'increasing', 'decreasing', 'stable'
    trend_percent: float  # Overall trend percentage


@dataclass
class TrendReport:
    """Complete trend analysis report."""
    tag_key: str
    tag_value: Optional[str]
    granularity: str
    period_count: int
    trends: List[TagTrend]
    total_cost: float
    generated_at: datetime = field(default_factory=datetime.utcnow)
    source: str = 'cur'


class TrendAnalyzer:
    """
    Analyzes cost trends by tag dimension over time.

    Provides:
    - Period-over-period comparison
    - Trend direction analysis
    - Visual trend representation
    """

    def __init__(self, data_source: CostDataSource):
        """Initialize analyzer with a cost data source."""
        self.data_source = data_source

    def analyze_trends(
        self,
        tag_key: str,
        periods: int = 6,
        granularity: str = 'MONTHLY',
        tag_value: Optional[str] = None
    ) -> TrendReport:
        """
        Analyze cost trends for a tag dimension.

        Args:
            tag_key: Tag key to analyze
            periods: Number of periods to include
            granularity: 'MONTHLY' or 'WEEKLY'
            tag_value: Optional specific tag value

        Returns:
            TrendReport with trend analysis
        """
        console.print(f"[blue]Analyzing trends for {tag_key} ({periods} periods)...[/blue]")

        # Calculate date range
        end_date = date.today()
        if granularity == 'MONTHLY':
            start_date = end_date - timedelta(days=periods * 31)
        else:
            start_date = end_date - timedelta(weeks=periods)

        # Query data
        result = self.data_source.get_costs_by_tag(
            tag_key=tag_key,
            start_date=start_date,
            end_date=end_date,
            granularity=granularity,
            tag_value=tag_value
        )

        # Organize by tag value and period
        by_tag: Dict[str, Dict[str, float]] = {}

        for row in result.data:
            tv = row.get('tag_value', '(untagged)') or '(untagged)'
            period = row.get('period', '')
            cost = float(row.get('cost', 0) or 0)

            if tv not in by_tag:
                by_tag[tv] = {}
            by_tag[tv][period] = cost

        # Build trends
        trends = []

        for tv, period_data in by_tag.items():
            # Sort periods
            sorted_periods = sorted(period_data.keys())

            period_costs = []
            prev_cost = None

            for period in sorted_periods:
                cost = period_data[period]

                change_abs = None
                change_pct = None
                if prev_cost is not None:
                    change_abs = cost - prev_cost
                    change_pct = (change_abs / prev_cost * 100) if prev_cost > 0 else 0

                period_costs.append(PeriodCost(
                    period=period,
                    start_date=self._parse_period_date(period),
                    end_date=self._parse_period_date(period) + timedelta(days=30),
                    cost=cost,
                    previous_cost=prev_cost,
                    change_absolute=change_abs,
                    change_percent=change_pct
                ))
                prev_cost = cost

            if not period_costs:
                continue

            # Calculate overall trend
            total = sum(p.cost for p in period_costs)
            average = total / len(period_costs)

            # Trend direction based on first vs last period
            if len(period_costs) >= 2:
                first_cost = period_costs[0].cost
                last_cost = period_costs[-1].cost

                if first_cost > 0:
                    overall_change = ((last_cost - first_cost) / first_cost) * 100
                else:
                    overall_change = 100 if last_cost > 0 else 0

                if overall_change > 10:
                    direction = 'increasing'
                elif overall_change < -10:
                    direction = 'decreasing'
                else:
                    direction = 'stable'
            else:
                overall_change = 0
                direction = 'stable'

            trends.append(TagTrend(
                tag_value=tv,
                periods=period_costs,
                total_cost=total,
                average_cost=average,
                trend_direction=direction,
                trend_percent=overall_change
            ))

        # Sort by total cost
        trends.sort(key=lambda x: x.total_cost, reverse=True)

        report = TrendReport(
            tag_key=tag_key,
            tag_value=tag_value,
            granularity=granularity,
            period_count=periods,
            trends=trends,
            total_cost=result.total_cost,
            source=result.source
        )

        console.print(f"[green][OK] Analyzed trends for {len(trends)} tag values[/green]")

        return report

    def _parse_period_date(self, period: str) -> date:
        """Parse period string to date."""
        try:
            return datetime.strptime(period, '%Y-%m-%d').date()
        except ValueError:
            try:
                return datetime.strptime(period, '%Y-%m').date()
            except ValueError:
                return date.today()

    def display_trends(self, report: TrendReport, show_all: bool = False) -> None:
        """Display trend report in tables."""
        # Summary
        title = f"Cost Trends: {report.tag_key}"
        if report.tag_value:
            title += f" = {report.tag_value}"

        console.print(Panel(
            f"[bold]{title}[/bold]\n\n"
            f"Granularity: {report.granularity}\n"
            f"Periods: {report.period_count}\n"
            f"Total Cost: ${report.total_cost:,.2f}\n"
            f"Data Source: {report.source.upper()}",
            border_style="blue"
        ))

        # Trend summary table
        table = Table(
            title="Trend Summary by Tag Value",
            show_header=True,
            header_style="bold cyan"
        )

        table.add_column("Tag Value", style="white", max_width=30)
        table.add_column("Total Cost", style="green", justify="right")
        table.add_column("Avg/Period", style="dim", justify="right")
        table.add_column("Trend", style="cyan")
        table.add_column("Change", style="yellow", justify="right")
        table.add_column("Visual", style="dim")

        display_trends = report.trends if show_all else report.trends[:10]

        for trend in display_trends:
            # Trend indicator
            if trend.trend_direction == 'increasing':
                trend_text = "[red]Increasing[/red]"
                arrow = self._generate_trend_visual(trend, 'up')
            elif trend.trend_direction == 'decreasing':
                trend_text = "[green]Decreasing[/green]"
                arrow = self._generate_trend_visual(trend, 'down')
            else:
                trend_text = "[dim]Stable[/dim]"
                arrow = self._generate_trend_visual(trend, 'stable')

            change_str = f"{trend.trend_percent:+.1f}%"

            table.add_row(
                trend.tag_value[:30],
                f"${trend.total_cost:,.2f}",
                f"${trend.average_cost:,.2f}",
                trend_text,
                change_str,
                arrow
            )

        console.print(table)

        if not show_all and len(report.trends) > 10:
            console.print(f"[dim]Showing top 10 of {len(report.trends)} tag values. Use --all to show all.[/dim]")

    def display_detailed_trend(self, trend: TagTrend) -> None:
        """Display detailed period-by-period trend for a single tag value."""
        console.print(f"\n[bold]Detailed Trend: {trend.tag_value}[/bold]\n")

        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("Period", style="dim")
        table.add_column("Cost", style="green", justify="right")
        table.add_column("vs Previous", style="yellow", justify="right")
        table.add_column("% Change", style="cyan", justify="right")
        table.add_column("Bar", style="white")

        max_cost = max(p.cost for p in trend.periods) if trend.periods else 1

        for period in trend.periods:
            # Change indicators
            if period.change_absolute is not None:
                change_str = f"${period.change_absolute:+,.2f}"
                pct_str = f"{period.change_percent:+.1f}%"
            else:
                change_str = "-"
                pct_str = "-"

            # Visual bar
            bar_width = int((period.cost / max_cost) * 20) if max_cost > 0 else 0
            bar = "[" + "=" * bar_width + " " * (20 - bar_width) + "]"

            table.add_row(
                period.period,
                f"${period.cost:,.2f}",
                change_str,
                pct_str,
                bar
            )

        console.print(table)

        # Summary
        console.print(f"\n[bold]Summary:[/bold]")
        console.print(f"  Total: ${trend.total_cost:,.2f}")
        console.print(f"  Average: ${trend.average_cost:,.2f}")
        console.print(f"  Trend: {trend.trend_direction.upper()} ({trend.trend_percent:+.1f}%)")

    def _generate_trend_visual(self, trend: TagTrend, direction: str) -> str:
        """Generate ASCII visual for trend direction."""
        if len(trend.periods) < 2:
            return "----"

        # Simple sparkline-like representation
        costs = [p.cost for p in trend.periods[-6:]]  # Last 6 periods
        max_cost = max(costs) if costs else 1
        min_cost = min(costs) if costs else 0

        chars = []
        levels = " _.-~^"  # 6 levels

        for cost in costs:
            if max_cost == min_cost:
                level = 3
            else:
                level = int((cost - min_cost) / (max_cost - min_cost) * 5)
            chars.append(levels[level])

        return ''.join(chars)

    def compare_periods(
        self,
        tag_key: str,
        period1_start: date,
        period1_end: date,
        period2_start: date,
        period2_end: date
    ) -> Dict[str, Dict[str, Any]]:
        """
        Compare costs between two specific periods.

        Returns comparison data for each tag value.
        """
        # Get data for both periods
        result1 = self.data_source.get_costs_by_tag(
            tag_key=tag_key,
            start_date=period1_start,
            end_date=period1_end,
            granularity='MONTHLY'
        )

        result2 = self.data_source.get_costs_by_tag(
            tag_key=tag_key,
            start_date=period2_start,
            end_date=period2_end,
            granularity='MONTHLY'
        )

        # Aggregate by tag value
        costs1: Dict[str, float] = {}
        costs2: Dict[str, float] = {}

        for row in result1.data:
            tv = row.get('tag_value', '(untagged)') or '(untagged)'
            costs1[tv] = costs1.get(tv, 0) + float(row.get('cost', 0) or 0)

        for row in result2.data:
            tv = row.get('tag_value', '(untagged)') or '(untagged)'
            costs2[tv] = costs2.get(tv, 0) + float(row.get('cost', 0) or 0)

        # Build comparison
        all_tags = set(costs1.keys()) | set(costs2.keys())
        comparison = {}

        for tv in all_tags:
            c1 = costs1.get(tv, 0)
            c2 = costs2.get(tv, 0)
            change = c2 - c1
            pct = (change / c1 * 100) if c1 > 0 else (100 if c2 > 0 else 0)

            comparison[tv] = {
                'period1_cost': c1,
                'period2_cost': c2,
                'change_absolute': change,
                'change_percent': pct
            }

        return comparison
