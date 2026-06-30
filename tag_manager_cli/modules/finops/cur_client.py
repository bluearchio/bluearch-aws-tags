"""
CUR Client - Athena query layer for AWS Cost and Usage Reports.

Provides a unified interface for querying CUR data via Athena with
automatic caching and fallback to Cost Explorer API when CUR is unavailable.
"""

import hashlib
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Union

from botocore.exceptions import ClientError
from rich.console import Console

from ...utils.aws_auth import aws_auth
from ...utils.cache import cache

console = Console()


@dataclass
class QueryResult:
    """Result from a CUR or Cost Explorer query."""
    data: List[Dict[str, Any]]
    total_cost: float = 0.0
    currency: str = 'USD'
    query_time_ms: int = 0
    from_cache: bool = False
    source: str = 'cur'  # 'cur' or 'cost_explorer'


class CostDataSource(ABC):
    """Abstract base class for cost data sources."""

    @abstractmethod
    def get_costs_by_tag(
        self,
        tag_key: str,
        start_date: date,
        end_date: date,
        granularity: str = 'MONTHLY',
        tag_value: Optional[str] = None,
        additional_group_by: Optional[List[str]] = None
    ) -> QueryResult:
        """Get cost breakdown by tag dimension."""
        pass

    @abstractmethod
    def get_untagged_costs(
        self,
        required_tags: List[str],
        start_date: date,
        end_date: date
    ) -> QueryResult:
        """Get costs for resources missing required tags."""
        pass

    @abstractmethod
    def get_costs_by_service(
        self,
        start_date: date,
        end_date: date,
        tag_filter: Optional[Dict[str, str]] = None
    ) -> QueryResult:
        """Get cost breakdown by AWS service."""
        pass

    @classmethod
    def get_source(cls, cur_config: Optional['CURConfiguration'] = None) -> 'CostDataSource':
        """Get the appropriate data source (CUR preferred, CE fallback)."""
        if cur_config and cur_config.status == 'active':
            try:
                client = CURClient(cur_config)
                # Quick validation
                if client.validate_access():
                    return client
            except Exception as e:
                console.print(f"[yellow][WARN] CUR access failed: {e}[/yellow]")

        console.print("[yellow][WARN] CUR not available, using Cost Explorer (limited detail)[/yellow]")
        return CostExplorerDataSource()


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


