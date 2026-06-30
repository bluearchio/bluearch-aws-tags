"""
Anomaly Detector - Cost spike and trend change detection.

Monitors costs by tag dimension and alerts on significant
changes compared to historical baselines.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from .cur_client import CostDataSource, QueryResult

console = Console()


class AnomalyType(str, Enum):
    """Types of cost anomalies."""
    SPIKE = 'spike'           # Sudden increase
    DROP = 'drop'             # Sudden decrease
    TREND_INCREASE = 'trend_increase'   # Gradual increase
    TREND_DECREASE = 'trend_decrease'   # Gradual decrease
    NEW_COST = 'new_cost'     # Cost appeared where there was none


class Severity(str, Enum):
    """Anomaly severity levels."""
    LOW = 'low'
    MEDIUM = 'medium'
    HIGH = 'high'
    CRITICAL = 'critical'


@dataclass
class CostAnomaly:
    """Detected cost anomaly."""
    tag_key: str
    tag_value: str
    anomaly_type: AnomalyType
    current_cost: float
    baseline_cost: float
    absolute_change: float
    percent_change: float
    severity: Severity
    detected_at: datetime = field(default_factory=datetime.utcnow)
    period: str = ''
    details: Dict[str, Any] = field(default_factory=dict)

    @property
    def change_direction(self) -> str:
        """Get human-readable change direction."""
        if self.absolute_change > 0:
            return 'increased'
        elif self.absolute_change < 0:
            return 'decreased'
        return 'unchanged'


@dataclass
class CostBaseline:
    """Historical cost baseline for anomaly detection."""
    tag_key: str
    tag_value: str
    average_cost: float
    std_deviation: float
    min_cost: float
    max_cost: float
    period_count: int
    periods: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class AnomalyThresholds:
    """Configuration for anomaly detection thresholds."""
    percent_threshold: float = 25.0      # % change to trigger
    absolute_threshold: float = 100.0    # $ change to trigger
    min_baseline_cost: float = 10.0      # Minimum baseline to consider
    std_deviation_multiplier: float = 2.0  # Std dev multiplier for anomaly


class AnomalyDetector:
    """
    Detects cost anomalies by comparing current costs to baselines.

    Features:
    - Period-over-period comparison
    - Rolling average baselines
    - Configurable thresholds (% and $)
    - Severity classification
    """

    def __init__(self, data_source: CostDataSource):
        """Initialize detector with a cost data source."""
        self.data_source = data_source

    def calculate_baseline(
        self,
        tag_key: str,
        tag_value: Optional[str] = None,
        periods: int = 3,
        granularity: str = 'MONTHLY'
    ) -> Dict[str, CostBaseline]:
        """
        Calculate cost baselines from historical data.

        Args:
            tag_key: Tag key to calculate baselines for
            tag_value: Optional specific tag value (all values if None)
            periods: Number of historical periods to use
            granularity: 'MONTHLY' or 'DAILY'

        Returns:
            Dict mapping tag values to their baselines
        """
        console.print(f"[blue]Calculating baseline for {tag_key}...[/blue]")

        # Calculate date range
        end_date = date.today()
        if granularity == 'MONTHLY':
            start_date = end_date - timedelta(days=periods * 31)
        else:
            start_date = end_date - timedelta(days=periods)

        # Query historical data
        result = self.data_source.get_costs_by_tag(
            tag_key=tag_key,
            start_date=start_date,
            end_date=end_date,
            granularity=granularity,
            tag_value=tag_value
        )

        # Aggregate by tag value
        by_tag: Dict[str, List[float]] = {}
        by_tag_periods: Dict[str, List[Dict]] = {}

        for row in result.data:
            tv = row.get('tag_value', '(untagged)') or '(untagged)'
            cost = float(row.get('cost', 0) or 0)
            period = row.get('period', '')

            if tv not in by_tag:
                by_tag[tv] = []
                by_tag_periods[tv] = []

            by_tag[tv].append(cost)
            by_tag_periods[tv].append({'period': period, 'cost': cost})

        # Calculate baselines
        baselines = {}
        for tv, costs in by_tag.items():
            if not costs:
                continue

            avg = sum(costs) / len(costs)
            variance = sum((c - avg) ** 2 for c in costs) / len(costs) if len(costs) > 1 else 0
            std_dev = variance ** 0.5

            baselines[tv] = CostBaseline(
                tag_key=tag_key,
                tag_value=tv,
                average_cost=avg,
                std_deviation=std_dev,
                min_cost=min(costs),
                max_cost=max(costs),
                period_count=len(costs),
                periods=by_tag_periods[tv]
            )

        console.print(f"[green][OK] Calculated baselines for {len(baselines)} tag values[/green]")

        return baselines

    def detect_anomalies(
        self,
        tag_key: str,
        thresholds: Optional[AnomalyThresholds] = None,
        tag_value: Optional[str] = None,
        comparison_periods: int = 1
    ) -> List[CostAnomaly]:
        """
        Detect cost anomalies for a tag dimension.

        Compares the most recent period to historical baseline
        and flags significant deviations.

        Args:
            tag_key: Tag key to analyze
            thresholds: Anomaly detection thresholds
            tag_value: Optional specific tag value
            comparison_periods: Number of periods to compare

        Returns:
            List of detected anomalies
        """
        if thresholds is None:
            thresholds = AnomalyThresholds()

        console.print(f"[blue]Detecting anomalies for {tag_key}...[/blue]")

        # Calculate baselines (using 3 historical periods)
        baselines = self.calculate_baseline(
            tag_key=tag_key,
            tag_value=tag_value,
            periods=3
        )

        # Get current period data
        end_date = date.today()
        start_date = end_date - timedelta(days=31)  # Last month

        current_result = self.data_source.get_costs_by_tag(
            tag_key=tag_key,
            start_date=start_date,
            end_date=end_date,
            granularity='MONTHLY',
            tag_value=tag_value
        )

        # Map current costs by tag value
        current_costs: Dict[str, Tuple[float, str]] = {}
        for row in current_result.data:
            tv = row.get('tag_value', '(untagged)') or '(untagged)'
            cost = float(row.get('cost', 0) or 0)
            period = row.get('period', '')
            current_costs[tv] = (cost, period)

        # Detect anomalies
        anomalies = []

        # Check existing tag values
        all_tag_values = set(baselines.keys()) | set(current_costs.keys())

        for tv in all_tag_values:
            baseline = baselines.get(tv)
            current_data = current_costs.get(tv)

            if current_data:
                current_cost, period = current_data
            else:
                current_cost, period = 0.0, ''

            # New cost center (no baseline)
            if baseline is None and current_cost > thresholds.min_baseline_cost:
                anomaly = CostAnomaly(
                    tag_key=tag_key,
                    tag_value=tv,
                    anomaly_type=AnomalyType.NEW_COST,
                    current_cost=current_cost,
                    baseline_cost=0,
                    absolute_change=current_cost,
                    percent_change=100.0,
                    severity=self._calculate_severity(current_cost, 0, thresholds),
                    period=period,
                    details={'message': 'New cost center detected'}
                )
                anomalies.append(anomaly)
                continue

            if baseline is None:
                continue

            # Skip if baseline is too low
            if baseline.average_cost < thresholds.min_baseline_cost:
                continue

            # Calculate changes
            absolute_change = current_cost - baseline.average_cost
            percent_change = (absolute_change / baseline.average_cost * 100) if baseline.average_cost > 0 else 0

            # Check if anomaly
            is_anomaly = False
            anomaly_type = None

            # Percentage threshold
            if abs(percent_change) >= thresholds.percent_threshold:
                is_anomaly = True
                anomaly_type = AnomalyType.SPIKE if percent_change > 0 else AnomalyType.DROP

            # Absolute threshold
            elif abs(absolute_change) >= thresholds.absolute_threshold:
                is_anomaly = True
                anomaly_type = AnomalyType.SPIKE if absolute_change > 0 else AnomalyType.DROP

            # Standard deviation check
            elif baseline.std_deviation > 0:
                z_score = abs(current_cost - baseline.average_cost) / baseline.std_deviation
                if z_score >= thresholds.std_deviation_multiplier:
                    is_anomaly = True
                    anomaly_type = AnomalyType.SPIKE if absolute_change > 0 else AnomalyType.DROP

            if is_anomaly and anomaly_type:
                severity = self._calculate_severity(absolute_change, baseline.average_cost, thresholds)

                anomaly = CostAnomaly(
                    tag_key=tag_key,
                    tag_value=tv,
                    anomaly_type=anomaly_type,
                    current_cost=current_cost,
                    baseline_cost=baseline.average_cost,
                    absolute_change=absolute_change,
                    percent_change=percent_change,
                    severity=severity,
                    period=period,
                    details={
                        'baseline_std_dev': baseline.std_deviation,
                        'baseline_periods': baseline.period_count,
                        'baseline_min': baseline.min_cost,
                        'baseline_max': baseline.max_cost
                    }
                )
                anomalies.append(anomaly)

        # Sort by severity and absolute change
        severity_order = {Severity.CRITICAL: 0, Severity.HIGH: 1, Severity.MEDIUM: 2, Severity.LOW: 3}
        anomalies.sort(key=lambda x: (severity_order[x.severity], -abs(x.absolute_change)))

        console.print(f"[green][OK] Detected {len(anomalies)} anomalies[/green]")

        return anomalies

    def _calculate_severity(
        self,
        absolute_change: float,
        baseline: float,
        thresholds: AnomalyThresholds
    ) -> Severity:
        """Calculate anomaly severity based on impact."""
        abs_change = abs(absolute_change)
        pct_change = (abs_change / baseline * 100) if baseline > 0 else 100

        # Critical: Very large absolute or percentage change
        if abs_change >= thresholds.absolute_threshold * 10 or pct_change >= 100:
            return Severity.CRITICAL

        # High: Large changes
        if abs_change >= thresholds.absolute_threshold * 5 or pct_change >= 75:
            return Severity.HIGH

        # Medium: Moderate changes
        if abs_change >= thresholds.absolute_threshold * 2 or pct_change >= 50:
            return Severity.MEDIUM

        return Severity.LOW

    def display_anomalies(self, anomalies: List[CostAnomaly]) -> None:
        """Display detected anomalies in a formatted table."""
        if not anomalies:
            console.print("[green][OK] No anomalies detected[/green]")
            return

        table = Table(
            title="Cost Anomalies Detected",
            show_header=True,
            header_style="bold red"
        )

        table.add_column("Severity", style="white")
        table.add_column("Tag Value", style="cyan")
        table.add_column("Type", style="white")
        table.add_column("Current", style="green", justify="right")
        table.add_column("Baseline", style="dim", justify="right")
        table.add_column("Change", style="red", justify="right")
        table.add_column("% Change", style="yellow", justify="right")

        severity_styles = {
            Severity.CRITICAL: "[bold red]CRITICAL[/bold red]",
            Severity.HIGH: "[red]HIGH[/red]",
            Severity.MEDIUM: "[yellow]MEDIUM[/yellow]",
            Severity.LOW: "[dim]LOW[/dim]"
        }

        for anomaly in anomalies:
            change_str = f"+${anomaly.absolute_change:,.2f}" if anomaly.absolute_change > 0 else f"-${abs(anomaly.absolute_change):,.2f}"
            pct_str = f"+{anomaly.percent_change:.1f}%" if anomaly.percent_change > 0 else f"{anomaly.percent_change:.1f}%"

            table.add_row(
                severity_styles[anomaly.severity],
                anomaly.tag_value[:30],
                anomaly.anomaly_type.value.upper(),
                f"${anomaly.current_cost:,.2f}",
                f"${anomaly.baseline_cost:,.2f}",
                change_str,
                pct_str
            )

        console.print(table)

        # Summary
        critical = sum(1 for a in anomalies if a.severity == Severity.CRITICAL)
        high = sum(1 for a in anomalies if a.severity == Severity.HIGH)
        total_impact = sum(a.absolute_change for a in anomalies)

        summary = f"""
