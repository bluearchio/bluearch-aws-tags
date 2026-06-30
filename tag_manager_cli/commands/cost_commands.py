"""FinOps cost management commands for tag-manager CLI.

Provides CUR-based cost analysis, chargeback reporting, visibility gap
analysis, anomaly detection, and trend analysis.
"""

from datetime import date, datetime, timedelta
from typing import Optional, List

import typer
from rich.console import Console
from rich.prompt import Confirm, Prompt

from ..utils.display_utils import print_safe, print_success, print_warning, print_error
from ..utils.error_handlers import handle_aws_errors, require_aws_credentials
from ..licensing.gate import requires_tier

cost_app = typer.Typer(
    help="FinOps cost analysis and chargeback reporting (CUR-powered)",
    no_args_is_help=False
)
console = Console()


def show_cost_help():
    """Show the enhanced cost help format."""
    console.print("\n[bold cyan]FinOps Cost Analysis[/bold cyan] - CUR-powered cost visibility and optimization\n")

    console.print("[bold green]COST OVERVIEW[/bold green]:")
    console.print("- [cyan]summary[/cyan]       - Comprehensive cost summary by charge type")
    console.print("- [cyan]daily[/cyan]         - Daily cost summary with trends\n")

    console.print("[bold blue]SERVICE ANALYSIS[/bold blue] (deep-dive into specific services):")
    console.print("- [cyan]services[/cyan]      - Cost breakdown by AWS service")
    console.print("- [cyan]ec2[/cyan]           - EC2 deep dive (instance types, families, pricing)")
    console.print("- [cyan]s3[/cyan]            - S3 deep dive (buckets, storage classes, operations)")
    console.print("- [cyan]rds[/cyan]           - RDS deep dive (engines, instance types, storage)")
    console.print("- [cyan]lambda[/cyan]        - Lambda deep dive (memory tiers, functions)\n")

    console.print("[bold magenta]DIMENSIONAL ANALYSIS[/bold magenta] (slice costs by dimension):")
    console.print("- [cyan]accounts[/cyan]      - Cost breakdown by AWS account")
    console.print("- [cyan]regions[/cyan]       - Cost breakdown by AWS region")
    console.print("- [cyan]resources[/cyan]     - Top cost-driving resources")
    console.print("- [cyan]usage-types[/cyan]   - Detailed usage type breakdown\n")

    console.print("[bold yellow]COMMITMENT & OPTIMIZATION[/bold yellow]:")
    console.print("- [cyan]pricing[/cyan]       - Pricing model breakdown (On-Demand vs SP vs RI vs Spot)")
    console.print("- [cyan]savings-plans[/cyan] - Savings Plans coverage and utilization")
    console.print("- [cyan]reservations[/cyan]  - Reserved Instance utilization metrics")
    console.print("- [cyan]data-transfer[/cyan] - Data transfer costs (hidden cost driver)\n")

    console.print("[bold cyan]ANALYTICS[/bold cyan] (trends, forecasting, ad-hoc queries):")
    console.print("- [cyan]compare[/cyan]       - Compare costs between two periods (MoM, YoY)")
    console.print("- [cyan]forecast[/cyan]      - Forecast future costs based on trends")
    console.print("- [cyan]query[/cyan]         - Run ad-hoc Athena queries against CUR\n")

    console.print("[bold green]CHARGEBACK & ATTRIBUTION[/bold green] (tag-based analysis):")
    console.print("- [cyan]report[/cyan]        - Generate tag-based chargeback reports")
    console.print("- [cyan]trends[/cyan]        - View historical cost trends by tag dimension")
    console.print("- [cyan]gaps[/cyan]          - Identify untagged resources and their costs")
    console.print("- [cyan]anomalies[/cyan]     - Detect cost anomalies by tag dimension\n")

    console.print("[bold red]SETUP & CONFIGURATION[/bold red]:")
    console.print("- [cyan]setup detect[/cyan]    - Auto-detect existing CUR and display status")
    console.print("- [cyan]setup create[/cyan]    - Deploy CUR infrastructure through bluearch-core")
    console.print("- [cyan]setup validate[/cyan]  - Test CUR access and query capability\n")

    console.print("[bold white]QUICK START WORKFLOW[/bold white]:")
    console.print("1. [dim]cost setup detect[/dim]           # Check for existing CUR")
    console.print("2. [dim]cost summary[/dim]                # Overview of all costs")
    console.print("3. [dim]cost services[/dim]               # Breakdown by service")
    console.print("4. [dim]cost ec2[/dim]                    # Deep-dive into EC2")
    console.print("5. [dim]cost regions[/dim]                # Regional cost distribution")
    console.print("6. [dim]cost compare this-month last-month[/dim]  # MoM comparison")
    console.print("7. [dim]cost forecast[/dim]               # Project future costs\n")

    console.print("[bold cyan]DATA SOURCES[/bold cyan]:")
    console.print("- [green]CUR (Cost & Usage Reports)[/green] - Full detail, hourly granularity, resource-level")
    console.print("- [yellow]Cost Explorer API[/yellow] - Fallback when CUR unavailable (daily, less detail)\n")

    console.print("For detailed help on any command: [cyan]cost [COMMAND] --help[/cyan]")


def _get_data_source():
    """Get the appropriate cost data source (CUR or Cost Explorer fallback)."""
    from ..modules.finops.cur_client import CostDataSource
    from ..modules.finops.cur_setup import CURSetup

    # Try to detect CUR configuration
    setup = CURSetup()
    cur_config = setup.detect_existing_cur()

    return CostDataSource.get_source(cur_config)


def _parse_date(date_str: Optional[str], default_days_ago: int = 30) -> date:
    """Parse date string or return default."""
    if date_str:
        try:
            return datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            print_error(f"Invalid date format: {date_str}. Use YYYY-MM-DD.")
            raise typer.Exit(1)
    return date.today() - timedelta(days=default_days_ago)


# =============================================================================
# SETUP COMMANDS
# =============================================================================

@cost_app.command("setup")
@requires_tier("cost:cur_analytics")
@require_aws_credentials
def cost_setup(
    action: str = typer.Argument(
        "detect",
        help="Action: detect, create, configure, validate"
    ),
    bucket: Optional[str] = typer.Option(
        None, "--bucket", "-b",
        help="S3 bucket name for CUR data"
    ),
    database: Optional[str] = typer.Option(
        None, "--database", "-d",
        help="Athena database name"
    ),
    table: Optional[str] = typer.Option(
        None, "--table", "-t",
        help="Athena table name"
    ),
    force: bool = typer.Option(
        False, "--force", "-f",
        help="Force reconfiguration"
    )
):
    """Configure CUR access or create new CUR through bluearch-core.

    Actions:
      detect    - Auto-detect existing CUR configuration and display status
      create    - Deploy CUR infrastructure through bluearch-core
      configure - Manually configure CUR settings
      validate  - Test CUR access and query capability
    """
    from ..modules.finops.cur_setup import CURSetup, CURConfiguration

    setup = CURSetup()

    if action == "detect":
        console.print("\n[bold blue]Detecting CUR Configuration[/bold blue]\n")
        # Force refresh to always check AWS (bypass cache)
        config = setup.detect_existing_cur(force_refresh=True)

        if config:
            if config.status == 'pending':
                # CUR exists but data not ready yet - don't offer validation
                console.print("\n[yellow]CUR is set up but data is not available yet.[/yellow]")
                console.print("Check back in ~24 hours and run 'cost setup status'")
            else:
                setup.display_cur_status(config)
                # Offer to validate only for active configs
                if Confirm.ask("\nWould you like to validate CUR access?"):
                    result = setup.validate_cur_access(config)
                    if result.valid:
                        print_success("CUR access validated successfully")
                    else:
                        print_error(f"Validation failed: {result.message}")
        else:
            print_warning("No CUR configuration detected")
            if Confirm.ask("\nWould you like to set up CUR now?"):
                _deploy_cur(setup, bucket)

    elif action == "create":
        _deploy_cur(setup, bucket)

    elif action == "configure":
        if not all([database, table]):
            print_error("Manual configuration requires --database and --table")
            raise typer.Exit(1)

        config = CURConfiguration(
            account_id="manual",
            report_name="manual",
            s3_bucket=bucket or "unknown",
            s3_prefix="",
            athena_database=database,
            athena_table=table
        )

        result = setup.validate_cur_access(config)
        if result.valid:
            print_success("Configuration validated successfully")
            setup.display_cur_status(config)
        else:
            print_error(f"Configuration invalid: {result.message}")

    elif action == "validate":
        config = setup.detect_existing_cur()
        if not config:
            print_error("No CUR configuration found. Run 'cost setup detect' first.")
            raise typer.Exit(1)

        if config.status == 'pending':
            print_warning("CUR is set up but data is not available yet (~24 hours).")
            print_safe("Run 'cost setup status' later to check when data is ready.")
            raise typer.Exit(0)

        result = setup.validate_cur_access(config)
        if result.valid:
            print_success("CUR access validated successfully")
        else:
            print_error(f"Validation failed: {result.message}")

    else:
        print_error(f"Unknown action: {action}")
        print_safe("Valid actions: detect, create, configure, validate")
        raise typer.Exit(1)


def _deploy_cur(setup, bucket: Optional[str] = None):
    """Deploy CUR infrastructure."""
    from ..modules.finops.cur_setup import CURSetup

    # Check for existing tag-manager managed CUR first
    console.print("[blue]Checking for existing CUR configuration...[/blue]")
    existing_config = setup.detect_existing_cur()

    if existing_config and existing_config.report_name == 'tag-manager-cur':
        console.print("\n[yellow]A tag-manager managed CUR already exists:[/yellow]")
        setup.display_cur_status(existing_config)
        if existing_config.status == 'pending':
            console.print("\n[dim]CUR data is still being prepared (~24 hours after creation).[/dim]")
            console.print("[dim]Run 'cost setup detect' later to check when data is ready.[/dim]")
        else:
            console.print("\n[dim]CUR is already configured and active.[/dim]")
            console.print("[dim]Use 'cost setup validate' to test access.[/dim]")
        return

    if existing_config:
        console.print(f"\n[yellow]Found existing CUR: {existing_config.report_name}[/yellow]")
        console.print("[dim]You can use your existing CUR or deploy a new one.[/dim]")

    console.print("\n[bold blue]Deploying CUR Infrastructure[/bold blue]\n")
    console.print("This will create:")
    console.print("  - S3 bucket for CUR data")
    console.print("  - CUR report definition (Parquet format)")
    console.print("  - Glue database and crawler")
    console.print("")
    console.print("[yellow]Note: CUR data will be available in ~24 hours[/yellow]")

    if not Confirm.ask("\nProceed with deployment?"):
        print_safe("Deployment cancelled")
        return

    result = setup.deploy_cur_infrastructure(bucket_name=bucket)

    if result.success:
        print_success("CUR infrastructure deployment started successfully")
        console.print(f"\nStack ID: {result.stack_id}")
        # Clear cached config so next detection finds the new CUR
        setup.clear_config_cache()
        console.print("\n[yellow]Next steps:[/yellow]")
        console.print("1. Wait ~24 hours for CUR data to appear")
        console.print("2. Run 'tag-manager cost setup detect' to check status")
        console.print("3. Run 'tag-manager cost setup validate' to confirm access")
    else:
        print_error(f"Deployment failed: {result.message}")


# =============================================================================
# REPORT COMMANDS
# =============================================================================

