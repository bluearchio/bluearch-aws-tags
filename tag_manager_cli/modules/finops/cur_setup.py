"""
CUR Setup - Detection and configuration of AWS Cost and Usage Reports.

Handles auto-detection of existing CUR configurations and provides
bluearch-core-managed setup for new CUR deployments.
"""

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from botocore.exceptions import ClientError
from rich.console import Console
from rich.table import Table

from ...utils.aws_auth import aws_auth
from ...utils.cache import cache
from ...utils.core_client import CoreRuntimeError, request_core

console = Console()

# Cache key and TTL for CUR configuration
CUR_CONFIG_CACHE_KEY = "finops:cur:config"
CUR_CONFIG_CACHE_TTL = 3600  # 1 hour


@dataclass
class CURConfiguration:
    """Configuration for CUR access."""
    account_id: str
    report_name: str
    s3_bucket: str
    s3_prefix: str
    athena_database: str
    athena_table: str
    athena_workgroup: str = 'primary'
    region: str = 'us-east-1'
    status: str = 'active'
    setup_stack_id: Optional[str] = None


@dataclass
class ValidationResult:
    """Result of CUR configuration validation."""
    valid: bool
    message: str
    details: Dict[str, Any] = None


@dataclass
class DeploymentResult:
    """Result of CUR infrastructure deployment."""
    success: bool
    stack_id: Optional[str] = None
    config: Optional[CURConfiguration] = None
    message: str = ''
    estimated_ready_hours: int = 24  # CUR data typically takes ~24h to appear