class CURClient(CostDataSource):
    """
    Client for querying AWS Cost and Usage Reports via Athena.

    Provides caching, query optimization, and result formatting for
    CUR data stored in S3 and queryable via Athena.
    """

    # Cache TTLs in seconds
    CACHE_TTL_QUERY = 3600      # 1 hour for query results (CUR updates daily)
    CACHE_TTL_SCHEMA = 86400    # 24 hours for schema info

    def __init__(self, config: CURConfiguration):
        """Initialize CUR client with configuration."""
        self.config = config
        self._athena_client = None
        self._s3_client = None

    @property
    def athena_client(self):
        """Lazy-load Athena client."""
        if self._athena_client is None:
            self._athena_client = aws_auth.get_client('athena', region=self.config.region)
        return self._athena_client

    @property
    def s3_client(self):
        """Lazy-load S3 client."""
        if self._s3_client is None:
            self._s3_client = aws_auth.get_client('s3', region=self.config.region)
        return self._s3_client

    def _quote_identifier(self, identifier: str) -> str:
        """Quote an identifier (database/table name) for Athena SQL."""
        # Athena uses double quotes for identifiers with special characters
        return f'"{identifier}"'

    @property
    def table_name(self) -> str:
        """Get the properly quoted table name for SQL queries."""
        return self._quote_identifier(self.config.athena_table)

    def validate_access(self) -> bool:
        """Validate that we can query the CUR data."""
        try:
            # Try a simple query to validate access
            # Use quoted identifiers for names with special characters (hyphens)
            db = self._quote_identifier(self.config.athena_database)
            table = self._quote_identifier(self.config.athena_table)
            test_query = f"SELECT 1 FROM {db}.{table} LIMIT 1"
            self.execute_query(test_query, cache_ttl=0)
            return True
        except Exception as e:
            console.print(f"[red]CUR access validation failed: {e}[/red]")
            return False

    def get_available_tag_columns(self) -> List[str]:
        """
        Discover available tag columns in the CUR table.

        CUR tag columns follow the pattern: resource_tags_user_{tag_name}
        Returns a list of tag names (without the prefix).
        """
        try:
            # Query information_schema to get column names
            db = self._quote_identifier(self.config.athena_database)
            sql = f"""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = '{self.config.athena_database}'
              AND table_name = '{self.config.athena_table}'
              AND column_name LIKE 'resource_tags_user_%'
            ORDER BY column_name
            """

            results = self.execute_query(sql, cache_ttl=self.CACHE_TTL_SCHEMA)

            # Extract tag names from column names
            # Column format: resource_tags_user_{tag_name}
            tag_names = []
            prefix = 'resource_tags_user_'
            for row in results:
                col_name = row.get('column_name', '')
                if col_name.startswith(prefix):
                    # Convert back to readable tag name
                    # Note: underscores in tag names become underscores in column,
                    # so we can't perfectly reverse hyphens, but we can return as-is
                    tag_name = col_name[len(prefix):]
                    tag_names.append(tag_name)

            return tag_names

        except Exception as e:
            console.print(f"[yellow][WARN] Could not discover tag columns: {e}[/yellow]")
            return []

    def _generate_cache_key(self, sql: str, params: Dict = None) -> str:
        """Generate a cache key for a query."""
        key_parts = [sql]
        if params:
            key_parts.append(str(sorted(params.items())))
        key_string = '|'.join(key_parts)
        return f"finops:cur:query:{hashlib.md5(key_string.encode()).hexdigest()}"

    def execute_query(
        self,
        sql: str,
        cache_ttl: int = CACHE_TTL_QUERY,
        params: Dict = None
    ) -> List[Dict[str, Any]]:
        """
        Execute an Athena query with caching.

        Args:
            sql: The SQL query to execute
            cache_ttl: Cache time-to-live in seconds (0 to skip cache)
            params: Optional parameters for cache key generation

        Returns:
            List of result dictionaries
        """
        # Check cache first
        if cache_ttl > 0:
            cache_key = self._generate_cache_key(sql, params)
            cached_result = cache.get(cache_key)
            if cached_result is not None:
                console.print("[dim][CACHE] Using cached CUR data[/dim]")
                return cached_result

        start_time = time.time()

        try:
            # Build output location from CUR S3 bucket
            output_location = f"s3://{self.config.s3_bucket}/athena-results/"

            # Start query execution
            response = self.athena_client.start_query_execution(
                QueryString=sql,
                QueryExecutionContext={
                    'Database': self.config.athena_database
                },
                ResultConfiguration={
                    'OutputLocation': output_location
                },
                WorkGroup=self.config.athena_workgroup
            )

            execution_id = response['QueryExecutionId']

            # Wait for query to complete
            result = self._wait_for_query(execution_id)

            # Cache the result
            if cache_ttl > 0:
                cache.set(cache_key, result, ttl=cache_ttl)

            query_time = int((time.time() - start_time) * 1000)
            console.print(f"[dim]Query completed in {query_time}ms[/dim]")

            return result

        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            error_msg = e.response.get('Error', {}).get('Message', str(e))
            console.print(f"[red]Athena query failed ({error_code}): {error_msg}[/red]")
            raise

    def _wait_for_query(self, execution_id: str, timeout: int = 300) -> List[Dict[str, Any]]:
        """Wait for Athena query to complete and return results."""
        start_time = time.time()

        while True:
            if time.time() - start_time > timeout:
                # Cancel the query
                try:
                    self.athena_client.stop_query_execution(QueryExecutionId=execution_id)
                except Exception:
                    pass
                raise TimeoutError(f"Query timed out after {timeout} seconds")

            response = self.athena_client.get_query_execution(QueryExecutionId=execution_id)
            state = response['QueryExecution']['Status']['State']

            if state == 'SUCCEEDED':
                break
            elif state in ('FAILED', 'CANCELLED'):
                reason = response['QueryExecution']['Status'].get('StateChangeReason', 'Unknown')
                raise Exception(f"Query {state.lower()}: {reason}")

            # Wait before polling again
            time.sleep(0.5)

        # Fetch results
        results = []
        paginator = self.athena_client.get_paginator('get_query_results')

        for page in paginator.paginate(QueryExecutionId=execution_id):
            result_set = page['ResultSet']

            # Get column names from first page
            if not results and 'ResultSetMetadata' in result_set:
                columns = [col['Name'] for col in result_set['ResultSetMetadata']['ColumnInfo']]

            # Process rows (skip header row on first page)
            rows = result_set.get('Rows', [])
            start_idx = 1 if not results else 0  # Skip header on first page

            for row in rows[start_idx:]:
                row_data = {}
                for i, col in enumerate(columns):
                    value = row['Data'][i].get('VarCharValue', None) if i < len(row['Data']) else None
                    row_data[col] = value
                results.append(row_data)

        return results

    def get_costs_by_tag(
        self,
        tag_key: str,
        start_date: date,
        end_date: date,
        granularity: str = 'MONTHLY',
        tag_value: Optional[str] = None,
        additional_group_by: Optional[List[str]] = None
    ) -> QueryResult:
        """Get cost breakdown by tag dimension."""
        # Build the SQL query
        tag_column = f"resource_tags_user_{tag_key.lower().replace('-', '_')}"

        # Determine date grouping
        if granularity == 'DAILY':
            date_group = "line_item_usage_start_date"
            date_format = "DATE(line_item_usage_start_date)"
        else:
            date_group = "DATE_TRUNC('month', line_item_usage_start_date)"
            date_format = date_group

        # Build GROUP BY columns
        group_columns = [date_format, tag_column]
        select_columns = [f"{date_format} as period", f"{tag_column} as tag_value"]

        if additional_group_by:
            for extra_tag in additional_group_by:
                extra_col = f"resource_tags_user_{extra_tag.lower().replace('-', '_')}"
                group_columns.append(extra_col)
                select_columns.append(f"{extra_col} as {extra_tag.lower()}")

        # Build WHERE clause
        where_clauses = [
            f"line_item_usage_start_date >= DATE('{start_date.isoformat()}')",
            f"line_item_usage_start_date < DATE('{end_date.isoformat()}')",
            "line_item_line_item_type IN ('Usage', 'DiscountedUsage', 'SavingsPlanCoveredUsage')"
        ]

        if tag_value:
            where_clauses.append(f"{tag_column} = '{tag_value}'")

        sql = f"""
        SELECT
            {', '.join(select_columns)},
            SUM(line_item_unblended_cost) as cost,
            SUM(line_item_blended_cost) as blended_cost
        FROM {self.table_name}
        WHERE {' AND '.join(where_clauses)}
        GROUP BY {', '.join(group_columns)}
        ORDER BY period DESC, cost DESC
        """

        start_time = time.time()
        try:
            results = self.execute_query(
                sql,
                params={'tag_key': tag_key, 'start': str(start_date), 'end': str(end_date)}
            )
        except Exception as e:
            if 'COLUMN_NOT_FOUND' in str(e):
                console.print(f"[yellow][WARN] Tag column '{tag_column}' not found in CUR table.[/yellow]")
                console.print(f"[dim]This means no resources have the '{tag_key}' tag applied in AWS.[/dim]")
                console.print(f"[dim]Apply the tag to resources and wait for CUR data refresh (~24h).[/dim]")
                return QueryResult(data=[], total_cost=0, query_time_ms=0, source='cur')
            raise
        query_time = int((time.time() - start_time) * 1000)

        # Calculate total
        total_cost = sum(float(r.get('cost', 0) or 0) for r in results)

        return QueryResult(
            data=results,
            total_cost=total_cost,
            query_time_ms=query_time,
            source='cur'
        )

    def get_untagged_costs(
        self,
        required_tags: List[str],
        start_date: date,
        end_date: date
    ) -> QueryResult:
        """Get costs for resources missing required tags."""
        # Build conditions for missing tags
        tag_conditions = []
        tag_columns_used = []
        for tag in required_tags:
            tag_column = f"resource_tags_user_{tag.lower().replace('-', '_')}"
            tag_columns_used.append((tag, tag_column))
            tag_conditions.append(f"({tag_column} IS NULL OR {tag_column} = '')")

        sql = f"""
        SELECT
            product_product_name as service,
            line_item_resource_id as resource_id,
            SUM(line_item_unblended_cost) as cost,
            COUNT(DISTINCT line_item_resource_id) as resource_count
        FROM {self.table_name}
        WHERE line_item_usage_start_date >= DATE('{start_date.isoformat()}')
            AND line_item_usage_start_date < DATE('{end_date.isoformat()}')
            AND line_item_line_item_type IN ('Usage', 'DiscountedUsage', 'SavingsPlanCoveredUsage')
            AND ({' OR '.join(tag_conditions)})
            AND line_item_resource_id IS NOT NULL
            AND line_item_resource_id != ''
        GROUP BY product_product_name, line_item_resource_id
        HAVING SUM(line_item_unblended_cost) > 0.01
        ORDER BY cost DESC
        LIMIT 1000
        """

        start_time = time.time()
        try:
            results = self.execute_query(
                sql,
                params={'tags': ','.join(required_tags), 'start': str(start_date), 'end': str(end_date)}
            )
        except Exception as e:
            if 'COLUMN_NOT_FOUND' in str(e):
                # Find which tag column is missing from the error message
                missing_tags = []
                for tag, col in tag_columns_used:
                    if col in str(e):
                        missing_tags.append(tag)

                if missing_tags:
                    console.print(f"[yellow][WARN] Tag column(s) not found in CUR: {', '.join(missing_tags)}[/yellow]")
                else:
                    console.print(f"[yellow][WARN] One or more tag columns not found in CUR table.[/yellow]")
                console.print(f"[dim]The following tags were requested: {', '.join(required_tags)}[/dim]")
                console.print(f"[dim]Tag columns only exist if resources have those tags applied.[/dim]")
                console.print(f"[dim]Apply tags to resources and wait for CUR data refresh (~24h).[/dim]")
                return QueryResult(data=[], total_cost=0, query_time_ms=0, source='cur')
            raise
        query_time = int((time.time() - start_time) * 1000)

        total_cost = sum(float(r.get('cost', 0) or 0) for r in results)

        return QueryResult(
            data=results,
            total_cost=total_cost,
            query_time_ms=query_time,
            source='cur'
        )

    def get_costs_by_service(
        self,
        start_date: date,
        end_date: date,
        tag_filter: Optional[Dict[str, str]] = None
    ) -> QueryResult:
        """Get cost breakdown by AWS service."""
        where_clauses = [
            f"line_item_usage_start_date >= DATE('{start_date.isoformat()}')",
            f"line_item_usage_start_date < DATE('{end_date.isoformat()}')",
            "line_item_line_item_type IN ('Usage', 'DiscountedUsage', 'SavingsPlanCoveredUsage')"
        ]

        if tag_filter:
            for tag_key, tag_value in tag_filter.items():
                tag_column = f"resource_tags_user_{tag_key.lower().replace('-', '_')}"
                where_clauses.append(f"{tag_column} = '{tag_value}'")

        sql = f"""
        SELECT
            product_product_name as service,
            SUM(line_item_unblended_cost) as cost,
            SUM(line_item_blended_cost) as blended_cost
        FROM {self.table_name}
        WHERE {' AND '.join(where_clauses)}
        GROUP BY product_product_name
        HAVING SUM(line_item_unblended_cost) > 0.01
        ORDER BY cost DESC
        """

        start_time = time.time()
        results = self.execute_query(
            sql,
            params={'start': str(start_date), 'end': str(end_date), 'filter': str(tag_filter)}
        )
        query_time = int((time.time() - start_time) * 1000)

        total_cost = sum(float(r.get('cost', 0) or 0) for r in results)

        return QueryResult(
            data=results,
            total_cost=total_cost,
            query_time_ms=query_time,
            source='cur'
        )

    # =========================================================================
    # ENHANCED CUR QUERIES (AWS Best Practices from CUR Query Library)
    # =========================================================================

    def get_costs_by_account(
        self,
        start_date: date,
        end_date: date,
        include_services: bool = False
    ) -> QueryResult:
        """
        Get cost breakdown by AWS account (linked accounts).

        Based on AWS CUR Query Library best practices.
        """
        group_cols = ["line_item_usage_account_id"]
        select_cols = ["line_item_usage_account_id as account_id"]

        if include_services:
            group_cols.append("product_product_name")
            select_cols.append("product_product_name as service")

        # Simplified query using only core columns
        # Amortized cost = unblended cost when SP/RI columns not available
        sql = f"""
        SELECT
            {', '.join(select_cols)},
            SUM(line_item_unblended_cost) as unblended_cost,
            SUM(line_item_blended_cost) as blended_cost
        FROM {self.table_name}
        WHERE line_item_usage_start_date >= DATE('{start_date.isoformat()}')
            AND line_item_usage_start_date < DATE('{end_date.isoformat()}')
        GROUP BY {', '.join(group_cols)}
        HAVING SUM(line_item_unblended_cost) > 0.01
        ORDER BY unblended_cost DESC
        """

        start_time = time.time()
        results = self.execute_query(sql)
        query_time = int((time.time() - start_time) * 1000)

        # Add amortized_cost as alias for unblended_cost for compatibility
        for r in results:
            r['amortized_cost'] = r.get('unblended_cost', 0)

        total_cost = sum(float(r.get('unblended_cost', 0) or 0) for r in results)

        return QueryResult(data=results, total_cost=total_cost, query_time_ms=query_time, source='cur')

    def get_pricing_model_breakdown(
        self,
        start_date: date,
        end_date: date
    ) -> QueryResult:
        """
        Get cost breakdown by pricing model (On-Demand, Savings Plans, Reserved, Spot).

        Based on AWS CUR Query Library: EC2 pricing model analysis.
        Uses line_item_line_item_type for categorization (works with all CUR configs).
        """
        sql = f"""
        SELECT
            CASE
                WHEN line_item_usage_type LIKE '%SpotUsage%' THEN 'Spot'
                WHEN line_item_line_item_type = 'SavingsPlanCoveredUsage' THEN 'Savings Plans'
                WHEN line_item_line_item_type = 'SavingsPlanNegation' THEN 'Savings Plans'
                WHEN line_item_line_item_type = 'DiscountedUsage' THEN 'Reserved Instance'
                WHEN line_item_line_item_type = 'Usage' THEN 'On-Demand'
                ELSE 'Other'
            END AS pricing_model,
            product_product_name as service,
            SUM(line_item_unblended_cost) as unblended_cost,
            SUM(line_item_unblended_cost) as effective_cost
        FROM {self.table_name}
        WHERE line_item_usage_start_date >= DATE('{start_date.isoformat()}')
            AND line_item_usage_start_date < DATE('{end_date.isoformat()}')
            AND line_item_line_item_type IN ('Usage', 'DiscountedUsage', 'SavingsPlanCoveredUsage', 'SavingsPlanNegation')
        GROUP BY 1, 2
        HAVING SUM(line_item_unblended_cost) > 0.01
        ORDER BY effective_cost DESC
        """

        start_time = time.time()
        results = self.execute_query(sql)
        query_time = int((time.time() - start_time) * 1000)
        total_cost = sum(float(r.get('effective_cost', 0) or 0) for r in results)

        return QueryResult(data=results, total_cost=total_cost, query_time_ms=query_time, source='cur')

    def get_savings_plans_coverage(
        self,
        start_date: date,
        end_date: date
    ) -> QueryResult:
        """
        Get Savings Plans coverage and utilization metrics.

        Based on AWS CUR Query Library: Savings Plan inventory and utilization.
        Note: Requires savings_plan_* columns which may not be present in all CUR configs.
        """
        sql = f"""
        SELECT
            SPLIT_PART(savings_plan_savings_plan_a_r_n, '/', 2) AS savings_plan_id,
            bill_payer_account_id as payer_account,
            line_item_usage_account_id as usage_account,
            DATE_FORMAT(line_item_usage_start_date, '%Y-%m') AS month,
            savings_plan_offering_type as offering_type,
            savings_plan_payment_option as payment_option,
            savings_plan_purchase_term as term,
            CAST(SUM(savings_plan_total_commitment_to_date) AS DECIMAL(16,2)) AS total_commitment,
            CAST(SUM(savings_plan_used_commitment) AS DECIMAL(16,2)) AS used_commitment,
            CAST(SUM(savings_plan_total_commitment_to_date) - SUM(savings_plan_used_commitment) AS DECIMAL(16,2)) AS unused_commitment,
            CAST((SUM(savings_plan_used_commitment) / NULLIF(SUM(savings_plan_total_commitment_to_date), 0)) * 100 AS DECIMAL(5,2)) AS utilization_percent
        FROM {self.table_name}
        WHERE line_item_usage_start_date >= DATE('{start_date.isoformat()}')
            AND line_item_usage_start_date < DATE('{end_date.isoformat()}')
            AND savings_plan_savings_plan_a_r_n <> ''
            AND line_item_line_item_type = 'SavingsPlanRecurringFee'
        GROUP BY 1, 2, 3, 4, 5, 6, 7
        ORDER BY utilization_percent ASC, unused_commitment DESC
        """

        start_time = time.time()
        try:
            results = self.execute_query(sql)
        except Exception as e:
            if 'COLUMN_NOT_FOUND' in str(e):
                console.print("[yellow][WARN] Savings Plans columns not available in this CUR configuration.[/yellow]")
                console.print("[dim]This may indicate no Savings Plans usage or CUR configured without SP columns.[/dim]")
                return QueryResult(data=[], total_cost=0, query_time_ms=0, source='cur')
            raise

        query_time = int((time.time() - start_time) * 1000)

        # Calculate overall metrics
        total_commitment = sum(float(r.get('total_commitment', 0) or 0) for r in results)
        total_used = sum(float(r.get('used_commitment', 0) or 0) for r in results)

        return QueryResult(
            data=results,
            total_cost=total_commitment,
            query_time_ms=query_time,
            source='cur'
        )

    def get_reserved_instance_utilization(
        self,
        start_date: date,
        end_date: date
    ) -> QueryResult:
        """
        Get Reserved Instance utilization metrics.

        Based on AWS CUR Query Library: EC2 Reservation utilization.
        Note: Requires reservation_* columns which may not be present in all CUR configs.
        """
        sql = f"""
        SELECT
            bill_payer_account_id as payer_account,
            line_item_usage_account_id as usage_account,
            DATE_FORMAT(line_item_usage_start_date, '%Y-%m') AS month,
            line_item_product_code as product,
            product_region as region,
            line_item_usage_type as usage_type,
            reservation_reservation_a_r_n as ri_arn,
            pricing_lease_contract_length as term,
            reservation_number_of_reservations as quantity,
            CAST(reservation_total_reserved_units AS DECIMAL(16,2)) AS reserved_units,
            CAST(reservation_unused_quantity AS DECIMAL(16,2)) AS unused_units,
            CAST((1 - (reservation_unused_quantity / NULLIF(CAST(reservation_total_reserved_units AS DECIMAL(16,8)), 0))) * 100 AS DECIMAL(5,2)) AS utilization_percent
        FROM {self.table_name}
        WHERE line_item_usage_start_date >= DATE('{start_date.isoformat()}')
            AND line_item_usage_start_date < DATE('{end_date.isoformat()}')
            AND pricing_term = 'Reserved'
            AND line_item_line_item_type IN ('Fee', 'RIFee')
            AND reservation_reservation_a_r_n <> ''
        GROUP BY 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11
        ORDER BY utilization_percent ASC, unused_units DESC
        """

        start_time = time.time()
        try:
            results = self.execute_query(sql)
        except Exception as e:
            if 'COLUMN_NOT_FOUND' in str(e):
                console.print("[yellow][WARN] Reserved Instance columns not available in this CUR configuration.[/yellow]")
                console.print("[dim]This may indicate no RI usage or CUR configured without RI columns.[/dim]")
                return QueryResult(data=[], total_cost=0, query_time_ms=0, source='cur')
            raise

        query_time = int((time.time() - start_time) * 1000)

        return QueryResult(data=results, total_cost=0, query_time_ms=query_time, source='cur')

    def get_top_cost_resources(
        self,
        start_date: date,
        end_date: date,
        limit: int = 50
    ) -> QueryResult:
        """
        Get top cost-driving resources with amortized costs.

        Based on AWS CUR Query Library best practices.
        """
        # Simplified query using only core columns
        sql = f"""
        SELECT
            line_item_usage_account_id as account_id,
            product_product_name as service,
            line_item_resource_id as resource_id,
            product_region as region,
            SUM(line_item_usage_amount) as usage_amount,
            SUM(line_item_unblended_cost) as unblended_cost
        FROM {self.table_name}
        WHERE line_item_usage_start_date >= DATE('{start_date.isoformat()}')
            AND line_item_usage_start_date < DATE('{end_date.isoformat()}')
            AND line_item_line_item_type IN ('Usage', 'DiscountedUsage', 'SavingsPlanCoveredUsage')
            AND line_item_resource_id IS NOT NULL
            AND line_item_resource_id != ''
        GROUP BY 1, 2, 3, 4
        HAVING SUM(line_item_unblended_cost) > 1.00
        ORDER BY unblended_cost DESC
        LIMIT {limit}
        """

        start_time = time.time()
        results = self.execute_query(sql)
        query_time = int((time.time() - start_time) * 1000)

        # Add amortized_cost as alias for unblended_cost for compatibility
        for r in results:
            r['amortized_cost'] = r.get('unblended_cost', 0)

        total_cost = sum(float(r.get('unblended_cost', 0) or 0) for r in results)

        return QueryResult(data=results, total_cost=total_cost, query_time_ms=query_time, source='cur')

    def get_data_transfer_costs(
        self,
        start_date: date,
        end_date: date
    ) -> QueryResult:
        """
        Get data transfer costs breakdown (often a hidden cost driver).

        Based on AWS best practices for identifying data transfer spend.
        """
        sql = f"""
        SELECT
            line_item_usage_account_id as account_id,
            product_product_name as service,
            CASE
                WHEN line_item_usage_type LIKE '%DataTransfer-In%' THEN 'Data Transfer IN'
                WHEN line_item_usage_type LIKE '%DataTransfer-Out%' THEN 'Data Transfer OUT'
                WHEN line_item_usage_type LIKE '%DataTransfer-Regional%' THEN 'Regional Transfer'
                WHEN line_item_usage_type LIKE '%DataTransfer%' THEN 'Other Transfer'
                WHEN product_product_family = 'Data Transfer' THEN 'Data Transfer'
                ELSE 'Other'
            END AS transfer_type,
            product_from_location as from_location,
            product_to_location as to_location,
            SUM(line_item_usage_amount) as usage_gb,
            SUM(line_item_unblended_cost) as cost
        FROM {self.table_name}
        WHERE line_item_usage_start_date >= DATE('{start_date.isoformat()}')
            AND line_item_usage_start_date < DATE('{end_date.isoformat()}')
            AND (product_product_family = 'Data Transfer'
                 OR line_item_usage_type LIKE '%DataTransfer%'
                 OR line_item_usage_type LIKE '%Bytes%')
            AND line_item_line_item_type IN ('Usage', 'DiscountedUsage', 'SavingsPlanCoveredUsage')
        GROUP BY 1, 2, 3, 4, 5
        HAVING SUM(line_item_unblended_cost) > 0.01
        ORDER BY cost DESC
        """

        start_time = time.time()
        results = self.execute_query(sql)
        query_time = int((time.time() - start_time) * 1000)
        total_cost = sum(float(r.get('cost', 0) or 0) for r in results)

        return QueryResult(data=results, total_cost=total_cost, query_time_ms=query_time, source='cur')

    def get_daily_cost_summary(
        self,
        start_date: date,
        end_date: date
    ) -> QueryResult:
        """
        Get daily cost summary.

        Useful for identifying daily cost spikes and trends.
        Note: Uses unblended cost only; amortized costs require SP/RI columns
        which may not be present in all CUR configurations.
        """
        sql = f"""
        SELECT
            DATE(line_item_usage_start_date) as date,
            SUM(line_item_unblended_cost) as unblended_cost,
            SUM(line_item_blended_cost) as blended_cost
        FROM {self.table_name}
        WHERE line_item_usage_start_date >= DATE('{start_date.isoformat()}')
            AND line_item_usage_start_date < DATE('{end_date.isoformat()}')
        GROUP BY 1
        ORDER BY 1 DESC
        """

        start_time = time.time()
        results = self.execute_query(sql)
        query_time = int((time.time() - start_time) * 1000)

        # Add amortized_cost as alias for unblended_cost for compatibility
        for r in results:
            r['amortized_cost'] = r.get('unblended_cost', 0)

        total_cost = sum(float(r.get('unblended_cost', 0) or 0) for r in results)

        return QueryResult(data=results, total_cost=total_cost, query_time_ms=query_time, source='cur')

    def get_cost_summary(
        self,
        start_date: date,
        end_date: date
    ) -> QueryResult:
        """
        Get comprehensive cost summary with all charge types.

        Based on AWS CUR Query Library: Aggregate charge types.
        """
        # Simplified query using only core CUR columns
        # Advanced columns like reservation_* may not exist in all CUR tables
        sql = f"""
        SELECT
            CASE
                WHEN line_item_line_item_type = 'Fee' AND product_product_name = 'AWS Premium Support' THEN 'Support Fee'
                WHEN line_item_line_item_type = 'Fee' THEN 'Fee'
                WHEN line_item_line_item_type = 'SavingsPlanUpfrontFee' THEN 'SP Upfront Fee'
                WHEN line_item_line_item_type = 'SavingsPlanRecurringFee' THEN 'SP Recurring Fee'
                WHEN line_item_line_item_type = 'SavingsPlanCoveredUsage' THEN 'SP Covered Usage'
                WHEN line_item_line_item_type = 'SavingsPlanNegation' THEN 'SP Negation'
                WHEN line_item_line_item_type = 'DiscountedUsage' THEN 'RI Usage'
                WHEN line_item_line_item_type = 'RIFee' THEN 'RI Fee'
                WHEN line_item_line_item_type = 'Usage' THEN 'On-Demand Usage'
                WHEN line_item_line_item_type = 'Tax' THEN 'Tax'
                WHEN line_item_line_item_type = 'Credit' THEN 'Credit'
                WHEN line_item_line_item_type = 'Refund' THEN 'Refund'
                ELSE line_item_line_item_type
            END AS charge_type,
            COUNT(*) as line_count,
            CAST(SUM(line_item_unblended_cost) AS DECIMAL(16,2)) as unblended_cost
        FROM {self.table_name}
        WHERE line_item_usage_start_date >= DATE('{start_date.isoformat()}')
            AND line_item_usage_start_date < DATE('{end_date.isoformat()}')
        GROUP BY 1
        ORDER BY unblended_cost DESC
        """

        start_time = time.time()
        results = self.execute_query(sql)
        query_time = int((time.time() - start_time) * 1000)
        total_cost = sum(float(r.get('unblended_cost', 0) or 0) for r in results)

        return QueryResult(data=results, total_cost=total_cost, query_time_ms=query_time, source='cur')

    # =========================================================================
    # SERVICE-SPECIFIC QUERIES (EC2, S3, RDS, Lambda)
    # =========================================================================

    def get_ec2_costs_by_instance_type(
        self,
        start_date: date,
        end_date: date,
        limit: int = 50
    ) -> QueryResult:
        """Get EC2 costs breakdown by instance type."""
        sql = f"""
        SELECT
            product_instance_type as instance_type,
            product_operating_system as operating_system,
            product_tenancy as tenancy,
            SUM(line_item_usage_amount) as usage_hours,
            SUM(line_item_unblended_cost) as cost
        FROM {self.table_name}
        WHERE line_item_usage_start_date >= DATE('{start_date.isoformat()}')
            AND line_item_usage_start_date < DATE('{end_date.isoformat()}')
            AND line_item_product_code = 'AmazonEC2'
            AND line_item_usage_type LIKE '%BoxUsage%'
            AND product_instance_type IS NOT NULL
            AND product_instance_type != ''
        GROUP BY 1, 2, 3
        HAVING SUM(line_item_unblended_cost) > 0.01
        ORDER BY cost DESC
        LIMIT {limit}
        """
        start_time = time.time()
        results = self.execute_query(sql)
        query_time = int((time.time() - start_time) * 1000)
        total_cost = sum(float(r.get('cost', 0) or 0) for r in results)
        return QueryResult(data=results, total_cost=total_cost, query_time_ms=query_time, source='cur')

    def get_ec2_costs_by_family(
        self,
        start_date: date,
        end_date: date
    ) -> QueryResult:
        """Get EC2 costs breakdown by instance family (t3, m5, c5, etc.)."""
        sql = f"""
        SELECT
            CASE
                WHEN product_instance_type LIKE 't2.%' THEN 't2'
                WHEN product_instance_type LIKE 't3.%' THEN 't3'
                WHEN product_instance_type LIKE 't3a.%' THEN 't3a'
                WHEN product_instance_type LIKE 't4g.%' THEN 't4g'
                WHEN product_instance_type LIKE 'm4.%' THEN 'm4'
                WHEN product_instance_type LIKE 'm5.%' THEN 'm5'
                WHEN product_instance_type LIKE 'm5a.%' THEN 'm5a'
                WHEN product_instance_type LIKE 'm6i.%' THEN 'm6i'
                WHEN product_instance_type LIKE 'm6g.%' THEN 'm6g'
                WHEN product_instance_type LIKE 'm7i.%' THEN 'm7i'
                WHEN product_instance_type LIKE 'c5.%' THEN 'c5'
                WHEN product_instance_type LIKE 'c5a.%' THEN 'c5a'
                WHEN product_instance_type LIKE 'c6i.%' THEN 'c6i'
                WHEN product_instance_type LIKE 'c6g.%' THEN 'c6g'
                WHEN product_instance_type LIKE 'c7i.%' THEN 'c7i'
                WHEN product_instance_type LIKE 'r5.%' THEN 'r5'
                WHEN product_instance_type LIKE 'r6i.%' THEN 'r6i'
                WHEN product_instance_type LIKE 'r6g.%' THEN 'r6g'
                WHEN product_instance_type LIKE 'i3.%' THEN 'i3'
                WHEN product_instance_type LIKE 'i4i.%' THEN 'i4i'
                WHEN product_instance_type LIKE 'g4dn.%' THEN 'g4dn'
                WHEN product_instance_type LIKE 'g5.%' THEN 'g5'
                WHEN product_instance_type LIKE 'p3.%' THEN 'p3'
                WHEN product_instance_type LIKE 'p4d.%' THEN 'p4d'
                ELSE SPLIT_PART(product_instance_type, '.', 1)
            END AS instance_family,
            COUNT(DISTINCT product_instance_type) as instance_type_count,
            SUM(line_item_usage_amount) as usage_hours,
            SUM(line_item_unblended_cost) as cost
        FROM {self.table_name}
        WHERE line_item_usage_start_date >= DATE('{start_date.isoformat()}')
            AND line_item_usage_start_date < DATE('{end_date.isoformat()}')
            AND line_item_product_code = 'AmazonEC2'
            AND line_item_usage_type LIKE '%BoxUsage%'
            AND product_instance_type IS NOT NULL
            AND product_instance_type != ''
        GROUP BY 1
        HAVING SUM(line_item_unblended_cost) > 0.01
        ORDER BY cost DESC
        """
        start_time = time.time()
        results = self.execute_query(sql)
        query_time = int((time.time() - start_time) * 1000)
        total_cost = sum(float(r.get('cost', 0) or 0) for r in results)
        return QueryResult(data=results, total_cost=total_cost, query_time_ms=query_time, source='cur')

    def get_ec2_pricing_breakdown(
        self,
        start_date: date,
        end_date: date
    ) -> QueryResult:
        """Get EC2-specific pricing model breakdown (On-Demand, Spot, SP, RI)."""
        sql = f"""
        SELECT
            CASE
                WHEN line_item_usage_type LIKE '%SpotUsage%' THEN 'Spot'
                WHEN line_item_line_item_type = 'SavingsPlanCoveredUsage' THEN 'Savings Plans'
                WHEN line_item_line_item_type = 'DiscountedUsage' THEN 'Reserved Instance'
                WHEN line_item_line_item_type = 'Usage' THEN 'On-Demand'
                ELSE 'Other'
            END AS pricing_model,
            SUM(line_item_usage_amount) as usage_hours,
            SUM(line_item_unblended_cost) as cost
        FROM {self.table_name}
        WHERE line_item_usage_start_date >= DATE('{start_date.isoformat()}')
            AND line_item_usage_start_date < DATE('{end_date.isoformat()}')
            AND line_item_product_code = 'AmazonEC2'
            AND line_item_usage_type LIKE '%BoxUsage%'
        GROUP BY 1
        HAVING SUM(line_item_unblended_cost) > 0.01
        ORDER BY cost DESC
        """
        start_time = time.time()
        results = self.execute_query(sql)
        query_time = int((time.time() - start_time) * 1000)
        total_cost = sum(float(r.get('cost', 0) or 0) for r in results)
        return QueryResult(data=results, total_cost=total_cost, query_time_ms=query_time, source='cur')

    def get_s3_costs_by_bucket(
        self,
        start_date: date,
        end_date: date,
        limit: int = 50
    ) -> QueryResult:
        """Get S3 costs breakdown by bucket."""
        sql = f"""
        SELECT
            CASE
                WHEN line_item_resource_id LIKE 'arn:aws:s3:::%'
                    THEN SPLIT_PART(line_item_resource_id, ':::', 2)
                WHEN line_item_resource_id != ''
                    THEN line_item_resource_id
                ELSE 'Unknown'
            END AS bucket_name,
            SUM(line_item_usage_amount) as usage_amount,
            SUM(line_item_unblended_cost) as cost
        FROM {self.table_name}
        WHERE line_item_usage_start_date >= DATE('{start_date.isoformat()}')
            AND line_item_usage_start_date < DATE('{end_date.isoformat()}')
            AND line_item_product_code = 'AmazonS3'
        GROUP BY 1
        HAVING SUM(line_item_unblended_cost) > 0.01
        ORDER BY cost DESC
        LIMIT {limit}
        """
        start_time = time.time()
        results = self.execute_query(sql)
        query_time = int((time.time() - start_time) * 1000)
        total_cost = sum(float(r.get('cost', 0) or 0) for r in results)
        return QueryResult(data=results, total_cost=total_cost, query_time_ms=query_time, source='cur')

    def get_s3_costs_by_storage_class(
        self,
        start_date: date,
        end_date: date
    ) -> QueryResult:
        """Get S3 costs breakdown by storage class."""
        sql = f"""
        SELECT
            CASE
                WHEN line_item_usage_type LIKE '%TimedStorage-ByteHrs%' THEN 'Standard'
                WHEN line_item_usage_type LIKE '%TimedStorage-SIA-ByteHrs%' THEN 'Standard-IA'
                WHEN line_item_usage_type LIKE '%TimedStorage-ZIA-ByteHrs%' THEN 'One Zone-IA'
                WHEN line_item_usage_type LIKE '%TimedStorage-GlacierByteHrs%' THEN 'Glacier Flexible'
                WHEN line_item_usage_type LIKE '%TimedStorage-GDA-ByteHrs%' THEN 'Glacier Deep Archive'
                WHEN line_item_usage_type LIKE '%TimedStorage-INT-FA-ByteHrs%' THEN 'Intelligent-Tiering FA'
                WHEN line_item_usage_type LIKE '%TimedStorage-INT-IA-ByteHrs%' THEN 'Intelligent-Tiering IA'
                WHEN line_item_usage_type LIKE '%TimedStorage%' THEN 'Other Storage'
                WHEN line_item_usage_type LIKE '%Requests%' THEN 'Requests'
                WHEN line_item_usage_type LIKE '%DataTransfer%' THEN 'Data Transfer'
                ELSE 'Other'
            END AS storage_class,
            SUM(line_item_usage_amount) as usage_amount,
            SUM(line_item_unblended_cost) as cost
        FROM {self.table_name}
        WHERE line_item_usage_start_date >= DATE('{start_date.isoformat()}')
            AND line_item_usage_start_date < DATE('{end_date.isoformat()}')
            AND line_item_product_code = 'AmazonS3'
        GROUP BY 1
        HAVING SUM(line_item_unblended_cost) > 0.01
        ORDER BY cost DESC
        """
        start_time = time.time()
        results = self.execute_query(sql)
        query_time = int((time.time() - start_time) * 1000)
        total_cost = sum(float(r.get('cost', 0) or 0) for r in results)
        return QueryResult(data=results, total_cost=total_cost, query_time_ms=query_time, source='cur')

    def get_s3_costs_by_operation(
        self,
        start_date: date,
        end_date: date
    ) -> QueryResult:
        """Get S3 costs breakdown by operation type (GET, PUT, etc.)."""
        sql = f"""
        SELECT
            line_item_operation as operation,
            SUM(line_item_usage_amount) as request_count,
            SUM(line_item_unblended_cost) as cost
        FROM {self.table_name}
        WHERE line_item_usage_start_date >= DATE('{start_date.isoformat()}')
            AND line_item_usage_start_date < DATE('{end_date.isoformat()}')
            AND line_item_product_code = 'AmazonS3'
            AND line_item_operation IS NOT NULL
            AND line_item_operation != ''
        GROUP BY 1
        HAVING SUM(line_item_unblended_cost) > 0.01
        ORDER BY cost DESC
        """
        start_time = time.time()
        results = self.execute_query(sql)
        query_time = int((time.time() - start_time) * 1000)
        total_cost = sum(float(r.get('cost', 0) or 0) for r in results)
        return QueryResult(data=results, total_cost=total_cost, query_time_ms=query_time, source='cur')

    def get_rds_costs_by_engine(
        self,
        start_date: date,
        end_date: date
    ) -> QueryResult:
        """Get RDS costs breakdown by database engine."""
        sql = f"""
        SELECT
            product_database_engine as engine,
            COUNT(DISTINCT line_item_resource_id) as instance_count,
            SUM(line_item_usage_amount) as usage_hours,
            SUM(line_item_unblended_cost) as cost
        FROM {self.table_name}
        WHERE line_item_usage_start_date >= DATE('{start_date.isoformat()}')
            AND line_item_usage_start_date < DATE('{end_date.isoformat()}')
            AND line_item_product_code = 'AmazonRDS'
            AND product_database_engine IS NOT NULL
            AND product_database_engine != ''
        GROUP BY 1
        HAVING SUM(line_item_unblended_cost) > 0.01
        ORDER BY cost DESC
        """
        start_time = time.time()
        results = self.execute_query(sql)
        query_time = int((time.time() - start_time) * 1000)
        total_cost = sum(float(r.get('cost', 0) or 0) for r in results)
        return QueryResult(data=results, total_cost=total_cost, query_time_ms=query_time, source='cur')

    def get_rds_costs_by_instance_type(
        self,
        start_date: date,
        end_date: date,
        limit: int = 50
    ) -> QueryResult:
        """Get RDS costs breakdown by instance type."""
        sql = f"""
        SELECT
            product_instance_type as instance_type,
            product_database_engine as engine,
            SUM(line_item_usage_amount) as usage_hours,
            SUM(line_item_unblended_cost) as cost
        FROM {self.table_name}
        WHERE line_item_usage_start_date >= DATE('{start_date.isoformat()}')
            AND line_item_usage_start_date < DATE('{end_date.isoformat()}')
            AND line_item_product_code = 'AmazonRDS'
            AND product_instance_type IS NOT NULL
            AND product_instance_type != ''
            AND line_item_usage_type LIKE '%InstanceUsage%'
        GROUP BY 1, 2
        HAVING SUM(line_item_unblended_cost) > 0.01
        ORDER BY cost DESC
        LIMIT {limit}
        """
        start_time = time.time()
        results = self.execute_query(sql)
        query_time = int((time.time() - start_time) * 1000)
        total_cost = sum(float(r.get('cost', 0) or 0) for r in results)
        return QueryResult(data=results, total_cost=total_cost, query_time_ms=query_time, source='cur')

    def get_rds_costs_breakdown(
        self,
        start_date: date,
        end_date: date
    ) -> QueryResult:
        """Get RDS costs breakdown by charge category (Instance, Storage, I/O)."""
        sql = f"""
        SELECT
            CASE
                WHEN line_item_usage_type LIKE '%InstanceUsage%' THEN 'Instance'
                WHEN line_item_usage_type LIKE '%StorageUsage%' THEN 'Storage'
                WHEN line_item_usage_type LIKE '%IOPS%' THEN 'Provisioned IOPS'
                WHEN line_item_usage_type LIKE '%IOUsage%' THEN 'I/O Requests'
                WHEN line_item_usage_type LIKE '%DataTransfer%' THEN 'Data Transfer'
                WHEN line_item_usage_type LIKE '%BackupUsage%' THEN 'Backup'
                WHEN line_item_usage_type LIKE '%Snapshot%' THEN 'Snapshots'
                ELSE 'Other'
            END AS charge_category,
            SUM(line_item_unblended_cost) as cost
        FROM {self.table_name}
        WHERE line_item_usage_start_date >= DATE('{start_date.isoformat()}')
            AND line_item_usage_start_date < DATE('{end_date.isoformat()}')
            AND line_item_product_code = 'AmazonRDS'
        GROUP BY 1
        HAVING SUM(line_item_unblended_cost) > 0.01
        ORDER BY cost DESC
        """
        start_time = time.time()
        results = self.execute_query(sql)
        query_time = int((time.time() - start_time) * 1000)
        total_cost = sum(float(r.get('cost', 0) or 0) for r in results)
        return QueryResult(data=results, total_cost=total_cost, query_time_ms=query_time, source='cur')

    def get_lambda_costs_by_memory(
        self,
        start_date: date,
        end_date: date
    ) -> QueryResult:
        """Get Lambda costs breakdown by memory tier."""
        sql = f"""
        SELECT
            CASE
                WHEN line_item_usage_type LIKE '%Lambda-GB-Second%' THEN 'Duration (GB-Seconds)'
                WHEN line_item_usage_type LIKE '%Request%' THEN 'Requests'
                WHEN line_item_usage_type LIKE '%Lambda-Provisioned%' THEN 'Provisioned Concurrency'
                WHEN line_item_usage_type LIKE '%DataTransfer%' THEN 'Data Transfer'
                ELSE 'Other'
            END AS charge_type,
            SUM(line_item_usage_amount) as usage_amount,
            SUM(line_item_unblended_cost) as cost
        FROM {self.table_name}
        WHERE line_item_usage_start_date >= DATE('{start_date.isoformat()}')
            AND line_item_usage_start_date < DATE('{end_date.isoformat()}')
            AND line_item_product_code = 'AWSLambda'
        GROUP BY 1
        HAVING SUM(line_item_unblended_cost) > 0.01
        ORDER BY cost DESC
        """
        start_time = time.time()
        results = self.execute_query(sql)
        query_time = int((time.time() - start_time) * 1000)
        total_cost = sum(float(r.get('cost', 0) or 0) for r in results)
        return QueryResult(data=results, total_cost=total_cost, query_time_ms=query_time, source='cur')

    def get_lambda_costs_by_function(
        self,
        start_date: date,
        end_date: date,
        limit: int = 50
    ) -> QueryResult:
        """Get Lambda costs breakdown by function (requires resource-level reporting)."""
        sql = f"""
        SELECT
            CASE
                WHEN line_item_resource_id LIKE 'arn:aws:lambda:%'
                    THEN SPLIT_PART(line_item_resource_id, ':', 7)
                ELSE 'Unknown'
            END AS function_name,
            SUM(line_item_usage_amount) as invocations,
            SUM(line_item_unblended_cost) as cost
        FROM {self.table_name}
        WHERE line_item_usage_start_date >= DATE('{start_date.isoformat()}')
            AND line_item_usage_start_date < DATE('{end_date.isoformat()}')
            AND line_item_product_code = 'AWSLambda'
            AND line_item_resource_id IS NOT NULL
            AND line_item_resource_id != ''
        GROUP BY 1
        HAVING SUM(line_item_unblended_cost) > 0.01
        ORDER BY cost DESC
        LIMIT {limit}
        """
        start_time = time.time()
        results = self.execute_query(sql)
        query_time = int((time.time() - start_time) * 1000)
        total_cost = sum(float(r.get('cost', 0) or 0) for r in results)
        return QueryResult(data=results, total_cost=total_cost, query_time_ms=query_time, source='cur')

    # =========================================================================
    # DIMENSIONAL QUERIES (Region, Usage Type, Operations)
    # =========================================================================

    def get_costs_by_region(
        self,
        start_date: date,
        end_date: date,
        include_services: bool = False
    ) -> QueryResult:
        """Get costs breakdown by AWS region."""
        if include_services:
            sql = f"""
            SELECT
                COALESCE(product_region, 'Global') as region,
                product_product_name as service,
                SUM(line_item_unblended_cost) as cost
            FROM {self.table_name}
            WHERE line_item_usage_start_date >= DATE('{start_date.isoformat()}')
                AND line_item_usage_start_date < DATE('{end_date.isoformat()}')
                AND line_item_line_item_type IN ('Usage', 'DiscountedUsage', 'SavingsPlanCoveredUsage')
            GROUP BY 1, 2
            HAVING SUM(line_item_unblended_cost) > 0.01
            ORDER BY region, cost DESC
            """
        else:
            sql = f"""
            SELECT
                COALESCE(product_region, 'Global') as region,
                COUNT(DISTINCT product_product_name) as service_count,
                SUM(line_item_unblended_cost) as cost
            FROM {self.table_name}
            WHERE line_item_usage_start_date >= DATE('{start_date.isoformat()}')
                AND line_item_usage_start_date < DATE('{end_date.isoformat()}')
                AND line_item_line_item_type IN ('Usage', 'DiscountedUsage', 'SavingsPlanCoveredUsage')
            GROUP BY 1
            HAVING SUM(line_item_unblended_cost) > 0.01
            ORDER BY cost DESC
            """
        start_time = time.time()
        results = self.execute_query(sql)
        query_time = int((time.time() - start_time) * 1000)
        total_cost = sum(float(r.get('cost', 0) or 0) for r in results)
        return QueryResult(data=results, total_cost=total_cost, query_time_ms=query_time, source='cur')

    def get_costs_by_usage_type(
        self,
        start_date: date,
        end_date: date,
        service: Optional[str] = None,
        limit: int = 100
    ) -> QueryResult:
        """Get costs breakdown by usage type (granular charge types)."""
        service_filter = ""
        if service:
            service_filter = f"AND product_product_name = '{service}'"

        sql = f"""
        SELECT
            line_item_usage_type as usage_type,
            product_product_name as service,
            line_item_operation as operation,
            SUM(line_item_usage_amount) as usage_amount,
            SUM(line_item_unblended_cost) as cost
        FROM {self.table_name}
        WHERE line_item_usage_start_date >= DATE('{start_date.isoformat()}')
            AND line_item_usage_start_date < DATE('{end_date.isoformat()}')
            AND line_item_line_item_type IN ('Usage', 'DiscountedUsage', 'SavingsPlanCoveredUsage')
            {service_filter}
        GROUP BY 1, 2, 3
        HAVING SUM(line_item_unblended_cost) > 0.01
        ORDER BY cost DESC
        LIMIT {limit}
        """
        start_time = time.time()
        results = self.execute_query(sql)
        query_time = int((time.time() - start_time) * 1000)
        total_cost = sum(float(r.get('cost', 0) or 0) for r in results)
        return QueryResult(data=results, total_cost=total_cost, query_time_ms=query_time, source='cur')

    # =========================================================================
    # ANALYTICS QUERIES (Compare, Forecast)
    # =========================================================================

    def get_monthly_costs(
        self,
        start_date: date,
        end_date: date,
        group_by: str = 'service'
    ) -> QueryResult:
        """Get monthly costs for comparison analysis."""
        group_column = {
            'service': 'product_product_name',
            'account': 'line_item_usage_account_id',
            'region': 'product_region'
        }.get(group_by, 'product_product_name')

        sql = f"""
        SELECT
            DATE_FORMAT(line_item_usage_start_date, '%Y-%m') AS month,
            {group_column} as dimension,
            SUM(line_item_unblended_cost) as cost
        FROM {self.table_name}
        WHERE line_item_usage_start_date >= DATE('{start_date.isoformat()}')
            AND line_item_usage_start_date < DATE('{end_date.isoformat()}')
        GROUP BY 1, 2
        HAVING SUM(line_item_unblended_cost) > 0.01
        ORDER BY 1, cost DESC
        """
        start_time = time.time()
        results = self.execute_query(sql)
        query_time = int((time.time() - start_time) * 1000)
        total_cost = sum(float(r.get('cost', 0) or 0) for r in results)
        return QueryResult(data=results, total_cost=total_cost, query_time_ms=query_time, source='cur')

    def get_historical_monthly_totals(
        self,
        months: int = 12
    ) -> QueryResult:
        """Get historical monthly totals for forecasting."""
        end_date = date.today()
        start_date = date(end_date.year, end_date.month, 1) - timedelta(days=months * 31)

        sql = f"""
        SELECT
            DATE_FORMAT(line_item_usage_start_date, '%Y-%m') AS month,
            SUM(line_item_unblended_cost) as cost
        FROM {self.table_name}
        WHERE line_item_usage_start_date >= DATE('{start_date.isoformat()}')
            AND line_item_usage_start_date < DATE('{end_date.isoformat()}')
        GROUP BY 1
        ORDER BY 1
        """
        start_time = time.time()
        results = self.execute_query(sql)
        query_time = int((time.time() - start_time) * 1000)
        total_cost = sum(float(r.get('cost', 0) or 0) for r in results)
        return QueryResult(data=results, total_cost=total_cost, query_time_ms=query_time, source='cur')

    def execute_custom_query(
        self,
        sql: str,
        timeout_seconds: int = 60
    ) -> QueryResult:
        """
        Execute a custom SQL query against the CUR table.

        The query must be SELECT only. The {table} placeholder will be replaced
        with the actual table name.
        """
        # Security check - only allow SELECT
        sql_upper = sql.strip().upper()
        if not sql_upper.startswith('SELECT'):
            raise ValueError("Only SELECT queries are allowed")

        # Disallow dangerous operations
        forbidden = ['DROP', 'DELETE', 'INSERT', 'UPDATE', 'ALTER', 'CREATE', 'TRUNCATE']
        for word in forbidden:
            if word in sql_upper:
                raise ValueError(f"Query contains forbidden keyword: {word}")

        # Replace {table} placeholder
        sql = sql.replace('{table}', self.table_name)

        start_time = time.time()
        results = self.execute_query(sql, cache_ttl=0)  # Don't cache custom queries
        query_time = int((time.time() - start_time) * 1000)

        # Try to calculate total if there's a 'cost' column
        total_cost = 0
        if results:
            for col in ['cost', 'total_cost', 'unblended_cost', 'amount']:
                if col in results[0]:
                    total_cost = sum(float(r.get(col, 0) or 0) for r in results)
                    break

        return QueryResult(data=results, total_cost=total_cost, query_time_ms=query_time, source='cur')