@cost_app.command("report")
@require_aws_credentials
def cost_report(
    tag_key: Optional[str] = typer.Option(
        None, "--tag-key", "-k",
        help="Primary tag dimension for grouping (e.g., Team, Environment)"
    ),
    tag_value: Optional[str] = typer.Option(
        None, "--tag-value", "-v",
        help="Filter to specific tag value"
    ),
    group_by: Optional[str] = typer.Option(
        None, "--group-by", "-g",
        help="Additional tags to group by (comma-separated)"
    ),
    start_date: Optional[str] = typer.Option(
        None, "--start", "-s",
        help="Start date (YYYY-MM-DD, default: 30 days ago)"
    ),
    end_date: Optional[str] = typer.Option(
        None, "--end", "-e",
        help="End date (YYYY-MM-DD, default: today)"
    ),
    granularity: str = typer.Option(
        "MONTHLY", "--granularity",
        help="Time granularity: DAILY or MONTHLY"
    ),
    format_type: str = typer.Option(
        "table", "--format", "-f",
        help="Output format: table, csv, json"
    ),
    output: Optional[str] = typer.Option(
        None, "--output", "-o",
        help="Output file path (for csv/json)"
    ),
    show_all: bool = typer.Option(
        False, "--all", "-a",
        help="Show all rows (default limits to top 20)"
    ),
    summary: bool = typer.Option(
        False, "--summary",
        help="Show summary view grouped by tag value"
    )
):
    """Generate tag-based chargeback reports.

    Run without options for interactive mode, or use flags for automation.

    Examples:
      tag-manager cost report                  # Interactive mode
      tag-manager cost report -k Team          # Quick report by Team tag
      tag-manager cost report -k Environment -v production --group-by Team
      tag-manager cost report -k Team -f csv -o team_costs.csv
    """
    from ..modules.finops.chargeback import ChargebackReporter

    # Interactive mode if no tag_key provided
    if tag_key is None:
        console.print("\n[bold blue]Chargeback Report Generator[/bold blue]\n")
        console.print("[dim]Generate cost reports grouped by tag dimensions[/dim]\n")

        # Get tag key
        tag_key = Prompt.ask(
            "Enter tag key to group costs by",
            default="Team"
        )

        # Offer common presets or custom date range
        date_preset = Prompt.ask(
            "Select time range",
            choices=["last-30-days", "last-90-days", "this-month", "last-month", "custom"],
            default="last-30-days"
        )

        if date_preset == "last-30-days":
            start_date = (date.today() - timedelta(days=30)).strftime('%Y-%m-%d')
            end_date = date.today().strftime('%Y-%m-%d')
        elif date_preset == "last-90-days":
            start_date = (date.today() - timedelta(days=90)).strftime('%Y-%m-%d')
            end_date = date.today().strftime('%Y-%m-%d')
        elif date_preset == "this-month":
            start_date = date.today().replace(day=1).strftime('%Y-%m-%d')
            end_date = date.today().strftime('%Y-%m-%d')
        elif date_preset == "last-month":
            first_of_this_month = date.today().replace(day=1)
            last_month_end = first_of_this_month - timedelta(days=1)
            last_month_start = last_month_end.replace(day=1)
            start_date = last_month_start.strftime('%Y-%m-%d')
            end_date = last_month_end.strftime('%Y-%m-%d')
        else:  # custom
            start_date = Prompt.ask("Start date (YYYY-MM-DD)")
            end_date = Prompt.ask("End date (YYYY-MM-DD)", default=date.today().strftime('%Y-%m-%d'))

        # Ask about output format
        format_type = Prompt.ask(
            "Output format",
            choices=["table", "csv", "json"],
            default="table"
        )

        if format_type in ["csv", "json"]:
            output = Prompt.ask(
                f"Output file path",
                default=f"cost_report.{format_type}"
            )

        console.print("")  # Add spacing

    console.print("\n[bold blue]Generating Chargeback Report[/bold blue]\n")

    # Parse dates
    start = _parse_date(start_date, default_days_ago=90)
    end = _parse_date(end_date, default_days_ago=0) if end_date else date.today()

    # Parse additional group by
    additional_groups = None
    if group_by:
        additional_groups = [g.strip() for g in group_by.split(',')]

    # Get data source
    data_source = _get_data_source()

    # Generate report
    reporter = ChargebackReporter(data_source)
    report = reporter.generate_report(
        tag_key=tag_key,
        start_date=start,
        end_date=end,
        granularity=granularity.upper(),
        group_by=additional_groups,
        tag_value=tag_value
    )

    # Output
    if format_type == "csv":
        reporter.export_csv(report, output)
        if not output:
            console.print(reporter.export_csv(report))
    elif format_type == "json":
        reporter.export_json(report, output)
        if not output:
            console.print(reporter.export_json(report))
    else:
        if summary:
            reporter.display_summary(report)
        else:
            reporter.display_table(report, show_all=show_all)


# =============================================================================
# GAPS COMMANDS
# =============================================================================

@cost_app.command("gaps")
@require_aws_credentials
def cost_gaps(
    required_tags: Optional[str] = typer.Option(
        None, "--required-tags", "-r",
        help="Comma-separated list of required tags (interactive if not provided)"
    ),
    min_cost: float = typer.Option(
        1.0, "--min-cost",
        help="Minimum cost threshold to include"
    ),
    services: Optional[str] = typer.Option(
        None, "--services",
        help="Filter by services (comma-separated)"
    ),
    start_date: Optional[str] = typer.Option(
        None, "--start", "-s",
        help="Start date (YYYY-MM-DD, default: 30 days ago)"
    ),
    end_date: Optional[str] = typer.Option(
        None, "--end", "-e",
        help="End date (YYYY-MM-DD, default: today)"
    ),
    show_roi: bool = typer.Option(
        True, "--show-roi/--no-roi",
        help="Show tagging ROI analysis"
    ),
    show_resources: bool = typer.Option(
        False, "--show-resources",
        help="Show individual untagged resources"
    )
):
    """Identify untagged resources and their costs.

    Shows the cost of resources missing required tags and calculates
    the potential ROI of tagging them for proper cost attribution.

    Run without options for interactive mode that discovers available tags.

    Examples:
      tag-manager cost gaps                    # Interactive - discover tags
      tag-manager cost gaps -r Team,Project    # Check specific tags
      tag-manager cost gaps --show-resources
    """
    from ..modules.finops.visibility_gaps import VisibilityGapAnalyzer
    from ..modules.finops.cur_client import CURClient

    console.print("\n[bold blue]Analyzing Tagging Gaps[/bold blue]\n")

    # Get data source first - we need it to discover tags
    data_source = _get_data_source()

    # Interactive mode if no tags specified
    if required_tags is None:
        console.print("[dim]No tags specified - discovering available tags in CUR...[/dim]\n")

        # Check if we have CUR access (required for tag discovery)
        if not isinstance(data_source, CURClient):
            print_warning("Tag discovery requires CUR. Using Cost Explorer fallback.")
            print_safe("Specify tags manually with: cost gaps -r Tag1,Tag2")
            required_tags = Prompt.ask(
                "Enter required tags (comma-separated)",
                default="Team,Environment,CostCenter"
            )
        else:
            # Discover available tag columns
            available_tags = data_source.get_available_tag_columns()

            if available_tags:
                console.print(f"[green][OK] Found {len(available_tags)} tag column(s) in CUR:[/green]")
                for i, tag in enumerate(available_tags, 1):
                    console.print(f"  {i}. {tag}")
                console.print("")

                # Let user select which tags to check
                console.print("[dim]Enter tag numbers to check (comma-separated), or 'all' for all tags.[/dim]")
                console.print("[dim]Example: 1,3,5 or all[/dim]\n")

                selection = Prompt.ask(
                    "Select tags to analyze",
                    default="all"
                )

                if selection.lower() == "all":
                    tags = available_tags
                else:
                    # Parse selection
                    selected_indices = []
                    for part in selection.split(','):
                        try:
                            idx = int(part.strip()) - 1
                            if 0 <= idx < len(available_tags):
                                selected_indices.append(idx)
                        except ValueError:
                            # Check if it's a tag name instead of index
                            tag_lower = part.strip().lower()
                            for i, tag in enumerate(available_tags):
                                if tag.lower() == tag_lower:
                                    selected_indices.append(i)
                                    break

                    if selected_indices:
                        tags = [available_tags[i] for i in selected_indices]
                    else:
                        print_warning("No valid selection. Using all available tags.")
                        tags = available_tags

                console.print(f"\n[cyan]Analyzing gaps for: {', '.join(tags)}[/cyan]\n")
            else:
                print_warning("No tag columns found in CUR table.")
                console.print("[dim]This could mean:[/dim]")
                console.print("[dim]  - No resources have user tags applied[/dim]")
                console.print("[dim]  - CUR is not configured to include resource tags[/dim]")
                console.print("[dim]  - The Glue crawler hasn't run yet[/dim]\n")

                required_tags = Prompt.ask(
                    "Enter tags to check anyway (comma-separated)",
                    default="Team,Environment,CostCenter"
                )
                tags = [t.strip() for t in required_tags.split(',')]
    else:
        # Parse provided tags
        tags = [t.strip() for t in required_tags.split(',')]

    # Parse dates
    start = _parse_date(start_date, default_days_ago=30)
    end = _parse_date(end_date, default_days_ago=0) if end_date else date.today()
    service_list = [s.strip() for s in services.split(',')] if services else None

    # Analyze gaps
    analyzer = VisibilityGapAnalyzer(data_source)
    report = analyzer.analyze_gaps(
        required_tags=tags,
        start_date=start,
        end_date=end,
        min_cost=min_cost,
        services=service_list,
        calculate_roi=show_roi
    )

    # Display
    analyzer.display_report(report, show_resources=show_resources)


# =============================================================================
# ANOMALIES COMMANDS
# =============================================================================

@cost_app.command("anomalies")
@requires_tier("cost:cur_analytics")
@require_aws_credentials
def cost_anomalies(
    action: str = typer.Argument(
        "detect",
        help="Action: detect, list, configure, acknowledge"
    ),
    tag_key: Optional[str] = typer.Option(
        None, "--tag-key", "-k",
        help="Tag dimension for anomaly detection"
    ),
    percent_threshold: float = typer.Option(
        25.0, "--percent-threshold", "-p",
        help="Percent change threshold to trigger anomaly"
    ),
    absolute_threshold: float = typer.Option(
        100.0, "--absolute-threshold", "-a",
        help="Absolute dollar change threshold"
    ),
    anomaly_id: Optional[str] = typer.Option(
        None, "--id",
        help="Anomaly ID for acknowledge action"
    )
):
    """Detect and manage cost anomalies by tag dimension.

    Run 'detect' without options for interactive mode.

    Actions:
      detect      - Run anomaly detection
      list        - List detected anomalies
      configure   - Configure detection thresholds
      acknowledge - Mark an anomaly as acknowledged

    Examples:
      tag-manager cost anomalies                    # Interactive mode
      tag-manager cost anomalies detect -k Team
      tag-manager cost anomalies detect -k Environment -p 50 -a 500
      tag-manager cost anomalies list
    """
    from ..modules.finops.anomaly_detector import AnomalyDetector, AnomalyThresholds

    if action == "detect":
        # Interactive mode if no tag_key provided
        if not tag_key:
            console.print("\n[bold blue]Cost Anomaly Detection[/bold blue]\n")
            console.print("[dim]Detect unusual cost spikes by tag dimension[/dim]\n")

            tag_key = Prompt.ask(
                "Enter tag key to analyze for anomalies",
                default="Team"
            )

            percent_threshold = float(Prompt.ask(
                "Percent change threshold (e.g., 25 = 25% increase triggers alert)",
                default="25"
            ))

            absolute_threshold = float(Prompt.ask(
                "Absolute change threshold in dollars",
                default="100"
            ))

            console.print("")

        console.print("\n[bold blue]Detecting Cost Anomalies[/bold blue]\n")

        # Get data source
        data_source = _get_data_source()

        # Configure thresholds
        thresholds = AnomalyThresholds(
            percent_threshold=percent_threshold,
            absolute_threshold=absolute_threshold
        )

        # Detect anomalies
        detector = AnomalyDetector(data_source)
        anomalies = detector.detect_anomalies(
            tag_key=tag_key,
            thresholds=thresholds
        )

        # Display results
        detector.display_anomalies(anomalies)

    elif action == "list":
        console.print("\n[bold blue]Recent Cost Anomalies[/bold blue]\n")
        # TODO: Load from database
        print_warning("Anomaly history not yet implemented. Run 'detect' to find anomalies.")

    elif action == "configure":
        console.print("\n[bold blue]Anomaly Detection Configuration[/bold blue]\n")
        console.print(f"Current thresholds:")
        console.print(f"  Percent change: {percent_threshold}%")
        console.print(f"  Absolute change: ${absolute_threshold}")
        # TODO: Save to database

    elif action == "acknowledge":
        if not anomaly_id:
            print_error("--id is required to acknowledge an anomaly")
            raise typer.Exit(1)
        # TODO: Implement acknowledgment
        print_warning("Anomaly acknowledgment not yet implemented")

    else:
        print_error(f"Unknown action: {action}")
        raise typer.Exit(1)


# =============================================================================
# TRENDS COMMANDS
# =============================================================================