class CURSetup:
    """
    Handles CUR detection, validation, and setup.

    Provides functionality to:
    - Detect existing CUR configurations in an AWS account
    - Validate CUR access via Athena
    - Request new CUR infrastructure through bluearch-core
    - Store and retrieve CUR configuration
    """

    # Standard CUR report names we look for
    KNOWN_REPORT_NAMES = [
        'cur-report',
        'cost-and-usage-report',
        'aws-cost-report',
        'billing-report',
        'finops-cur',
    ]

    # Standard Glue database names for CUR
    KNOWN_DATABASE_NAMES = [
        'athenacurcfn_cur_report',
        'athenacurcfn_cost_and_usage_report',
        'cur_database',
        'cost_usage_db',
        'billing_db',
    ]

    def __init__(self):
        """Initialize CUR setup handler."""
        self._cur_client = None
        self._glue_client = None
        self._athena_client = None
        self._s3_client = None
        self._cfn_client = None
        self._sts_client = None

    def _get_client(self, service: str, region: str = None):
        """Get boto3 client with caching."""
        return aws_auth.get_client(service, region=region)

    def detect_existing_cur(self, force_refresh: bool = False) -> Optional[CURConfiguration]:
        """
        Detect existing CUR configurations in the account.

        Searches for:
        1. Existing CUR report definitions
        2. Glue databases with CUR data
        3. Athena tables queryable for cost data

        Args:
            force_refresh: If True, bypass cache and re-detect

        Returns:
            CURConfiguration if found, None otherwise
        """
        # Check cache first (unless force refresh)
        if not force_refresh:
            cached_config = cache.get(CUR_CONFIG_CACHE_KEY)
            if cached_config is not None:
                # Reconstruct CURConfiguration from cached dict
                if cached_config.get('_cached'):
                    config = CURConfiguration(
                        account_id=cached_config['account_id'],
                        report_name=cached_config['report_name'],
                        s3_bucket=cached_config['s3_bucket'],
                        s3_prefix=cached_config['s3_prefix'],
                        athena_database=cached_config['athena_database'],
                        athena_table=cached_config['athena_table'],
                        athena_workgroup=cached_config.get('athena_workgroup', 'primary'),
                        region=cached_config.get('region', 'us-east-1'),
                        status=cached_config.get('status', 'active'),
                        setup_stack_id=cached_config.get('setup_stack_id')
                    )
                    console.print(f"[dim][CACHE] Using cached CUR configuration: {config.athena_database}.{config.athena_table}[/dim]")
                    return config

        console.print("[blue]Detecting existing CUR configuration...[/blue]")

        # Get account ID
        try:
            sts = self._get_client('sts')
            account_id = sts.get_caller_identity()['Account']
        except Exception as e:
            console.print(f"[red]Failed to get account ID: {e}[/red]")
            return None

        # Step 1: Check for CUR report definitions
        cur_reports = self._find_cur_reports()
        if cur_reports:
            console.print(f"[green][OK] Found {len(cur_reports)} CUR report(s)[/green]")
            for report in cur_reports:
                console.print(f"  - {report['ReportName']} -> s3://{report['S3Bucket']}/{report.get('S3Prefix', '')}")

        # Step 2: Find Glue databases with CUR tables
        cur_databases = self._find_cur_databases()
        if cur_databases:
            console.print(f"[green][OK] Found {len(cur_databases)} potential CUR database(s)[/green]")

        # Step 3: Try to match report to database
        config = self._match_cur_config(account_id, cur_reports, cur_databases)

        if config:
            if config.status == 'pending':
                console.print(f"[yellow][PENDING] CUR report exists but data not ready yet:[/yellow]")
                console.print(f"  Report: {config.report_name}")
                console.print(f"  S3: s3://{config.s3_bucket}/{config.s3_prefix}")
                console.print(f"\n[dim]CUR data takes ~24 hours to appear after initial setup.[/dim]")
                console.print(f"[dim]Run 'cost setup detect' later to check.[/dim]")
                # Don't cache pending configs - check again next time
            else:
                console.print(f"[green][OK] CUR configuration detected:[/green]")
                console.print(f"  Database: {config.athena_database}")
                console.print(f"  Table: {config.athena_table}")
                console.print(f"  S3: s3://{config.s3_bucket}/{config.s3_prefix}")
                # Cache active configuration
                self._cache_config(config)
            return config

        console.print("[yellow][WARN] No CUR configuration found[/yellow]")
        return None

    def _cache_config(self, config: CURConfiguration):
        """Cache the CUR configuration."""
        config_dict = {
            '_cached': True,
            'account_id': config.account_id,
            'report_name': config.report_name,
            's3_bucket': config.s3_bucket,
            's3_prefix': config.s3_prefix,
            'athena_database': config.athena_database,
            'athena_table': config.athena_table,
            'athena_workgroup': config.athena_workgroup,
            'region': config.region,
            'status': config.status,
            'setup_stack_id': config.setup_stack_id
        }
        cache.set(CUR_CONFIG_CACHE_KEY, config_dict, ttl=CUR_CONFIG_CACHE_TTL)

    def clear_config_cache(self):
        """Clear the cached CUR configuration."""
        cache.delete(CUR_CONFIG_CACHE_KEY)

    def _find_cur_reports(self) -> List[Dict]:
        """Find CUR report definitions in the account."""
        reports = []

        try:
            # CUR API is only available in us-east-1
            cur_client = self._get_client('cur', region='us-east-1')

            paginator = cur_client.get_paginator('describe_report_definitions')
            for page in paginator.paginate():
                for report in page.get('ReportDefinitions', []):
                    # We want Parquet format for Athena compatibility
                    if report.get('Format') == 'Parquet' or report.get('Compression') == 'Parquet':
                        reports.append(report)
                    elif report.get('AdditionalSchemaElements') and 'RESOURCES' in report['AdditionalSchemaElements']:
                        # Resource-level data is available
                        reports.append(report)
                    else:
                        # Still useful, just note the format
                        reports.append(report)

        except ClientError as e:
            if e.response['Error']['Code'] == 'AccessDeniedException':
                console.print("[yellow][WARN] No permission to list CUR reports (cur:DescribeReportDefinitions)[/yellow]")
            else:
                console.print(f"[yellow][WARN] Could not list CUR reports: {e}[/yellow]")
        except Exception as e:
            console.print(f"[yellow][WARN] Error checking CUR reports: {e}[/yellow]")

        return reports

    def _find_cur_databases(self) -> List[Dict]:
        """Find Glue databases that might contain CUR data."""
        databases = []

        try:
            glue_client = self._get_client('glue')

            paginator = glue_client.get_paginator('get_databases')
            for page in paginator.paginate():
                for db in page.get('DatabaseList', []):
                    db_name = db['Name'].lower()

                    # Check if database name suggests CUR data
                    is_cur_db = any(
                        pattern in db_name
                        for pattern in ['cur', 'cost', 'billing', 'usage']
                    )

                    if is_cur_db:
                        # Get tables in this database
                        tables = self._get_cur_tables(db['Name'])
                        if tables:
                            databases.append({
                                'name': db['Name'],
                                'tables': tables
                            })

        except ClientError as e:
            if e.response['Error']['Code'] == 'AccessDeniedException':
                console.print("[yellow][WARN] No permission to list Glue databases (glue:GetDatabases)[/yellow]")
            else:
                console.print(f"[yellow][WARN] Could not list Glue databases: {e}[/yellow]")
        except Exception as e:
            console.print(f"[yellow][WARN] Error checking Glue databases: {e}[/yellow]")

        return databases

    def _get_cur_tables(self, database_name: str) -> List[str]:
        """Get tables in a database that look like CUR tables."""
        tables = []

        try:
            glue_client = self._get_client('glue')

            paginator = glue_client.get_paginator('get_tables')
            for page in paginator.paginate(DatabaseName=database_name):
                for table in page.get('TableList', []):
                    table_name = table['Name'].lower()

                    # Check if table has CUR-like columns
                    columns = [col['Name'].lower() for col in table.get('StorageDescriptor', {}).get('Columns', [])]

                    # CUR tables typically have these columns
                    cur_indicators = ['line_item_unblended_cost', 'line_item_usage_start_date', 'product_product_name']

                    if any(ind in columns for ind in cur_indicators):
                        tables.append(table['Name'])
                    elif 'cur' in table_name or 'cost' in table_name:
                        tables.append(table['Name'])

        except Exception:
            pass  # Silently handle errors for individual databases

        return tables

    def _match_cur_config(
        self,
        account_id: str,
        reports: List[Dict],
        databases: List[Dict]
    ) -> Optional[CURConfiguration]:
        """Match CUR reports to Glue databases to create a complete configuration."""

        # If we have both reports and databases, try to match them
        if reports and databases:
            for report in reports:
                report_name = report['ReportName'].lower().replace('-', '_')

                for db in databases:
                    # Check if database name matches report
                    if report_name in db['name'].lower():
                        if db['tables']:
                            return CURConfiguration(
                                account_id=account_id,
                                report_name=report['ReportName'],
                                s3_bucket=report['S3Bucket'],
                                s3_prefix=report.get('S3Prefix', ''),
                                athena_database=db['name'],
                                athena_table=db['tables'][0],
                                region=report.get('S3Region', 'us-east-1'),
                                status='active'
                            )

        # If we only have databases with valid tables, use the first one
        if databases:
            for db in databases:
                if db['tables']:
                    # Try to infer S3 location from table
                    s3_info = self._get_table_s3_location(db['name'], db['tables'][0])

                    return CURConfiguration(
                        account_id=account_id,
                        report_name='detected',
                        s3_bucket=s3_info.get('bucket', 'unknown'),
                        s3_prefix=s3_info.get('prefix', ''),
                        athena_database=db['name'],
                        athena_table=db['tables'][0],
                        status='active'
                    )

        # If we have CUR reports but no Glue database yet, return pending config
        # This happens when CUR was just created and data isn't available yet (~24h wait)
        if reports:
            report = reports[0]  # Use first report
            return CURConfiguration(
                account_id=account_id,
                report_name=report['ReportName'],
                s3_bucket=report['S3Bucket'],
                s3_prefix=report.get('S3Prefix', ''),
                athena_database='',  # Not yet available
                athena_table='',     # Not yet available
                region=report.get('S3Region', 'us-east-1'),
                status='pending'     # Data not ready yet
            )

        return None

    def _get_table_s3_location(self, database: str, table: str) -> Dict[str, str]:
        """Get S3 location from Glue table metadata."""
        try:
            glue_client = self._get_client('glue')
            response = glue_client.get_table(DatabaseName=database, Name=table)

            location = response['Table'].get('StorageDescriptor', {}).get('Location', '')

            if location.startswith('s3://'):
                # Parse s3://bucket/prefix format
                parts = location[5:].split('/', 1)
                return {
                    'bucket': parts[0],
                    'prefix': parts[1] if len(parts) > 1 else ''
                }

        except Exception:
            pass

        return {}

    def validate_cur_access(self, config: CURConfiguration) -> ValidationResult:
        """
        Validate that we can query the CUR data.

        Runs a test query against the configured Athena table to ensure
        the data is accessible and contains expected CUR columns.
        """
        console.print("[blue]Validating CUR access...[/blue]")

        try:
            athena_client = self._get_client('athena', region=config.region)

            # Quote identifiers for names with special characters (hyphens, etc.)
            quoted_db = f'"{config.athena_database}"'
            quoted_table = f'"{config.athena_table}"'

            # Test query to validate access and schema
            test_query = f"""
            SELECT
                line_item_usage_start_date,
                line_item_unblended_cost,
                product_product_name
            FROM {quoted_db}.{quoted_table}
            LIMIT 1
            """

            # Build output location for Athena results
            output_location = f"s3://{config.s3_bucket}/athena-results/"

            # Start query
            response = athena_client.start_query_execution(
                QueryString=test_query,
                QueryExecutionContext={'Database': config.athena_database},
                ResultConfiguration={'OutputLocation': output_location},
                WorkGroup=config.athena_workgroup
            )

            execution_id = response['QueryExecutionId']

            # Wait for completion (with timeout)
            start_time = time.time()
            while time.time() - start_time < 60:  # 60 second timeout
                result = athena_client.get_query_execution(QueryExecutionId=execution_id)
                state = result['QueryExecution']['Status']['State']

                if state == 'SUCCEEDED':
                    console.print("[green][OK] CUR access validated successfully[/green]")
                    return ValidationResult(
                        valid=True,
                        message="CUR data is accessible and contains expected columns",
                        details={'execution_id': execution_id}
                    )
                elif state in ('FAILED', 'CANCELLED'):
                    reason = result['QueryExecution']['Status'].get('StateChangeReason', 'Unknown error')
                    return ValidationResult(
                        valid=False,
                        message=f"Query {state.lower()}: {reason}",
                        details={'execution_id': execution_id, 'state': state}
                    )

                time.sleep(1)

            return ValidationResult(
                valid=False,
                message="Validation query timed out",
                details={'execution_id': execution_id}
            )

        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_msg = e.response['Error']['Message']

            if 'AccessDenied' in error_code:
                return ValidationResult(
                    valid=False,
                    message=f"Permission denied: {error_msg}",
                    details={'error_code': error_code}
                )
            else:
                return ValidationResult(
                    valid=False,
                    message=f"AWS error: {error_msg}",
                    details={'error_code': error_code}
                )
        except Exception as e:
            return ValidationResult(
                valid=False,
                message=f"Unexpected error: {str(e)}"
            )

    def deploy_cur_infrastructure(
        self,
        bucket_name: Optional[str] = None,
        report_name: str = 'tag-manager-cur',
        stack_name: str = 'BlueArchCUR'
    ) -> DeploymentResult:
        """
        Ask bluearch-core to deploy the CloudFormation stack for CUR infrastructure.

        Creates:
        - S3 bucket for CUR data (or uses provided bucket)
        - CUR report definition
        - Glue database and crawler
        - Athena workgroup

        Args:
            bucket_name: Optional S3 bucket name (auto-generated if not provided)
            report_name: Name for the CUR report
            stack_name: Core-owned CloudFormation stack name

        Returns:
            DeploymentResult with status and configuration
        """
        console.print("[blue]Submitting CUR infrastructure deployment to bluearch-core...[/blue]")

        try:
            job = request_core(
                "POST",
                "/api/v1/infrastructure/stacks/cost-reports/deploy",
                service_token=True,
                timeout=10.0,
                json={
                    "bucket_name": bucket_name,
                    "report_name": report_name,
                },
            )
            job_id = job["job_id"]
            console.print(f"[green][OK] Deployment job started: {job_id}[/green]")
            console.print("[blue]Waiting for bluearch-core to finish stack deployment...[/blue]")

            deadline = time.time() + 900
            last_message = ""
            while time.time() < deadline:
                status = request_core("GET", f"/api/v1/jobs/{job_id}", timeout=10.0)
                current_status = status.get("status")
                message = status.get("progress_message") or status.get("message") or ""
                progress = status.get("progress") or 0
                if message and message != last_message:
                    console.print(f"[dim]{progress:>3}% {message}[/dim]")
                    last_message = message

                if current_status == "completed":
                    result = status.get("result") or {}
                    result_stack_id = result.get("stack_id") or job_id
                    result_bucket = result.get("bucket_name") or bucket_name or ""
                    result_report = result.get("report_name") or report_name
                    try:
                        account_id = self._get_client('sts').get_caller_identity()['Account']
                    except Exception:
                        account_id = ""
                    config = CURConfiguration(
                        account_id=account_id,
                        report_name=result_report,
                        s3_bucket=result_bucket,
                        s3_prefix=result_report,
                        athena_database=f"athenacurcfn_{result_report.replace('-', '_')}",
                        athena_table=result_report.replace('-', '_'),
                        athena_workgroup='primary',
                        region='us-east-1',
                        status='setup_pending',
                        setup_stack_id=result_stack_id,
                    )
                    console.print(f"[green][OK] Stack deployment complete: {result.get('stack_name') or stack_name}[/green]")
                    console.print("[yellow]Note: CUR data will be available in ~24 hours[/yellow]")
                    return DeploymentResult(
                        success=True,
                        stack_id=result_stack_id,
                        config=config,
                        message=result.get("message") or "CUR infrastructure deployment completed",
                        estimated_ready_hours=int(result.get("estimated_ready_hours") or 24),
                    )

                if current_status == "failed":
                    error = status.get("error") or message or "bluearch-core deployment failed"
                    return DeploymentResult(success=False, message=f"Deployment failed: {error}")

                time.sleep(3)

            return DeploymentResult(
                success=True,
                stack_id=job_id,
                message="CUR deployment is still running in bluearch-core",
            )

        except CoreRuntimeError as e:
            console.print(f"[red]bluearch-core error: {e}[/red]")
            return DeploymentResult(success=False, message=f"Deployment failed: {e}")
        except Exception as e:
            console.print(f"[red]Unexpected error: {e}[/red]")
            return DeploymentResult(success=False, message=f"Deployment failed: {str(e)}")

    def display_cur_status(self, config: Optional[CURConfiguration] = None):
        """Display CUR configuration status in a table."""
        table = Table(title="CUR Configuration Status", show_header=True, header_style="bold cyan")
        table.add_column("Setting", style="white")
        table.add_column("Value", style="green")

        if config:
            # Format status with color based on state
            if config.status == 'pending':
                status_display = "[yellow]PENDING - Waiting for data (~24h)[/yellow]"
            elif config.status == 'active':
                status_display = "[green]ACTIVE[/green]"
            else:
                status_display = config.status.upper()

            table.add_row("Status", status_display)
            table.add_row("Account ID", config.account_id)
            table.add_row("Report Name", config.report_name)
            table.add_row("S3 Bucket", config.s3_bucket)
            table.add_row("S3 Prefix", config.s3_prefix or "(root)")
            table.add_row("Athena Database", config.athena_database or "[dim]Not ready yet[/dim]")
            table.add_row("Athena Table", config.athena_table or "[dim]Not ready yet[/dim]")
            table.add_row("Workgroup", config.athena_workgroup)
            table.add_row("Region", config.region)
        else:
            table.add_row("Status", "[red]NOT CONFIGURED[/red]")
            table.add_row("Action Required", "Run 'tag-manager cost setup detect' to configure")

        console.print(table)