class CostExplorerDataSource(CostDataSource):
    """
    Fallback data source using AWS Cost Explorer API.

    Used when CUR is not available. Provides limited granularity
    compared to CUR but works without additional setup.
    """

    CACHE_TTL = 900  # 15 minutes (shorter due to API costs)

    def __init__(self):
        """Initialize Cost Explorer data source."""
        self._ce_client = None

    @property
    def ce_client(self):
        """Lazy-load Cost Explorer client."""
        if self._ce_client is None:
            self._ce_client = aws_auth.get_client('ce')
        return self._ce_client

    def get_costs_by_tag(
        self,
        tag_key: str,
        start_date: date,
        end_date: date,
        granularity: str = 'MONTHLY',
        tag_value: Optional[str] = None,
        additional_group_by: Optional[List[str]] = None
    ) -> QueryResult:
        """Get cost breakdown by tag dimension using Cost Explorer."""
        cache_key = f"finops:ce:tag:{tag_key}:{tag_value}:{start_date}:{end_date}:{granularity}"

        cached = cache.get(cache_key)
        if cached:
            console.print("[dim][CACHE] Using cached Cost Explorer data[/dim]")
            return QueryResult(
                data=cached['data'],
                total_cost=cached['total'],
                from_cache=True,
                source='cost_explorer'
            )

        start_time = time.time()

        try:
            # Build request
            request = {
                'TimePeriod': {
                    'Start': start_date.isoformat(),
                    'End': end_date.isoformat()
                },
                'Granularity': granularity,
                'Metrics': ['UnblendedCost', 'BlendedCost'],
                'GroupBy': [{'Type': 'TAG', 'Key': tag_key}]
            }

            # Add tag filter if specified
            if tag_value:
                request['Filter'] = {
                    'Tags': {
                        'Key': tag_key,
                        'Values': [tag_value]
                    }
                }

            response = self.ce_client.get_cost_and_usage(**request)

            # Transform response to standard format
            results = []
            for time_period in response.get('ResultsByTime', []):
                period = time_period['TimePeriod']['Start']
                for group in time_period.get('Groups', []):
                    tag_val = group['Keys'][0].replace(f'{tag_key}$', '')
                    cost = float(group['Metrics']['UnblendedCost']['Amount'])
                    if cost > 0.01:
                        results.append({
                            'period': period,
                            'tag_value': tag_val or '(untagged)',
                            'cost': str(cost),
                            'blended_cost': group['Metrics']['BlendedCost']['Amount']
                        })

            total_cost = sum(float(r['cost']) for r in results)
            query_time = int((time.time() - start_time) * 1000)

            # Cache result
            cache.set(cache_key, {'data': results, 'total': total_cost}, ttl=self.CACHE_TTL)

            return QueryResult(
                data=results,
                total_cost=total_cost,
                query_time_ms=query_time,
                source='cost_explorer'
            )

        except ClientError as e:
            console.print(f"[red]Cost Explorer API error: {e}[/red]")
            return QueryResult(data=[], total_cost=0, source='cost_explorer')

    def get_untagged_costs(
        self,
        required_tags: List[str],
        start_date: date,
        end_date: date
    ) -> QueryResult:
        """
        Get costs for resources missing required tags.

        Note: Cost Explorer has limited ability to query untagged resources.
        This returns an approximation based on resources without the tag.
        """
        # Cost Explorer doesn't support querying for missing tags directly
        # We query for the tag and look for empty values
        results = []
        total_cost = 0.0

        console.print("[yellow][WARN] Cost Explorer has limited untagged resource visibility[/yellow]")
        console.print("[yellow]Consider enabling CUR for accurate gap analysis[/yellow]")

        for tag_key in required_tags:
            tag_result = self.get_costs_by_tag(tag_key, start_date, end_date)

            # Look for untagged entries
            for item in tag_result.data:
                if item.get('tag_value') in ('(untagged)', '', None):
                    results.append({
                        'service': 'Multiple',
                        'resource_id': f'(untagged by {tag_key})',
                        'cost': item['cost'],
                        'missing_tag': tag_key
                    })
                    total_cost += float(item['cost'])

        return QueryResult(
            data=results,
            total_cost=total_cost,
            source='cost_explorer'
        )

    def get_costs_by_service(
        self,
        start_date: date,
        end_date: date,
        tag_filter: Optional[Dict[str, str]] = None
    ) -> QueryResult:
        """Get cost breakdown by AWS service using Cost Explorer."""
        cache_key = f"finops:ce:service:{start_date}:{end_date}:{str(tag_filter)}"

        cached = cache.get(cache_key)
        if cached:
            console.print("[dim][CACHE] Using cached Cost Explorer data[/dim]")
            return QueryResult(
                data=cached['data'],
                total_cost=cached['total'],
                from_cache=True,
                source='cost_explorer'
            )

        start_time = time.time()

        try:
            request = {
                'TimePeriod': {
                    'Start': start_date.isoformat(),
                    'End': end_date.isoformat()
                },
                'Granularity': 'MONTHLY',
                'Metrics': ['UnblendedCost', 'BlendedCost'],
                'GroupBy': [{'Type': 'DIMENSION', 'Key': 'SERVICE'}]
            }

            if tag_filter:
                # Build tag filter
                tag_filters = []
                for key, value in tag_filter.items():
                    tag_filters.append({
                        'Tags': {'Key': key, 'Values': [value]}
                    })

                if len(tag_filters) == 1:
                    request['Filter'] = tag_filters[0]
                else:
                    request['Filter'] = {'And': tag_filters}

            response = self.ce_client.get_cost_and_usage(**request)

            # Transform and aggregate by service
            service_costs = {}
            for time_period in response.get('ResultsByTime', []):
                for group in time_period.get('Groups', []):
                    service = group['Keys'][0]
                    cost = float(group['Metrics']['UnblendedCost']['Amount'])
                    blended = float(group['Metrics']['BlendedCost']['Amount'])

                    if service not in service_costs:
                        service_costs[service] = {'cost': 0, 'blended_cost': 0}
                    service_costs[service]['cost'] += cost
                    service_costs[service]['blended_cost'] += blended

            results = [
                {'service': svc, 'cost': str(data['cost']), 'blended_cost': str(data['blended_cost'])}
                for svc, data in sorted(service_costs.items(), key=lambda x: x[1]['cost'], reverse=True)
                if data['cost'] > 0.01
            ]

            total_cost = sum(float(r['cost']) for r in results)
            query_time = int((time.time() - start_time) * 1000)

            cache.set(cache_key, {'data': results, 'total': total_cost}, ttl=self.CACHE_TTL)

            return QueryResult(
                data=results,
                total_cost=total_cost,
                query_time_ms=query_time,
                source='cost_explorer'
            )

        except ClientError as e:
            console.print(f"[red]Cost Explorer API error: {e}[/red]")
            return QueryResult(data=[], total_cost=0, source='cost_explorer')