@cost_app.command("trends")
@require_aws_credentials
def cost_trends(
    tag_key: Optional[str] = typer.Option(
        None, "--tag-key", "-k",
        help="Tag dimension to analyze trends for"
    ),
    tag_value: Optional[str] = typer.Option(
        None, "--tag-value", "-v",
        help="Specific tag value to analyze"
    ),
    periods: int = typer.Option(
        6, "--periods", "-p",
        help="Number of periods to analyze"
    ),
    granularity: str = typer.Option(
        "MONTHLY", "--granularity",
        help="Time granularity: MONTHLY or WEEKLY"
    ),
    show_all: bool = typer.Option(
        False, "--all", "-a",
        help="Show all tag values (default limits to top 10)"
    ),
    detailed: Optional[str] = typer.Option(
        None, "--detailed",
        help="Show detailed trend for specific tag value"
    )
):
    """Show historical cost trends by tag dimension.

    Run without options for interactive mode.

    Examples:
      tag-manager cost trends                  # Interactive mode
      tag-manager cost trends -k Team
      tag-manager cost trends -k Environment -v production -p 12
      tag-manager cost trends -k Team --detailed engineering
    """
    from ..modules.finops.cost_trends import TrendAnalyzer

    # Interactive mode if no tag_key provided
    if tag_key is None:
        console.print("\n[bold blue]Cost Trend Analysis[/bold blue]\n")
        console.print("[dim]Analyze historical cost trends by tag dimension[/dim]\n")

        tag_key = Prompt.ask(
            "Enter tag key to analyze trends for",
            default="Team"
        )

        granularity = Prompt.ask(
            "Time granularity",
            choices=["MONTHLY", "WEEKLY"],
            default="MONTHLY"
        )

        periods = int(Prompt.ask(
            "Number of periods to analyze",
            default="6"
        ))

        console.print("")

    console.print("\n[bold blue]Analyzing Cost Trends[/bold blue]\n")

    # Get data source
    data_source = _get_data_source()

    # Analyze trends
    analyzer = TrendAnalyzer(data_source)
    report = analyzer.analyze_trends(
        tag_key=tag_key,
        periods=periods,
        granularity=granularity.upper(),
        tag_value=tag_value
    )

    # Display
    if detailed:
        # Find the specific trend
        for trend in report.trends:
            if trend.tag_value.lower() == detailed.lower():
                analyzer.display_detailed_trend(trend)
                return
        print_error(f"No data found for tag value: {detailed}")
    else:
        analyzer.display_trends(report, show_all=show_all)


# =============================================================================
# COST BREAKDOWN COMMANDS
# =============================================================================

@cost_app.command("services")
@requires_tier("cost:cur_analytics")
@require_aws_credentials
def cost_services(
    start_date: Optional[str] = typer.Option(
        None, "--start", "-s",
        help="Start date (YYYY-MM-DD, default: 30 days ago)"
    ),
    end_date: Optional[str] = typer.Option(
        None, "--end", "-e",
        help="End date (YYYY-MM-DD, default: today)"
    ),
    tag_key: Optional[str] = typer.Option(
        None, "--tag-key", "-k",
        help="Filter by tag key"
    ),
    tag_value: Optional[str] = typer.Option(
        None, "--tag-value", "-v",
        help="Filter by tag value (requires --tag-key)"
    ),
    limit: int = typer.Option(
        20, "--limit", "-l",
        help="Number of services to show"
    ),
    format_type: str = typer.Option(
        "table", "--format", "-f",
        help="Output format: table, csv, json"
    )
):
    """Show cost breakdown by AWS service.

    Displays unblended and blended costs per service with percentage of total.

    Examples:
      tag-manager cost services
      tag-manager cost services --start 2024-11-01
      tag-manager cost services -k Team -v engineering
    """
    from rich.table import Table

    console.print("\n[bold blue]Cost by Service[/bold blue]\n")

    # Parse dates
    start = _parse_date(start_date, default_days_ago=30)
    end = _parse_date(end_date, default_days_ago=0) if end_date else date.today()

    console.print(f"[dim]Period: {start} to {end}[/dim]\n")

    # Get data source
    data_source = _get_data_source()

    # Build tag filter
    tag_filter = None
    if tag_key and tag_value:
        tag_filter = {tag_key: tag_value}
        console.print(f"[dim]Filter: {tag_key}={tag_value}[/dim]\n")

    # Query
    result = data_source.get_costs_by_service(start, end, tag_filter)

    if not result.data:
        print_warning("No cost data found for the specified period")
        return

    # Limit results
    data = result.data[:limit]

    if format_type == "json":
        import json
        console.print(json.dumps(data, indent=2))
        return
    elif format_type == "csv":
        console.print("service,cost,blended_cost,percentage")
        for row in data:
            cost = float(row.get('cost', 0) or 0)
            pct = (cost / result.total_cost * 100) if result.total_cost > 0 else 0
            console.print(f"{row.get('service')},{cost:.2f},{row.get('blended_cost', 0)},{pct:.1f}")
        return

    # Table display
    table = Table(show_header=True, header_style="bold cyan", show_lines=True)
    table.add_column("Service", style="white")
    table.add_column("Cost (USD)", justify="right", style="green")
    table.add_column("% of Total", justify="right", style="dim")

    for row in data:
        cost = float(row.get('cost', 0) or 0)
        pct = (cost / result.total_cost * 100) if result.total_cost > 0 else 0
        table.add_row(
            row.get('service', 'Unknown'),
            f"${cost:,.2f}",
            f"{pct:.1f}%"
        )

    console.print(table)
    console.print(f"\n[bold]Total: ${result.total_cost:,.2f}[/bold]")
    console.print(f"[dim]Source: {result.source} | Query time: {result.query_time_ms}ms[/dim]")


@cost_app.command("accounts")
@requires_tier("cost:cur_analytics")
@require_aws_credentials
def cost_accounts(
    start_date: Optional[str] = typer.Option(
        None, "--start", "-s",
        help="Start date (YYYY-MM-DD, default: 30 days ago)"
    ),
    end_date: Optional[str] = typer.Option(
        None, "--end", "-e",
        help="End date (YYYY-MM-DD, default: today)"
    ),
    include_services: bool = typer.Option(
        False, "--include-services",
        help="Include service breakdown per account"
    ),
    format_type: str = typer.Option(
        "table", "--format", "-f",
        help="Output format: table, csv, json"
    )
):
    """Show cost breakdown by AWS account (multi-account).

    Displays unblended and amortized costs per linked account. Amortized costs
    properly distribute Savings Plans and Reserved Instance costs.

    Examples:
      tag-manager cost accounts
      tag-manager cost accounts --include-services
      tag-manager cost accounts --start 2024-11-01 --end 2024-12-01
    """
    from rich.table import Table
    from ..modules.finops.cur_client import CURClient

    console.print("\n[bold blue]Cost by Account[/bold blue]\n")

    # Parse dates
    start = _parse_date(start_date, default_days_ago=30)
    end = _parse_date(end_date, default_days_ago=0) if end_date else date.today()

    console.print(f"[dim]Period: {start} to {end}[/dim]\n")

    # Get data source
    data_source = _get_data_source()

    # Check if CUR is available (required for account breakdown)
    if not isinstance(data_source, CURClient):
        print_warning("Account breakdown requires CUR. Cost Explorer fallback not supported.")
        print_safe("Run 'cost setup detect' to configure CUR access.")
        return

    # Query
    result = data_source.get_costs_by_account(start, end, include_services)

    if not result.data:
        print_warning("No cost data found for the specified period")
        return

    if format_type == "json":
        import json
        console.print(json.dumps(result.data, indent=2))
        return
    elif format_type == "csv":
        if include_services:
            console.print("account_id,service,unblended_cost,amortized_cost")
        else:
            console.print("account_id,unblended_cost,amortized_cost,percentage")
        for row in result.data:
            amort = float(row.get('amortized_cost', 0) or 0)
            unbl = float(row.get('unblended_cost', 0) or 0)
            if include_services:
                console.print(f"{row.get('account_id')},{row.get('service')},{unbl:.2f},{amort:.2f}")
            else:
                pct = (amort / result.total_cost * 100) if result.total_cost > 0 else 0
                console.print(f"{row.get('account_id')},{unbl:.2f},{amort:.2f},{pct:.1f}")
        return

    # Table display
    table = Table(show_header=True, header_style="bold cyan", show_lines=True)
    table.add_column("Account ID", style="white")
    if include_services:
        table.add_column("Service", style="dim")
    table.add_column("Unblended", justify="right", style="yellow")
    table.add_column("Amortized", justify="right", style="green")
    table.add_column("% of Total", justify="right", style="dim")

    for row in result.data:
        amort = float(row.get('amortized_cost', 0) or 0)
        unbl = float(row.get('unblended_cost', 0) or 0)
        pct = (amort / result.total_cost * 100) if result.total_cost > 0 else 0

        if include_services:
            table.add_row(
                row.get('account_id', 'Unknown'),
                row.get('service', ''),
                f"${unbl:,.2f}",
                f"${amort:,.2f}",
                f"{pct:.1f}%"
            )
        else:
            table.add_row(
                row.get('account_id', 'Unknown'),
                f"${unbl:,.2f}",
                f"${amort:,.2f}",
                f"{pct:.1f}%"
            )

    console.print(table)
    console.print(f"\n[bold]Total Amortized Cost: ${result.total_cost:,.2f}[/bold]")
    console.print(f"[dim]Source: {result.source} | Query time: {result.query_time_ms}ms[/dim]")


@cost_app.command("resources")
@requires_tier("cost:cur_analytics")
@require_aws_credentials
def cost_resources(
    start_date: Optional[str] = typer.Option(
        None, "--start", "-s",
        help="Start date (YYYY-MM-DD, default: 30 days ago)"
    ),
    end_date: Optional[str] = typer.Option(
        None, "--end", "-e",
        help="End date (YYYY-MM-DD, default: today)"
    ),
    limit: int = typer.Option(
        50, "--limit", "-l",
        help="Number of resources to show"
    ),
    format_type: str = typer.Option(
        "table", "--format", "-f",
        help="Output format: table, csv, json"
    )
):
    """Show top cost-driving resources.

    Identifies the individual resources with highest costs. Useful for finding
    over-provisioned or unused resources.

    Examples:
      tag-manager cost resources
      tag-manager cost resources --limit 20
      tag-manager cost resources --start 2024-11-01
    """
    from rich.table import Table
    from ..modules.finops.cur_client import CURClient

    console.print("\n[bold blue]Top Cost-Driving Resources[/bold blue]\n")

    # Parse dates
    start = _parse_date(start_date, default_days_ago=30)
    end = _parse_date(end_date, default_days_ago=0) if end_date else date.today()

    console.print(f"[dim]Period: {start} to {end}[/dim]\n")

    # Get data source
    data_source = _get_data_source()

    if not isinstance(data_source, CURClient):
        print_warning("Resource-level breakdown requires CUR.")
        print_safe("Run 'cost setup detect' to configure CUR access.")
        return

    # Query
    result = data_source.get_top_cost_resources(start, end, limit)

    if not result.data:
        print_warning("No resource data found for the specified period")
        return

    if format_type == "json":
        import json
        console.print(json.dumps(result.data, indent=2))
        return
    elif format_type == "csv":
        console.print("account_id,service,resource_id,region,amortized_cost")
        for row in result.data:
            console.print(f"{row.get('account_id')},{row.get('service')},{row.get('resource_id')},{row.get('region')},{row.get('amortized_cost')}")
        return

    # Table display
    table = Table(show_header=True, header_style="bold cyan", show_lines=True)
    table.add_column("Service", style="cyan", width=20)
    table.add_column("Resource ID", style="white", width=50)
    table.add_column("Region", style="dim", width=15)
    table.add_column("Cost (USD)", justify="right", style="green")

    for row in result.data:
        amort = float(row.get('amortized_cost', 0) or 0)
        resource_id = row.get('resource_id', 'Unknown')
        # Truncate long resource IDs
        if len(resource_id) > 48:
            resource_id = resource_id[:45] + "..."

        table.add_row(
            row.get('service', 'Unknown'),
            resource_id,
            row.get('region', ''),
            f"${amort:,.2f}"
        )

    console.print(table)
    console.print(f"\n[bold]Total (top {limit}): ${result.total_cost:,.2f}[/bold]")
    console.print(f"[dim]Source: {result.source} | Query time: {result.query_time_ms}ms[/dim]")