[bold]Anomaly Summary[/bold]
  Critical: {critical}
  High: {high}
  Total Impact: ${total_impact:,.2f}
"""
        if critical > 0 or high > 0:
            summary += "\n[bold red]Action Required: Review critical and high severity anomalies[/bold red]"

        console.print(Panel(summary, border_style="red" if critical else "yellow"))

    def get_anomaly_details(self, anomaly: CostAnomaly) -> str:
        """Get detailed description of an anomaly."""
        details = f"""
[bold]Anomaly Details[/bold]

Tag: {anomaly.tag_key} = {anomaly.tag_value}
Period: {anomaly.period}
Detected: {anomaly.detected_at.strftime('%Y-%m-%d %H:%M')}

[bold cyan]Cost Analysis:[/bold cyan]
  Current Cost: ${anomaly.current_cost:,.2f}
  Baseline (avg): ${anomaly.baseline_cost:,.2f}
  Absolute Change: ${anomaly.absolute_change:+,.2f}
  Percent Change: {anomaly.percent_change:+.1f}%

[bold cyan]Classification:[/bold cyan]
  Type: {anomaly.anomaly_type.value.upper()}
  Severity: {anomaly.severity.value.upper()}

[bold cyan]Baseline Details:[/bold cyan]
"""
        if anomaly.details:
            details += f"  Std Deviation: ${anomaly.details.get('baseline_std_dev', 0):,.2f}\n"
            details += f"  Historical Range: ${anomaly.details.get('baseline_min', 0):,.2f} - ${anomaly.details.get('baseline_max', 0):,.2f}\n"
            details += f"  Periods Used: {anomaly.details.get('baseline_periods', 0)}\n"

        return details