@cost_app.command("daily")
@requires_tier("cost:cur_analytics")
@require_aws_credentials
def cost_daily(
    start_date: Optional[str] = typer.Option(
        None, "--start", "-s",
        help="Start date (YYYY-MM-DD, default: 30 days ago)"
    ),
    end_date: Optional[str] = typer.Option(
        None, "--end", "-e",
        help="End date (YYYY-MM-DD, default: today)"
    ),
    format_type: str = typer.Option(
        "table", "--format", "-f",
        help="Output format: table, csv, json"
    )
):
    """Show daily cost summary with trends.

    Displays daily unblended and amortized costs. Useful for identifying
    cost spikes and daily patterns.

    Examples:
      tag-manager cost daily
      tag-manager cost daily --start 2024-11-01
      tag-manager cost daily -f csv > daily_costs.csv
    """
    from rich.table import Table
    from ..modules.finops.cur_client import CURClient

    console.print("\n[bold blue]Daily Cost Summary[/bold blue]\n")

    # Parse dates
    start = _parse_date(start_date, default_days_ago=30)
    end = _parse_date(end_date, default_days_ago=0) if end_date else date.today()

    console.print(f"[dim]Period: {start} to {end}[/dim]\n")

    # Get data source
    data_source = _get_data_source()

    if not isinstance(data_source, CURClient):
        print_warning("Daily summary requires CUR for amortized costs.")
        print_safe("Run 'cost setup detect' to configure CUR access.")
        return

    # Query
    result = data_source.get_daily_cost_summary(start, end)

    if not result.data:
        print_warning("No daily data found for the specified period")
        return

    if format_type == "json":
        import json
        console.print(json.dumps(result.data, indent=2))
        return
    elif format_type == "csv":
        console.print("date,unblended_cost,amortized_cost")
        for row in result.data:
            console.print(f"{row.get('date')},{row.get('unblended_cost')},{row.get('amortized_cost')}")
        return

    # Table display with trend indicators
    table = Table(show_header=True, header_style="bold cyan", show_lines=True)
    table.add_column("Date", style="white")
    table.add_column("Unblended", justify="right", style="yellow")
    table.add_column("Amortized", justify="right", style="green")
    table.add_column("Trend", justify="center", style="dim")

    prev_cost = None
    for row in reversed(result.data):  # Show oldest first
        amort = float(row.get('amortized_cost', 0) or 0)
        unbl = float(row.get('unblended_cost', 0) or 0)

        # Calculate trend
        trend = ""
        if prev_cost is not None:
            diff = amort - prev_cost
            pct = (diff / prev_cost * 100) if prev_cost > 0 else 0
            if pct > 10:
                trend = f"[red]+{pct:.0f}%[/red]"
            elif pct < -10:
                trend = f"[green]{pct:.0f}%[/green]"
            else:
                trend = f"[dim]{pct:+.0f}%[/dim]"

        table.add_row(
            str(row.get('date', '')),
            f"${unbl:,.2f}",
            f"${amort:,.2f}",
            trend
        )
        prev_cost = amort

    console.print(table)

    # Calculate average
    avg_cost = result.total_cost / len(result.data) if result.data else 0
    console.print(f"\n[bold]Total: ${result.total_cost:,.2f} | Daily Avg: ${avg_cost:,.2f}[/bold]")
    console.print(f"[dim]Source: {result.source} | Query time: {result.query_time_ms}ms[/dim]")


@cost_app.command("summary")
@require_aws_credentials
def cost_summary(
    start_date: Optional[str] = typer.Option(
        None, "--start", "-s",
        help="Start date (YYYY-MM-DD, default: 30 days ago)"
    ),
    end_date: Optional[str] = typer.Option(
        None, "--end", "-e",
        help="End date (YYYY-MM-DD, default: today)"
    ),
    format_type: str = typer.Option(
        "table", "--format", "-f",
        help="Output format: table, csv, json"
    )
):
    """Show comprehensive cost summary by charge type.

    Breaks down costs by charge type: On-Demand, SP Covered, RI Usage,
    Taxes, Credits, Support fees, etc.

    Examples:
      tag-manager cost summary
      tag-manager cost summary --start 2024-11-01
    """
    from rich.table import Table
    from ..modules.finops.cur_client import CURClient

    console.print("\n[bold blue]Cost Summary by Charge Type[/bold blue]\n")

    # Explain what this summary shows
    console.print("[dim]This summary breaks down your AWS costs by charge type:[/dim]")
    console.print("[dim]- On-Demand Usage: Pay-as-you-go compute, storage, and services[/dim]")
    console.print("[dim]- SP Covered Usage: Usage covered by your Savings Plans commitments[/dim]")
    console.print("[dim]- SP Recurring Fee: Monthly Savings Plans charges[/dim]")
    console.print("[dim]- RI Usage: Usage covered by Reserved Instances[/dim]")
    console.print("[dim]- RI Fee: Upfront or recurring Reserved Instance fees[/dim]")
    console.print("[dim]- Tax: Regional taxes and regulatory fees[/dim]")
    console.print("[dim]- Credit: AWS credits applied (shows as negative)[/dim]")
    console.print("[dim]- Support Fee: AWS Support plan charges[/dim]")
    console.print("")

    # Parse dates
    start = _parse_date(start_date, default_days_ago=30)
    end = _parse_date(end_date, default_days_ago=0) if end_date else date.today()

    console.print(f"[dim]Period: {start} to {end}[/dim]\n")

    # Get data source
    data_source = _get_data_source()

    if not isinstance(data_source, CURClient):
        print_warning("Cost summary requires CUR for detailed charge types.")
        print_safe("Run 'cost setup detect' to configure CUR access.")
        return

    # Query
    result = data_source.get_cost_summary(start, end)

    if not result.data:
        print_warning("No cost data found for the specified period")
        return

    if format_type == "json":
        import json
        console.print(json.dumps(result.data, indent=2))
        return
    elif format_type == "csv":
        console.print("charge_type,line_count,unblended_cost")
        for row in result.data:
            console.print(f"{row.get('charge_type')},{row.get('line_count')},{row.get('unblended_cost')}")
        return

    # Table display
    table = Table(show_header=True, header_style="bold cyan", show_lines=True)
    table.add_column("Charge Type", style="white")
    table.add_column("Line Items", justify="right", style="dim")
    table.add_column("Cost (USD)", justify="right", style="green")
    table.add_column("% of Total", justify="right", style="dim")

    for row in result.data:
        cost = float(row.get('unblended_cost', 0) or 0)
        pct = (cost / result.total_cost * 100) if result.total_cost > 0 else 0

        # Color negative values (credits, refunds)
        if cost < 0:
            cost_str = f"[green]-${abs(cost):,.2f}[/green]"
        else:
            cost_str = f"${cost:,.2f}"

        table.add_row(
            row.get('charge_type', 'Unknown'),
            str(row.get('line_count', 0)),
            cost_str,
            f"{pct:.1f}%"
        )

    console.print(table)
    console.print(f"\n[bold]Total: ${result.total_cost:,.2f}[/bold]")
    console.print(f"[dim]Source: {result.source} | Query time: {result.query_time_ms}ms[/dim]")


# =============================================================================
# OPTIMIZATION COMMANDS (Savings Plans & Reserved Instances)
# =============================================================================

@cost_app.command("pricing")
@require_aws_credentials
def cost_pricing(
    start_date: Optional[str] = typer.Option(
        None, "--start", "-s",
        help="Start date (YYYY-MM-DD, default: 30 days ago)"
    ),
    end_date: Optional[str] = typer.Option(
        None, "--end", "-e",
        help="End date (YYYY-MM-DD, default: today)"
    ),
    format_type: str = typer.Option(
        "table", "--format", "-f",
        help="Output format: table, csv, json"
    )
):
    """Show pricing model breakdown (On-Demand vs Savings Plans vs RI vs Spot).

    Analyzes how your costs are distributed across different AWS pricing models.
    Helps identify optimization opportunities.

    Examples:
      tag-manager cost pricing
      tag-manager cost pricing --start 2024-11-01
    """
    from rich.table import Table
    from ..modules.finops.cur_client import CURClient

    console.print("\n[bold blue]Pricing Model Breakdown[/bold blue]\n")

    # Parse dates
    start = _parse_date(start_date, default_days_ago=30)
    end = _parse_date(end_date, default_days_ago=0) if end_date else date.today()

    console.print(f"[dim]Period: {start} to {end}[/dim]\n")

    # Get data source
    data_source = _get_data_source()

    if not isinstance(data_source, CURClient):
        print_warning("Pricing model analysis requires CUR.")
        print_safe("Run 'cost setup detect' to configure CUR access.")
        return

    # Query
    result = data_source.get_pricing_model_breakdown(start, end)

    if not result.data:
        print_warning("No pricing data found for the specified period")
        return

    if format_type == "json":
        import json
        console.print(json.dumps(result.data, indent=2))
        return

    # Aggregate by pricing model
    model_totals = {}
    for row in result.data:
        model = row.get('pricing_model', 'Other')
        cost = float(row.get('effective_cost', 0) or 0)
        if model not in model_totals:
            model_totals[model] = 0
        model_totals[model] += cost

    if format_type == "csv":
        console.print("pricing_model,effective_cost,percentage")
        for model, cost in sorted(model_totals.items(), key=lambda x: x[1], reverse=True):
            pct = (cost / result.total_cost * 100) if result.total_cost > 0 else 0
            console.print(f"{model},{cost:.2f},{pct:.1f}")
        return

    # Summary table
    summary_table = Table(show_header=True, header_style="bold cyan", show_lines=True, title="Summary by Pricing Model")
    summary_table.add_column("Pricing Model", style="white")
    summary_table.add_column("Cost (USD)", justify="right", style="green")
    summary_table.add_column("% of Total", justify="right")

    # Color code the pricing models
    model_colors = {
        'On-Demand': 'red',
        'Savings Plans': 'green',
        'Reserved Instance': 'blue',
        'Spot': 'yellow'
    }

    for model, cost in sorted(model_totals.items(), key=lambda x: x[1], reverse=True):
        pct = (cost / result.total_cost * 100) if result.total_cost > 0 else 0
        color = model_colors.get(model, 'dim')

        # Progress bar representation
        bar_len = int(pct / 5)  # 20 chars max
        bar = "[" + "=" * bar_len + " " * (20 - bar_len) + "]"

        summary_table.add_row(
            f"[{color}]{model}[/{color}]",
            f"${cost:,.2f}",
            f"[{color}]{pct:.1f}% {bar}[/{color}]"
        )

    console.print(summary_table)

    # Optimization insights
    on_demand_pct = (model_totals.get('On-Demand', 0) / result.total_cost * 100) if result.total_cost > 0 else 0
    if on_demand_pct > 50:
        console.print(f"\n[yellow][ACTION] {on_demand_pct:.0f}% On-Demand spend detected.[/yellow]")
        console.print("[yellow]Consider Savings Plans or Reserved Instances to reduce costs.[/yellow]")

    console.print(f"\n[bold]Total Effective Cost: ${result.total_cost:,.2f}[/bold]")
    console.print(f"[dim]Source: {result.source} | Query time: {result.query_time_ms}ms[/dim]")


@cost_app.command("savings-plans")
@require_aws_credentials
def cost_savings_plans(
    start_date: Optional[str] = typer.Option(
        None, "--start", "-s",
        help="Start date (YYYY-MM-DD, default: 30 days ago)"
    ),
    end_date: Optional[str] = typer.Option(
        None, "--end", "-e",
        help="End date (YYYY-MM-DD, default: today)"
    ),
    format_type: str = typer.Option(
        "table", "--format", "-f",
        help="Output format: table, csv, json"
    )
):
    """Show Savings Plans coverage and utilization.

    Tracks how well your Savings Plans commitments are being utilized.
    Low utilization means you're paying for unused commitment.

    Examples:
      tag-manager cost savings-plans
      tag-manager cost savings-plans --start 2024-11-01
    """
    from rich.table import Table
    from ..modules.finops.cur_client import CURClient

    console.print("\n[bold blue]Savings Plans Coverage & Utilization[/bold blue]\n")

    # Parse dates
    start = _parse_date(start_date, default_days_ago=30)
    end = _parse_date(end_date, default_days_ago=0) if end_date else date.today()

    console.print(f"[dim]Period: {start} to {end}[/dim]\n")

    # Get data source
    data_source = _get_data_source()

    if not isinstance(data_source, CURClient):
        print_warning("Savings Plans analysis requires CUR.")
        print_safe("Run 'cost setup detect' to configure CUR access.")
        return

    # Query
    result = data_source.get_savings_plans_coverage(start, end)

    if not result.data:
        print_warning("No Savings Plans data found")
        console.print("[dim]This could mean you have no active Savings Plans.[/dim]")
        return

    if format_type == "json":
        import json
        console.print(json.dumps(result.data, indent=2))
        return
    elif format_type == "csv":
        console.print("savings_plan_id,month,offering_type,term,total_commitment,used_commitment,unused_commitment,utilization_percent")
        for row in result.data:
            console.print(f"{row.get('savings_plan_id')},{row.get('month')},{row.get('offering_type')},{row.get('term')},{row.get('total_commitment')},{row.get('used_commitment')},{row.get('unused_commitment')},{row.get('utilization_percent')}")
        return

    # Table display
    table = Table(show_header=True, header_style="bold cyan", show_lines=True)
    table.add_column("SP ID", style="white", width=20)
    table.add_column("Month", style="dim")
    table.add_column("Type", style="cyan")
    table.add_column("Term", style="dim")
    table.add_column("Commitment", justify="right")
    table.add_column("Used", justify="right", style="green")
    table.add_column("Unused", justify="right", style="red")
    table.add_column("Util %", justify="right")

    total_commitment = 0
    total_used = 0
    total_unused = 0

    for row in result.data:
        util_pct = float(row.get('utilization_percent', 0) or 0)
        commitment = float(row.get('total_commitment', 0) or 0)
        used = float(row.get('used_commitment', 0) or 0)
        unused = float(row.get('unused_commitment', 0) or 0)

        total_commitment += commitment
        total_used += used
        total_unused += unused

        # Color utilization percentage
        if util_pct >= 95:
            util_str = f"[green]{util_pct:.1f}%[/green]"
        elif util_pct >= 80:
            util_str = f"[yellow]{util_pct:.1f}%[/yellow]"
        else:
            util_str = f"[red]{util_pct:.1f}%[/red]"

        table.add_row(
            row.get('savings_plan_id', '')[:20],
            str(row.get('month', '')),
            row.get('offering_type', ''),
            row.get('term', ''),
            f"${commitment:,.2f}",
            f"${used:,.2f}",
            f"${unused:,.2f}",
            util_str
        )

    console.print(table)

    # Overall metrics
    overall_util = (total_used / total_commitment * 100) if total_commitment > 0 else 0
    console.print(f"\n[bold]Overall Utilization: {overall_util:.1f}%[/bold]")
    console.print(f"[bold]Total Unused: ${total_unused:,.2f}[/bold]")

    if overall_util < 80:
        console.print(f"\n[red][ACTION] Low utilization detected ({overall_util:.0f}%)[/red]")
        console.print("[red]Consider right-sizing your Savings Plans commitment.[/red]")

    console.print(f"\n[dim]Source: {result.source} | Query time: {result.query_time_ms}ms[/dim]")


@cost_app.command("reservations")
@require_aws_credentials
def cost_reservations(
    start_date: Optional[str] = typer.Option(
        None, "--start", "-s",
        help="Start date (YYYY-MM-DD, default: 30 days ago)"
    ),
    end_date: Optional[str] = typer.Option(
        None, "--end", "-e",
        help="End date (YYYY-MM-DD, default: today)"
    ),
    format_type: str = typer.Option(
        "table", "--format", "-f",
        help="Output format: table, csv, json"
    )
):
    """Show Reserved Instance utilization.

    Tracks how well your Reserved Instances are being utilized.
    Low utilization means you're paying for unused reservations.

    Examples:
      tag-manager cost reservations
      tag-manager cost reservations --start 2024-11-01
    """
    from rich.table import Table
    from ..modules.finops.cur_client import CURClient

    console.print("\n[bold blue]Reserved Instance Utilization[/bold blue]\n")

    # Parse dates
    start = _parse_date(start_date, default_days_ago=30)
    end = _parse_date(end_date, default_days_ago=0) if end_date else date.today()

    console.print(f"[dim]Period: {start} to {end}[/dim]\n")

    # Get data source
    data_source = _get_data_source()

    if not isinstance(data_source, CURClient):
        print_warning("Reserved Instance analysis requires CUR.")
        print_safe("Run 'cost setup detect' to configure CUR access.")
        return

    # Query
    result = data_source.get_reserved_instance_utilization(start, end)

    if not result.data:
        print_warning("No Reserved Instance data found")
        console.print("[dim]This could mean you have no active Reserved Instances.[/dim]")
        return

    if format_type == "json":
        import json
        console.print(json.dumps(result.data, indent=2))
        return
    elif format_type == "csv":
        console.print("month,product,region,usage_type,term,quantity,reserved_units,unused_units,utilization_percent")
        for row in result.data:
            console.print(f"{row.get('month')},{row.get('product')},{row.get('region')},{row.get('usage_type')},{row.get('term')},{row.get('quantity')},{row.get('reserved_units')},{row.get('unused_units')},{row.get('utilization_percent')}")
        return

    # Table display
    table = Table(show_header=True, header_style="bold cyan", show_lines=True)
    table.add_column("Month", style="dim")
    table.add_column("Product", style="cyan")
    table.add_column("Region", style="dim")
    table.add_column("Term", style="dim")
    table.add_column("Reserved", justify="right")
    table.add_column("Unused", justify="right", style="red")
    table.add_column("Util %", justify="right")

    for row in result.data:
        util_pct = float(row.get('utilization_percent', 0) or 0)
        reserved = float(row.get('reserved_units', 0) or 0)
        unused = float(row.get('unused_units', 0) or 0)

        # Color utilization percentage
        if util_pct >= 95:
            util_str = f"[green]{util_pct:.1f}%[/green]"
        elif util_pct >= 80:
            util_str = f"[yellow]{util_pct:.1f}%[/yellow]"
        else:
            util_str = f"[red]{util_pct:.1f}%[/red]"

        table.add_row(
            str(row.get('month', '')),
            row.get('product', ''),
            row.get('region', ''),
            row.get('term', ''),
            f"{reserved:,.0f}",
            f"{unused:,.0f}",
            util_str
        )

    console.print(table)
    console.print(f"\n[dim]Source: {result.source} | Query time: {result.query_time_ms}ms[/dim]")


@cost_app.command("data-transfer")
@require_aws_credentials
def cost_data_transfer(
    start_date: Optional[str] = typer.Option(
        None, "--start", "-s",
        help="Start date (YYYY-MM-DD, default: 30 days ago)"
    ),
    end_date: Optional[str] = typer.Option(
        None, "--end", "-e",
        help="End date (YYYY-MM-DD, default: today)"
    ),
    format_type: str = typer.Option(
        "table", "--format", "-f",
        help="Output format: table, csv, json"
    )
):
    """Show data transfer costs breakdown.

    Data transfer is often a hidden cost driver. This command breaks down
    transfer costs by direction (IN/OUT), location, and service.

    Examples:
      tag-manager cost data-transfer
      tag-manager cost data-transfer --start 2024-11-01
    """
    from rich.table import Table
    from ..modules.finops.cur_client import CURClient

    console.print("\n[bold blue]Data Transfer Costs[/bold blue]\n")

    # Parse dates
    start = _parse_date(start_date, default_days_ago=30)
    end = _parse_date(end_date, default_days_ago=0) if end_date else date.today()

    console.print(f"[dim]Period: {start} to {end}[/dim]\n")

    # Get data source
    data_source = _get_data_source()

    if not isinstance(data_source, CURClient):
        print_warning("Data transfer analysis requires CUR.")
        print_safe("Run 'cost setup detect' to configure CUR access.")
        return

    # Query
    result = data_source.get_data_transfer_costs(start, end)

    if not result.data:
        print_warning("No data transfer costs found")
        return

    if format_type == "json":
        import json
        console.print(json.dumps(result.data, indent=2))
        return
    elif format_type == "csv":
        console.print("account_id,service,transfer_type,from_location,to_location,usage_gb,cost")
        for row in result.data:
            console.print(f"{row.get('account_id')},{row.get('service')},{row.get('transfer_type')},{row.get('from_location')},{row.get('to_location')},{row.get('usage_gb')},{row.get('cost')}")
        return

    # Aggregate by transfer type
    type_totals = {}
    for row in result.data:
        t_type = row.get('transfer_type', 'Other')
        cost = float(row.get('cost', 0) or 0)
        if t_type not in type_totals:
            type_totals[t_type] = 0
        type_totals[t_type] += cost

    # Summary table
    summary_table = Table(show_header=True, header_style="bold cyan", show_lines=True, title="Data Transfer Summary")
    summary_table.add_column("Transfer Type", style="white")
    summary_table.add_column("Cost (USD)", justify="right", style="green")
    summary_table.add_column("% of Transfer", justify="right", style="dim")

    for t_type, cost in sorted(type_totals.items(), key=lambda x: x[1], reverse=True):
        pct = (cost / result.total_cost * 100) if result.total_cost > 0 else 0
        summary_table.add_row(t_type, f"${cost:,.2f}", f"{pct:.1f}%")

    console.print(summary_table)

    # Detail table (top items)
    console.print("\n[bold]Top Data Transfer Costs[/bold]\n")
    detail_table = Table(show_header=True, header_style="bold cyan", show_lines=True)
    detail_table.add_column("Service", style="cyan", width=25)
    detail_table.add_column("Type", style="white")
    detail_table.add_column("From", style="dim", width=15)
    detail_table.add_column("To", style="dim", width=15)
    detail_table.add_column("GB", justify="right")
    detail_table.add_column("Cost", justify="right", style="green")

    for row in result.data[:20]:  # Top 20
        usage_gb = float(row.get('usage_gb', 0) or 0)
        cost = float(row.get('cost', 0) or 0)
        detail_table.add_row(
            row.get('service', '')[:25],
            row.get('transfer_type', ''),
            row.get('from_location', '')[:15] or '-',
            row.get('to_location', '')[:15] or '-',
            f"{usage_gb:,.1f}",
            f"${cost:,.2f}"
        )

    console.print(detail_table)

    console.print(f"\n[bold]Total Data Transfer: ${result.total_cost:,.2f}[/bold]")
    console.print(f"[dim]Source: {result.source} | Query time: {result.query_time_ms}ms[/dim]")


# =============================================================================
# SERVICE-SPECIFIC COMMANDS (EC2, S3, RDS, Lambda)
# =============================================================================

@cost_app.command("ec2")
@require_aws_credentials
def cost_ec2(
    view: str = typer.Argument(
        "summary",
        help="View: summary, instances, families, pricing"
    ),
    start_date: Optional[str] = typer.Option(
        None, "--start", "-s",
        help="Start date (YYYY-MM-DD, default: 30 days ago)"
    ),
    end_date: Optional[str] = typer.Option(
        None, "--end", "-e",
        help="End date (YYYY-MM-DD, default: today)"
    ),
    limit: int = typer.Option(
        50, "--limit", "-l",
        help="Number of results to show"
    ),
    format_type: str = typer.Option(
        "table", "--format", "-f",
        help="Output format: table, csv, json"
    )
):
    """EC2 cost analysis - instance types, families, and pricing breakdown.

    Views:
      summary   - Overview with family and pricing breakdown (default)
      instances - Breakdown by specific instance type (t3.micro, m5.large, etc.)
      families  - Breakdown by instance family (t3, m5, c5, etc.)
      pricing   - On-Demand vs Spot vs Savings Plans vs Reserved

    Examples:
      tag-manager cost ec2
      tag-manager cost ec2 instances --limit 20
      tag-manager cost ec2 pricing
      tag-manager cost ec2 families -f csv
    """
    from rich.table import Table
    from ..modules.finops.cur_client import CURClient

    console.print("\n[bold blue]EC2 Cost Analysis[/bold blue]\n")

    start = _parse_date(start_date, default_days_ago=30)
    end = _parse_date(end_date, default_days_ago=0) if end_date else date.today()
    console.print(f"[dim]Period: {start} to {end}[/dim]\n")

    data_source = _get_data_source()
    if not isinstance(data_source, CURClient):
        print_warning("EC2 analysis requires CUR. Run 'cost setup detect' first.")
        return

    if view == "instances":
        result = data_source.get_ec2_costs_by_instance_type(start, end, limit)
        title = "EC2 Cost by Instance Type"
        columns = [
            ("Instance Type", "instance_type", "cyan"),
            ("OS", "operating_system", "dim"),
            ("Tenancy", "tenancy", "dim"),
            ("Hours", "usage_hours", "right"),
            ("Cost", "cost", "green")
        ]
    elif view == "families":
        result = data_source.get_ec2_costs_by_family(start, end)
        title = "EC2 Cost by Instance Family"
        columns = [
            ("Family", "instance_family", "cyan"),
            ("Types Used", "instance_type_count", "dim"),
            ("Hours", "usage_hours", "right"),
            ("Cost", "cost", "green")
        ]
    elif view == "pricing":
        result = data_source.get_ec2_pricing_breakdown(start, end)
        title = "EC2 Cost by Pricing Model"
        columns = [
            ("Pricing Model", "pricing_model", "cyan"),
            ("Hours", "usage_hours", "right"),
            ("Cost", "cost", "green")
        ]
    else:  # summary - show all three
        console.print("[bold]Instance Family Breakdown[/bold]")
        families = data_source.get_ec2_costs_by_family(start, end)
        _display_simple_table(families, [
            ("Family", "instance_family", "cyan"),
            ("Cost", "cost", "green")
        ], limit=10)

        console.print("\n[bold]Pricing Model Breakdown[/bold]")
        pricing = data_source.get_ec2_pricing_breakdown(start, end)
        _display_simple_table(pricing, [
            ("Pricing", "pricing_model", "cyan"),
            ("Cost", "cost", "green")
        ])

        console.print(f"\n[bold]Total EC2 Cost: ${families.total_cost:,.2f}[/bold]")
        console.print(f"[dim]Source: {families.source} | Query time: {families.query_time_ms}ms[/dim]")
        return

    if not result.data:
        print_warning("No EC2 cost data found")
        return

    _display_cost_table(result, title, columns, format_type, limit)


@cost_app.command("s3")
@require_aws_credentials
def cost_s3(
    view: str = typer.Argument(
        "summary",
        help="View: summary, buckets, storage, operations"
    ),
    start_date: Optional[str] = typer.Option(
        None, "--start", "-s",
        help="Start date (YYYY-MM-DD, default: 30 days ago)"
    ),
    end_date: Optional[str] = typer.Option(
        None, "--end", "-e",
        help="End date (YYYY-MM-DD, default: today)"
    ),
    limit: int = typer.Option(
        50, "--limit", "-l",
        help="Number of results to show"
    ),
    format_type: str = typer.Option(
        "table", "--format", "-f",
        help="Output format: table, csv, json"
    )
):
    """S3 cost analysis - buckets, storage classes, and operations.

    Views:
      summary    - Overview with storage class and operation breakdown (default)
      buckets    - Cost by bucket name
      storage    - Cost by storage class (Standard, IA, Glacier, etc.)
      operations - Cost by operation type (GET, PUT, LIST, etc.)

    Examples:
      tag-manager cost s3
      tag-manager cost s3 buckets --limit 20
      tag-manager cost s3 storage
    """
    from rich.table import Table
    from ..modules.finops.cur_client import CURClient

    console.print("\n[bold blue]S3 Cost Analysis[/bold blue]\n")

    start = _parse_date(start_date, default_days_ago=30)
    end = _parse_date(end_date, default_days_ago=0) if end_date else date.today()
    console.print(f"[dim]Period: {start} to {end}[/dim]\n")

    data_source = _get_data_source()
    if not isinstance(data_source, CURClient):
        print_warning("S3 analysis requires CUR. Run 'cost setup detect' first.")
        return

    if view == "buckets":
        result = data_source.get_s3_costs_by_bucket(start, end, limit)
        title = "S3 Cost by Bucket"
        columns = [
            ("Bucket", "bucket_name", "cyan"),
            ("Cost", "cost", "green")
        ]
    elif view == "storage":
        result = data_source.get_s3_costs_by_storage_class(start, end)
        title = "S3 Cost by Storage Class"
        columns = [
            ("Storage Class", "storage_class", "cyan"),
            ("Cost", "cost", "green")
        ]
    elif view == "operations":
        result = data_source.get_s3_costs_by_operation(start, end)
        title = "S3 Cost by Operation"
        columns = [
            ("Operation", "operation", "cyan"),
            ("Requests", "request_count", "right"),
            ("Cost", "cost", "green")
        ]
    else:  # summary
        console.print("[bold]Storage Class Breakdown[/bold]")
        storage = data_source.get_s3_costs_by_storage_class(start, end)
        _display_simple_table(storage, [
            ("Storage Class", "storage_class", "cyan"),
            ("Cost", "cost", "green")
        ])

        console.print("\n[bold]Top Buckets[/bold]")
        buckets = data_source.get_s3_costs_by_bucket(start, end, 10)
        _display_simple_table(buckets, [
            ("Bucket", "bucket_name", "cyan"),
            ("Cost", "cost", "green")
        ])

        console.print(f"\n[bold]Total S3 Cost: ${storage.total_cost:,.2f}[/bold]")
        console.print(f"[dim]Source: {storage.source} | Query time: {storage.query_time_ms}ms[/dim]")
        return

    if not result.data:
        print_warning("No S3 cost data found")
        return

    _display_cost_table(result, title, columns, format_type, limit)


@cost_app.command("rds")
@require_aws_credentials
def cost_rds(
    view: str = typer.Argument(
        "summary",
        help="View: summary, engines, instances, breakdown"
    ),
    start_date: Optional[str] = typer.Option(
        None, "--start", "-s",
        help="Start date (YYYY-MM-DD, default: 30 days ago)"
    ),
    end_date: Optional[str] = typer.Option(
        None, "--end", "-e",
        help="End date (YYYY-MM-DD, default: today)"
    ),
    limit: int = typer.Option(
        50, "--limit", "-l",
        help="Number of results to show"
    ),
    format_type: str = typer.Option(
        "table", "--format", "-f",
        help="Output format: table, csv, json"
    )
):
    """RDS cost analysis - database engines, instance types, and charge breakdown.

    Views:
      summary   - Overview with engine and charge type breakdown (default)
      engines   - Cost by database engine (MySQL, PostgreSQL, Aurora, etc.)
      instances - Cost by instance type (db.t3.micro, db.r5.large, etc.)
      breakdown - Cost by charge category (Instance, Storage, I/O, etc.)

    Examples:
      tag-manager cost rds
      tag-manager cost rds engines
      tag-manager cost rds instances --limit 20
    """
    from rich.table import Table
    from ..modules.finops.cur_client import CURClient

    console.print("\n[bold blue]RDS Cost Analysis[/bold blue]\n")

    start = _parse_date(start_date, default_days_ago=30)
    end = _parse_date(end_date, default_days_ago=0) if end_date else date.today()
    console.print(f"[dim]Period: {start} to {end}[/dim]\n")

    data_source = _get_data_source()
    if not isinstance(data_source, CURClient):
        print_warning("RDS analysis requires CUR. Run 'cost setup detect' first.")
        return

    if view == "engines":
        result = data_source.get_rds_costs_by_engine(start, end)
        title = "RDS Cost by Database Engine"
        columns = [
            ("Engine", "engine", "cyan"),
            ("Instances", "instance_count", "dim"),
            ("Hours", "usage_hours", "right"),
            ("Cost", "cost", "green")
        ]
    elif view == "instances":
        result = data_source.get_rds_costs_by_instance_type(start, end, limit)
        title = "RDS Cost by Instance Type"
        columns = [
            ("Instance Type", "instance_type", "cyan"),
            ("Engine", "engine", "dim"),
            ("Hours", "usage_hours", "right"),
            ("Cost", "cost", "green")
        ]
    elif view == "breakdown":
        result = data_source.get_rds_costs_breakdown(start, end)
        title = "RDS Cost by Charge Category"
        columns = [
            ("Category", "charge_category", "cyan"),
            ("Cost", "cost", "green")
        ]
    else:  # summary
        console.print("[bold]Engine Breakdown[/bold]")
        engines = data_source.get_rds_costs_by_engine(start, end)
        _display_simple_table(engines, [
            ("Engine", "engine", "cyan"),
            ("Instances", "instance_count", "dim"),
            ("Cost", "cost", "green")
        ])

        console.print("\n[bold]Charge Category Breakdown[/bold]")
        breakdown = data_source.get_rds_costs_breakdown(start, end)
        _display_simple_table(breakdown, [
            ("Category", "charge_category", "cyan"),
            ("Cost", "cost", "green")
        ])

        console.print(f"\n[bold]Total RDS Cost: ${engines.total_cost:,.2f}[/bold]")
        console.print(f"[dim]Source: {engines.source} | Query time: {engines.query_time_ms}ms[/dim]")
        return

    if not result.data:
        print_warning("No RDS cost data found")
        return

    _display_cost_table(result, title, columns, format_type, limit)


@cost_app.command("lambda")
@require_aws_credentials
def cost_lambda(
    view: str = typer.Argument(
        "summary",
        help="View: summary, breakdown, functions"
    ),
    start_date: Optional[str] = typer.Option(
        None, "--start", "-s",
        help="Start date (YYYY-MM-DD, default: 30 days ago)"
    ),
    end_date: Optional[str] = typer.Option(
        None, "--end", "-e",
        help="End date (YYYY-MM-DD, default: today)"
    ),
    limit: int = typer.Option(
        50, "--limit", "-l",
        help="Number of results to show"
    ),
    format_type: str = typer.Option(
        "table", "--format", "-f",
        help="Output format: table, csv, json"
    )
):
    """Lambda cost analysis - invocations, duration, and function breakdown.

    Views:
      summary   - Overview with charge type breakdown (default)
      breakdown - Cost by charge type (Duration, Requests, Provisioned, etc.)
      functions - Cost by function name (requires resource-level CUR)

    Examples:
      tag-manager cost lambda
      tag-manager cost lambda breakdown
      tag-manager cost lambda functions --limit 20
    """
    from rich.table import Table
    from ..modules.finops.cur_client import CURClient

    console.print("\n[bold blue]Lambda Cost Analysis[/bold blue]\n")

    start = _parse_date(start_date, default_days_ago=30)
    end = _parse_date(end_date, default_days_ago=0) if end_date else date.today()
    console.print(f"[dim]Period: {start} to {end}[/dim]\n")

    data_source = _get_data_source()
    if not isinstance(data_source, CURClient):
        print_warning("Lambda analysis requires CUR. Run 'cost setup detect' first.")
        return

    if view == "breakdown":
        result = data_source.get_lambda_costs_by_memory(start, end)
        title = "Lambda Cost by Charge Type"
        columns = [
            ("Charge Type", "charge_type", "cyan"),
            ("Usage", "usage_amount", "right"),
            ("Cost", "cost", "green")
        ]
    elif view == "functions":
        result = data_source.get_lambda_costs_by_function(start, end, limit)
        title = "Lambda Cost by Function"
        columns = [
            ("Function", "function_name", "cyan"),
            ("Invocations", "invocations", "right"),
            ("Cost", "cost", "green")
        ]
    else:  # summary
        result = data_source.get_lambda_costs_by_memory(start, end)
        title = "Lambda Cost Breakdown"
        columns = [
            ("Charge Type", "charge_type", "cyan"),
            ("Usage", "usage_amount", "right"),
            ("Cost", "cost", "green")
        ]

    if not result.data:
        print_warning("No Lambda cost data found")
        return

    _display_cost_table(result, title, columns, format_type, limit)


# =============================================================================
# DIMENSIONAL COMMANDS (Regions, Usage Types)
# =============================================================================

@cost_app.command("regions")
@require_aws_credentials
def cost_regions(
    start_date: Optional[str] = typer.Option(
        None, "--start", "-s",
        help="Start date (YYYY-MM-DD, default: 30 days ago)"
    ),
    end_date: Optional[str] = typer.Option(
        None, "--end", "-e",
        help="End date (YYYY-MM-DD, default: today)"
    ),
    include_services: bool = typer.Option(
        False, "--include-services",
        help="Show service breakdown per region"
    ),
    format_type: str = typer.Option(
        "table", "--format", "-f",
        help="Output format: table, csv, json"
    )
):
    """Cost breakdown by AWS region.

    Shows how costs are distributed across AWS regions. Use --include-services
    to see which services are driving costs in each region.

    Examples:
      tag-manager cost regions
      tag-manager cost regions --include-services
    """
    from rich.table import Table
    from ..modules.finops.cur_client import CURClient

    console.print("\n[bold blue]Cost by Region[/bold blue]\n")

    start = _parse_date(start_date, default_days_ago=30)
    end = _parse_date(end_date, default_days_ago=0) if end_date else date.today()
    console.print(f"[dim]Period: {start} to {end}[/dim]\n")

    data_source = _get_data_source()
    if not isinstance(data_source, CURClient):
        print_warning("Regional analysis requires CUR. Run 'cost setup detect' first.")
        return

    result = data_source.get_costs_by_region(start, end, include_services)

    if not result.data:
        print_warning("No regional cost data found")
        return

    if include_services:
        columns = [
            ("Region", "region", "cyan"),
            ("Service", "service", "white"),
            ("Cost", "cost", "green")
        ]
    else:
        columns = [
            ("Region", "region", "cyan"),
            ("Services", "service_count", "dim"),
            ("Cost", "cost", "green")
        ]

    _display_cost_table(result, "Cost by AWS Region", columns, format_type)


@cost_app.command("usage-types")
@require_aws_credentials
def cost_usage_types(
    start_date: Optional[str] = typer.Option(
        None, "--start", "-s",
        help="Start date (YYYY-MM-DD, default: 30 days ago)"
    ),
    end_date: Optional[str] = typer.Option(
        None, "--end", "-e",
        help="End date (YYYY-MM-DD, default: today)"
    ),
    service: Optional[str] = typer.Option(
        None, "--service",
        help="Filter by service name (e.g., 'Amazon EC2')"
    ),
    limit: int = typer.Option(
        50, "--limit", "-l",
        help="Number of results to show"
    ),
    format_type: str = typer.Option(
        "table", "--format", "-f",
        help="Output format: table, csv, json"
    )
):
    """Detailed usage type breakdown (granular charge types).

    Shows the most specific AWS charge types like BoxUsage, DataTransfer-Out,
    EBS:VolumeUsage, etc. Useful for identifying unexpected charges.

    Examples:
      tag-manager cost usage-types
      tag-manager cost usage-types --service "Amazon EC2"
      tag-manager cost usage-types --limit 100
    """
    from rich.table import Table
    from ..modules.finops.cur_client import CURClient

    console.print("\n[bold blue]Cost by Usage Type[/bold blue]\n")

    start = _parse_date(start_date, default_days_ago=30)
    end = _parse_date(end_date, default_days_ago=0) if end_date else date.today()
    console.print(f"[dim]Period: {start} to {end}[/dim]")
    if service:
        console.print(f"[dim]Filter: {service}[/dim]")
    console.print("")

    data_source = _get_data_source()
    if not isinstance(data_source, CURClient):
        print_warning("Usage type analysis requires CUR. Run 'cost setup detect' first.")
        return

    result = data_source.get_costs_by_usage_type(start, end, service, limit)

    if not result.data:
        print_warning("No usage type data found")
        return

    columns = [
        ("Usage Type", "usage_type", "white"),
        ("Service", "service", "cyan"),
        ("Operation", "operation", "dim"),
        ("Cost", "cost", "green")
    ]

    _display_cost_table(result, "Cost by Usage Type", columns, format_type, limit)


# =============================================================================
# ANALYTICS COMMANDS (Compare, Forecast, Query)
# =============================================================================

@cost_app.command("compare")
@require_aws_credentials
def cost_compare(
    period1: Optional[str] = typer.Argument(
        None,
        help="First period: this-month, last-month, YYYY-MM"
    ),
    period2: Optional[str] = typer.Argument(
        None,
        help="Second period to compare against: last-month, YYYY-MM, last-year"
    ),
    group_by: str = typer.Option(
        "service", "--group-by", "-g",
        help="Group by: service, account, region"
    ),
    format_type: str = typer.Option(
        "table", "--format", "-f",
        help="Output format: table, csv, json"
    )
):
    """Compare costs between two periods.

    Supports named periods (this-month, last-month) or specific months (YYYY-MM).
    Use 'last-year' as period2 to compare with the same month last year.

    Examples:
      tag-manager cost compare this-month last-month
      tag-manager cost compare 2024-11 2024-10
      tag-manager cost compare this-month last-year --group-by account
    """
    from rich.table import Table
    from ..modules.finops.cur_client import CURClient

    console.print("\n[bold blue]Cost Period Comparison[/bold blue]\n")

    # Interactive prompts if periods not provided
    if not period1:
        console.print("[cyan]Select first period to analyze:[/cyan]")
        console.print("  1. this-month    - Current month")
        console.print("  2. last-month    - Previous month")
        console.print("  3. Custom        - Enter YYYY-MM format\n")

        choice = Prompt.ask("Select option", choices=["1", "2", "3"], default="1")
        if choice == "1":
            period1 = "this-month"
        elif choice == "2":
            period1 = "last-month"
        else:
            period1 = Prompt.ask("Enter period (YYYY-MM)")

    if not period2:
        console.print("\n[cyan]Select second period to compare against:[/cyan]")
        console.print("  1. last-month    - Previous month")
        console.print("  2. last-year     - Same month, last year")
        console.print("  3. Custom        - Enter YYYY-MM format\n")

        choice = Prompt.ask("Select option", choices=["1", "2", "3"], default="1")
        if choice == "1":
            period2 = "last-month"
        elif choice == "2":
            period2 = "last-year"
        else:
            period2 = Prompt.ask("Enter period (YYYY-MM)")

    data_source = _get_data_source()
    if not isinstance(data_source, CURClient):
        print_warning("Cost comparison requires CUR. Run 'cost setup detect' first.")
        return

    # Parse periods
    def parse_period(period_str: str, reference_date: date = None) -> tuple:
        today = date.today()
        if reference_date is None:
            reference_date = today

        if period_str == 'this-month':
            start = date(today.year, today.month, 1)
            if today.month == 12:
                end = date(today.year + 1, 1, 1)
            else:
                end = date(today.year, today.month + 1, 1)
        elif period_str == 'last-month':
            first_this_month = date(today.year, today.month, 1)
            end = first_this_month
            start = date(end.year - 1 if end.month == 1 else end.year,
                        12 if end.month == 1 else end.month - 1, 1)
        elif period_str == 'last-year':
            # Same month, last year - relative to reference_date
            start = date(reference_date.year - 1, reference_date.month, 1)
            if reference_date.month == 12:
                end = date(reference_date.year, 1, 1)
            else:
                end = date(reference_date.year - 1, reference_date.month + 1, 1)
        else:
            # Parse YYYY-MM format
            try:
                year, month = map(int, period_str.split('-'))
                start = date(year, month, 1)
                if month == 12:
                    end = date(year + 1, 1, 1)
                else:
                    end = date(year, month + 1, 1)
            except ValueError:
                print_error(f"Invalid period format: {period_str}. Use YYYY-MM or this-month/last-month")
                raise typer.Exit(1)

        return start, end

    p1_start, p1_end = parse_period(period1)
    p2_start, p2_end = parse_period(period2, p1_start)

    console.print(f"[dim]Period 1: {p1_start} to {p1_end}[/dim]")
    console.print(f"[dim]Period 2: {p2_start} to {p2_end}[/dim]")
    console.print(f"[dim]Grouping by: {group_by}[/dim]\n")

    # Get data for both periods
    result1 = data_source.get_monthly_costs(p1_start, p1_end, group_by)
    result2 = data_source.get_monthly_costs(p2_start, p2_end, group_by)

    # Build comparison
    p1_costs = {r.get('dimension', 'Unknown'): float(r.get('cost', 0) or 0) for r in result1.data}
    p2_costs = {r.get('dimension', 'Unknown'): float(r.get('cost', 0) or 0) for r in result2.data}

    all_dims = set(p1_costs.keys()) | set(p2_costs.keys())

    comparison = []
    for dim in all_dims:
        c1 = p1_costs.get(dim, 0)
        c2 = p2_costs.get(dim, 0)
        change = c1 - c2
        pct_change = ((c1 - c2) / c2 * 100) if c2 > 0 else (100 if c1 > 0 else 0)
        comparison.append({
            'dimension': dim,
            'period1': c1,
            'period2': c2,
            'change': change,
            'pct_change': pct_change
        })

    # Sort by absolute change
    comparison.sort(key=lambda x: abs(x['change']), reverse=True)

    # Check for empty or zero data
    total_p1 = sum(r['period1'] for r in comparison)
    total_p2 = sum(r['period2'] for r in comparison)

    if not comparison or (total_p1 == 0 and total_p2 == 0):
        console.print("[yellow]No cost data found for the selected periods.[/yellow]\n")
        console.print("Possible reasons:")
        console.print("  - CUR data may not be available for these periods yet")
        console.print("  - New CUR reports can take 24-48 hours to populate")
        console.print("  - Historical data depends on when CUR was first created")
        console.print(f"\nPeriod 1 ({p1_start} to {p1_end}): No data")
        console.print(f"Period 2 ({p2_start} to {p2_end}): No data")
        console.print("\n[dim]Tip: Try 'cost daily' to see what date ranges have data.[/dim]")
        return

    # Handle case where one period has no data - comparison not meaningful
    if total_p1 > 0 and total_p2 == 0:
        console.print("[yellow]Cannot compare: Period 2 has no cost data.[/yellow]\n")
        console.print(f"Period 1 ({p1_start} to {p1_end}): [green]${total_p1:,.2f}[/green]")
        console.print(f"Period 2 ({p2_start} to {p2_end}): [dim]No data available[/dim]\n")
        console.print("Possible reasons:")
        console.print("  - CUR was created after this period")
        console.print("  - Data retention period may have expired")
        console.print("  - The selected period predates your AWS usage\n")
        console.print("[dim]Tip: Try 'cost daily' to see what date ranges have data.[/dim]")
        console.print("[dim]Tip: Use 'cost compare this-month last-month' for recent comparison.[/dim]")
        return

    if total_p1 == 0 and total_p2 > 0:
        console.print("[yellow]Cannot compare: Period 1 has no cost data.[/yellow]\n")
        console.print(f"Period 1 ({p1_start} to {p1_end}): [dim]No data available[/dim]")
        console.print(f"Period 2 ({p2_start} to {p2_end}): [green]${total_p2:,.2f}[/green]\n")
        console.print("Possible reasons:")
        console.print("  - Current period data may still be processing")
        console.print("  - CUR data can take 24-48 hours to appear\n")
        console.print("[dim]Tip: Try 'cost daily' to see what date ranges have data.[/dim]")
        return

    if format_type == "json":
        import json
        console.print(json.dumps(comparison, indent=2))
        return
    elif format_type == "csv":
        console.print(f"{group_by},period1,period2,change,pct_change")
        for row in comparison:
            console.print(f"{row['dimension']},{row['period1']:.2f},{row['period2']:.2f},{row['change']:.2f},{row['pct_change']:.1f}")
        return

    # Table display
    table = Table(show_header=True, header_style="bold cyan", show_lines=True)
    table.add_column(group_by.title(), style="white")
    table.add_column(f"Period 1", justify="right")
    table.add_column(f"Period 2", justify="right")
    table.add_column("Change", justify="right")
    table.add_column("% Change", justify="right")

    for row in comparison[:30]:  # Top 30
        change_str = f"${row['change']:,.2f}" if row['change'] >= 0 else f"-${abs(row['change']):,.2f}"
        pct_str = f"{row['pct_change']:+.1f}%"

        # Color coding
        if row['change'] > 0:
            change_str = f"[red]{change_str}[/red]"
            pct_str = f"[red]{pct_str}[/red]"
        elif row['change'] < 0:
            change_str = f"[green]{change_str}[/green]"
            pct_str = f"[green]{pct_str}[/green]"

        table.add_row(
            row['dimension'] or 'Unknown',
            f"${row['period1']:,.2f}",
            f"${row['period2']:,.2f}",
            change_str,
            pct_str
        )

    console.print(table)

    # Totals (already calculated earlier)
    total_change = total_p1 - total_p2
    total_pct = ((total_p1 - total_p2) / total_p2 * 100) if total_p2 > 0 else 0

    console.print(f"\n[bold]Total Period 1: ${total_p1:,.2f}[/bold]")
    console.print(f"[bold]Total Period 2: ${total_p2:,.2f}[/bold]")
    if total_change >= 0:
        console.print(f"[bold red]Change: +${total_change:,.2f} ({total_pct:+.1f}%)[/bold red]")
    else:
        console.print(f"[bold green]Change: -${abs(total_change):,.2f} ({total_pct:+.1f}%)[/bold green]")


@cost_app.command("forecast")
@require_aws_credentials
def cost_forecast(
    months: int = typer.Option(
        3, "--months", "-m",
        help="Number of months to forecast"
    ),
    method: str = typer.Option(
        "linear", "--method",
        help="Forecast method: linear, average, weighted"
    ),
    format_type: str = typer.Option(
        "table", "--format", "-f",
        help="Output format: table, csv, json"
    )
):
    """Forecast future costs based on historical trends.

    Methods:
      linear   - Linear regression on historical data (default)
      average  - Simple average of recent months
      weighted - Weighted average favoring recent months

    Examples:
      tag-manager cost forecast
      tag-manager cost forecast --months 6
      tag-manager cost forecast --method average
    """
    from rich.table import Table
    from ..modules.finops.cur_client import CURClient

    console.print("\n[bold blue]Cost Forecast[/bold blue]\n")

    data_source = _get_data_source()
    if not isinstance(data_source, CURClient):
        print_warning("Cost forecasting requires CUR. Run 'cost setup detect' first.")
        return

    # Get historical data
    result = data_source.get_historical_monthly_totals(12)

    if len(result.data) < 3:
        print_warning("Need at least 3 months of data for forecasting")
        return

    # Parse historical data
    history = [(r.get('month'), float(r.get('cost', 0) or 0)) for r in result.data]
    history.sort()  # Ensure chronological order

    console.print("[bold]Historical Monthly Costs[/bold]")
    hist_table = Table(show_header=True, header_style="bold cyan")
    hist_table.add_column("Month")
    hist_table.add_column("Cost", justify="right", style="green")

    for month, cost in history[-6:]:  # Show last 6 months
        hist_table.add_row(month, f"${cost:,.2f}")

    console.print(hist_table)

    # Calculate forecast
    costs = [c for _, c in history]

    if method == "average":
        forecast_value = sum(costs[-6:]) / min(6, len(costs))
        confidence = "Medium"
    elif method == "weighted":
        # More weight to recent months
        recent = costs[-6:]
        weights = list(range(1, len(recent) + 1))
        forecast_value = sum(c * w for c, w in zip(recent, weights)) / sum(weights)
        confidence = "Medium"
    else:  # linear
        # Simple linear regression
        n = len(costs)
        x = list(range(n))
        x_mean = sum(x) / n
        y_mean = sum(costs) / n
        numerator = sum((x[i] - x_mean) * (costs[i] - y_mean) for i in range(n))
        denominator = sum((x[i] - x_mean) ** 2 for i in range(n))
        slope = numerator / denominator if denominator != 0 else 0
        intercept = y_mean - slope * x_mean
        forecast_value = slope * n + intercept
        confidence = "High" if len(costs) >= 6 else "Medium"

    # Generate forecast months
    from datetime import datetime
    last_month = datetime.strptime(history[-1][0], '%Y-%m')
    forecasts = []

    for i in range(1, months + 1):
        forecast_month = last_month.month + i
        forecast_year = last_month.year + (forecast_month - 1) // 12
        forecast_month = ((forecast_month - 1) % 12) + 1
        month_str = f"{forecast_year}-{forecast_month:02d}"

        # Add some variation based on trend
        if method == "linear":
            proj_cost = slope * (len(costs) + i - 1) + intercept
        else:
            proj_cost = forecast_value * (1 + 0.02 * i)  # 2% monthly growth assumption

        conf = "High" if i == 1 else ("Medium" if i <= 3 else "Low")
        forecasts.append({'month': month_str, 'cost': max(0, proj_cost), 'confidence': conf})

    if format_type == "json":
        import json
        console.print(json.dumps(forecasts, indent=2))
        return
    elif format_type == "csv":
        console.print("month,projected_cost,confidence")
        for f in forecasts:
            console.print(f"{f['month']},{f['cost']:.2f},{f['confidence']}")
        return

    console.print(f"\n[bold]Forecast ({method} method)[/bold]")
    forecast_table = Table(show_header=True, header_style="bold cyan")
    forecast_table.add_column("Month")
    forecast_table.add_column("Projected Cost", justify="right", style="yellow")
    forecast_table.add_column("Confidence")

    for f in forecasts:
        conf_color = "green" if f['confidence'] == "High" else ("yellow" if f['confidence'] == "Medium" else "red")
        forecast_table.add_row(
            f['month'],
            f"${f['cost']:,.2f}",
            f"[{conf_color}]{f['confidence']}[/{conf_color}]"
        )

    console.print(forecast_table)

    total_forecast = sum(f['cost'] for f in forecasts)
    console.print(f"\n[bold]Total {months}-Month Forecast: ${total_forecast:,.2f}[/bold]")


@cost_app.command("query")
@require_aws_credentials
def cost_query(
    sql: Optional[str] = typer.Argument(
        None,
        help="SQL query to execute (use {table} for CUR table name)"
    ),
    template: Optional[str] = typer.Option(
        None, "--template", "-t",
        help="Use a predefined query template"
    ),
    list_templates: bool = typer.Option(
        False, "--list-templates",
        help="List available query templates"
    ),
    format_type: str = typer.Option(
        "table", "--format", "-f",
        help="Output format: table, csv, json"
    )
):
    """Run ad-hoc Athena queries against CUR data.

    Use {table} as a placeholder for the CUR table name.
    Only SELECT queries are allowed for safety.

    Templates:
      top-services     - Top 10 services by cost
      untagged-spend   - Spend on untagged resources
      daily-trend      - Daily cost trend for last 30 days
      spot-savings     - Potential savings from Spot instances

    Examples:
      tag-manager cost query "SELECT product_product_name, SUM(line_item_unblended_cost) FROM {table} GROUP BY 1"
      tag-manager cost query --template top-services
      tag-manager cost query --list-templates
    """
    from rich.table import Table
    from ..modules.finops.cur_client import CURClient

    # Predefined templates
    templates = {
        'top-services': """
            SELECT product_product_name as service,
                   SUM(line_item_unblended_cost) as cost
            FROM {table}
            WHERE line_item_usage_start_date >= DATE_ADD('day', -30, current_date)
            GROUP BY 1
            ORDER BY 2 DESC
            LIMIT 10
        """,
        'untagged-spend': """
            SELECT product_product_name as service,
                   SUM(line_item_unblended_cost) as untagged_cost
            FROM {table}
            WHERE line_item_usage_start_date >= DATE_ADD('day', -30, current_date)
              AND line_item_line_item_type IN ('Usage', 'DiscountedUsage')
              AND (line_item_resource_id IS NULL OR line_item_resource_id = '')
            GROUP BY 1
            ORDER BY 2 DESC
            LIMIT 20
        """,
        'daily-trend': """
            SELECT DATE(line_item_usage_start_date) as date,
                   SUM(line_item_unblended_cost) as cost
            FROM {table}
            WHERE line_item_usage_start_date >= DATE_ADD('day', -30, current_date)
            GROUP BY 1
            ORDER BY 1
        """,
        'spot-savings': """
            SELECT 'On-Demand' as pricing,
                   SUM(CASE WHEN line_item_usage_type LIKE '%BoxUsage%'
                            AND line_item_line_item_type = 'Usage'
                       THEN line_item_unblended_cost ELSE 0 END) as cost
            FROM {table}
            WHERE line_item_usage_start_date >= DATE_ADD('day', -30, current_date)
              AND line_item_product_code = 'AmazonEC2'
            UNION ALL
            SELECT 'Spot' as pricing,
                   SUM(CASE WHEN line_item_usage_type LIKE '%SpotUsage%'
                       THEN line_item_unblended_cost ELSE 0 END) as cost
            FROM {table}
            WHERE line_item_usage_start_date >= DATE_ADD('day', -30, current_date)
              AND line_item_product_code = 'AmazonEC2'
        """
    }

    if list_templates:
        console.print("\n[bold blue]Available Query Templates[/bold blue]\n")
        for name, query in templates.items():
            console.print(f"[cyan]{name}[/cyan]")
            console.print(f"[dim]{query.strip()[:100]}...[/dim]\n")
        return

    if template:
        if template not in templates:
            print_error(f"Unknown template: {template}")
            console.print(f"[dim]Available: {', '.join(templates.keys())}[/dim]")
            return
        sql = templates[template]

    if not sql:
        print_error("Provide a SQL query or use --template")
        return

    console.print("\n[bold blue]Custom CUR Query[/bold blue]\n")

    data_source = _get_data_source()
    if not isinstance(data_source, CURClient):
        print_warning("Custom queries require CUR. Run 'cost setup detect' first.")
        return

    console.print(f"[dim]Query: {sql.strip()[:100]}{'...' if len(sql) > 100 else ''}[/dim]\n")

    try:
        result = data_source.execute_custom_query(sql)
    except ValueError as e:
        print_error(str(e))
        return
    except Exception as e:
        print_error(f"Query failed: {e}")
        return

    if not result.data:
        print_warning("Query returned no results")
        return

    # Dynamic column detection
    columns = list(result.data[0].keys())

    if format_type == "json":
        import json
        console.print(json.dumps(result.data, indent=2))
        return
    elif format_type == "csv":
        console.print(",".join(columns))
        for row in result.data:
            console.print(",".join(str(row.get(c, '')) for c in columns))
        return

    # Table display
    table = Table(show_header=True, header_style="bold cyan", show_lines=True)
    for col in columns:
        table.add_column(col)

    for row in result.data[:100]:  # Limit to 100 rows
        values = []
        for col in columns:
            val = row.get(col, '')
            if isinstance(val, float):
                if 'cost' in col.lower() or 'amount' in col.lower():
                    values.append(f"${val:,.2f}")
                else:
                    values.append(f"{val:,.2f}")
            else:
                values.append(str(val) if val else '')
        table.add_row(*values)

    console.print(table)
    console.print(f"\n[dim]Rows: {len(result.data)} | Query time: {result.query_time_ms}ms[/dim]")


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _display_simple_table(result, columns, limit=None):
    """Display a simple result table."""
    from rich.table import Table

    table = Table(show_header=True, header_style="bold cyan")
    for name, _, style in columns:
        table.add_column(name, style=style if style != "green" else None,
                        justify="right" if name == "Cost" else "left")

    data = result.data[:limit] if limit else result.data
    for row in data:
        values = []
        for _, key, style in columns:
            val = row.get(key, '')
            if key == 'cost' or style == 'green':
                val = f"${float(val or 0):,.2f}"
            elif isinstance(val, float):
                val = f"{val:,.0f}"
            values.append(str(val) if val else '-')
        table.add_row(*values)

    console.print(table)


def _display_cost_table(result, title, columns, format_type, limit=None):
    """Display a cost result table with format options."""
    from rich.table import Table
    import json

    data = result.data[:limit] if limit else result.data

    if format_type == "json":
        console.print(json.dumps(data, indent=2))
        return
    elif format_type == "csv":
        headers = [key for _, key, _ in columns]
        console.print(",".join(headers))
        for row in data:
            console.print(",".join(str(row.get(k, '')) for k in headers))
        return

    # Table display
    console.print(f"[bold]{title}[/bold]\n")
    table = Table(show_header=True, header_style="bold cyan", show_lines=True)

    for name, key, style in columns:
        justify = "right" if key in ['cost', 'usage_hours', 'usage_amount', 'request_count',
                                     'invocations', 'instance_count', 'service_count'] else "left"
        table.add_column(name, justify=justify)

    for row in data:
        values = []
        for name, key, style in columns:
            val = row.get(key, '')
            if key == 'cost':
                val = f"[green]${float(val or 0):,.2f}[/green]"
            elif key in ['usage_hours', 'usage_amount']:
                val = f"{float(val or 0):,.1f}"
            elif key in ['request_count', 'invocations', 'instance_count', 'service_count', 'instance_type_count']:
                val = f"{int(float(val or 0)):,}"
            elif style == "dim":
                val = f"[dim]{val or '-'}[/dim]"
            elif style == "cyan":
                val = f"[cyan]{val or '-'}[/cyan]"
            else:
                val = str(val) if val else '-'
            values.append(val)
        table.add_row(*values)

    console.print(table)
    console.print(f"\n[bold]Total: ${result.total_cost:,.2f}[/bold]")
    console.print(f"[dim]Source: {result.source} | Query time: {result.query_time_ms}ms[/dim]")


# =============================================================================
# INTERACTIVE MODE
# =============================================================================

@cost_app.callback(invoke_without_command=True)
def cost_callback(
    ctx: typer.Context,
    help: bool = typer.Option(False, "--help", "-h", help="Show this message and exit.")
):
    """
    FinOps cost analysis powered by AWS Cost and Usage Reports.

    Provides comprehensive cost visibility including chargeback reporting,
    untagged resource analysis, anomaly detection, and trend analysis.
    """
    if help or ctx.invoked_subcommand is None:
        show_cost_help()
        if help:
            raise typer.Exit()


def _interactive_cost_menu():
    """Interactive cost analysis menu."""
    from rich.table import Table

    console.print("\n[bold blue]FinOps Cost Analysis[/bold blue]")
    console.print("Powered by AWS Cost and Usage Reports\n")

    options = [
        ("1", "Generate chargeback report", "cost report"),
        ("2", "Analyze tagging gaps", "cost gaps"),
        ("3", "Detect cost anomalies", "cost anomalies"),
        ("4", "View cost trends", "cost trends"),
        ("5", "CUR setup & status", "cost setup"),
        ("b", "Back to main menu", None)
    ]

    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Option", width=8)
    table.add_column("Description")

    for opt, desc, _ in options:
        table.add_row(opt, desc)

    console.print(table)

    choice = Prompt.ask(
        "\nSelect an option",
        choices=[opt[0] for opt in options],
        default="b"
    )

    if choice == "1":
        tag_key = Prompt.ask("Enter tag key for grouping", default="Team")
        # Invoke report command
        cost_report(tag_key=tag_key, format_type="table")

    elif choice == "2":
        tags = Prompt.ask("Enter required tags (comma-separated)", default="Team,Environment")
        cost_gaps(required_tags=tags)

    elif choice == "3":
        tag_key = Prompt.ask("Enter tag key for anomaly detection", default="Team")
        cost_anomalies(action="detect", tag_key=tag_key)

    elif choice == "4":
        tag_key = Prompt.ask("Enter tag key for trend analysis", default="Team")
        cost_trends(tag_key=tag_key)

    elif choice == "5":
        cost_setup(action="status")
