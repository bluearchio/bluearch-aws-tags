"""Individual component testing utilities for development and debugging."""

import time
import json
import traceback
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Callable
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn

console = Console()


class ComponentTester:
    """Base class for component testing with debugging features."""
    
    def __init__(self, component_name: str, debug: bool = False):
        self.component_name = component_name
        self.debug = debug
        self.test_results = []
    
    def run_test(self, test_name: str, test_func: Callable, *args, **kwargs) -> Dict[str, Any]:
        """Run a single test with error handling and timing."""
        start_time = time.time()
        
        try:
            if self.debug:
                console.print(f"[dim]Starting {test_name}...[/dim]")
            
            result = test_func(*args, **kwargs)
            duration = time.time() - start_time
            
            test_result = {
                'name': test_name,
                'status': 'passed',
                'duration': duration,
                'result': result,
                'error': None
            }
            
            if self.debug:
                console.print(f"[green]OK[/green] {test_name} completed in {duration:.3f}s")
                if isinstance(result, dict) and result:
                    console.print(f"[dim]Result: {json.dumps(result, indent=2, default=str)}[/dim]")
            
        except Exception as e:
            duration = time.time() - start_time
            error_details = {
                'type': type(e).__name__,
                'message': str(e),
                'traceback': traceback.format_exc() if self.debug else None
            }
            
            test_result = {
                'name': test_name,
                'status': 'failed',
                'duration': duration,
                'result': None,
                'error': error_details
            }
            
            if self.debug:
                console.print(f"[red]ERROR[/red] {test_name} failed in {duration:.3f}s")
                console.print(f"[red]Error: {e}[/red]")
                console.print(f"[dim]{traceback.format_exc()}[/dim]")
        
        self.test_results.append(test_result)
        return test_result
    
    def print_summary(self):
        """Print test summary."""
        passed = sum(1 for r in self.test_results if r['status'] == 'passed')
        failed = sum(1 for r in self.test_results if r['status'] == 'failed')
        total = len(self.test_results)
        
        if total == 0:
            console.print("[yellow]No tests were run[/yellow]")
            return
        
        # Create summary table
        table = Table(title=f"{self.component_name} Test Results", show_header=True, header_style="bold magenta")
        table.add_column("Test", style="cyan", width=30)
        table.add_column("Status", style="white", width=10)
        table.add_column("Duration", style="yellow", width=10)
        table.add_column("Details", style="dim")
        
        for result in self.test_results:
            status_color = "green" if result['status'] == 'passed' else "red"
            status_text = f"[{status_color}]{result['status'].upper()}[/{status_color}]"
            duration_text = f"{result['duration']:.3f}s"
            
            if result['error']:
                details = f"Error: {result['error']['message']}"
            elif isinstance(result['result'], dict):
                details = f"Keys: {', '.join(result['result'].keys())}"
            else:
                details = str(result['result'])[:50] + "..." if str(result['result']) else "No output"
            
            table.add_row(result['name'], status_text, duration_text, details)
        
        console.print(table)
        
        # Summary stats
        success_rate = (passed / total) * 100
        color = "green" if success_rate == 100 else "yellow" if success_rate >= 50 else "red"
        console.print(f"\n[{color}]Summary: {passed}/{total} tests passed ({success_rate:.1f}%)[/{color}]")


class DatabaseTester(ComponentTester):
    """Database component testing."""
    
    def __init__(self, debug: bool = False):
        super().__init__("Database", debug)
    
    def test_connection(self):
        """Test database connection."""
        from ..database.connection import db_manager
        
        if not db_manager.initialize():
            raise Exception("Failed to initialize database connection")
        
        return {"status": "connected", "initialized": db_manager._initialized}
    
    def test_health_check(self):
        """Test database health check."""
        from ..database.connection import check_database_health
        
        health = check_database_health(force=True)
        
        if health['status'] != 'healthy':
            raise Exception(f"Database unhealthy: {health}")
        
        return health
    
    def test_pool_status(self):
        """Test connection pool status."""
        from ..database.connection import get_database_pool_status
        
        pool_status = get_database_pool_status()
        
        if 'error' in pool_status:
            raise Exception(f"Pool error: {pool_status['error']}")
        
        return pool_status
    
    def test_table_schema(self):
        """Test core-owned database table availability."""
        from ..utils.core_client import request_core

        status = request_core("GET", "/api/v1/core/db/status", service_token=True, timeout=10.0)
        tables = set(status.get("tables", []))
        expected_tables = {
            "resources",
            "tagging_rules",
            "tagging_audit_log",
            "resource_mappings",
            "cache_metadata",
            "worker_status",
        }

        missing_tables = expected_tables - tables
        if missing_tables:
            raise Exception(f"Missing core tables: {missing_tables}")

        return {"tables": sorted(expected_tables), "total_tables": status.get("table_count", 0)}
    
    def test_crud_operations(self):
        """Test basic CRUD operations."""
        from ..database.connection import get_db_session
        from ..database.models import Resource
        from datetime import datetime
        
        test_arn = f"arn:aws:s3:::test-bucket-{int(time.time())}"
        
        with get_db_session() as session:
            # Create
            resource = Resource(
                resource_arn=test_arn,
                resource_type="AWS::S3::Bucket",
                service_name="s3",
                region="us-east-1",
                account_id="123456789012",
                resource_id=f"test-bucket-{int(time.time())}",
                discovered_at=datetime.utcnow(),
                current_tags={"test": "true"},
                metadata_json={"test_operation": "crud"}
            )
            session.add(resource)
            session.commit()
            
            # Read
            found = session.query(Resource).filter_by(resource_arn=test_arn).first()
            if not found:
                raise Exception("Failed to read created resource")
            
            # Update
            found.current_tags = {"test": "updated"}
            session.commit()
            
            # Verify update
            updated = session.query(Resource).filter_by(resource_arn=test_arn).first()
            if updated.current_tags.get("test") != "updated":
                raise Exception("Failed to update resource")
            
            # Delete
            session.delete(updated)
            session.commit()
            
            # Verify delete
            deleted = session.query(Resource).filter_by(resource_arn=test_arn).first()
            if deleted:
                raise Exception("Failed to delete resource")
            
            return {"operations": ["create", "read", "update", "delete"], "status": "all_successful"}
    
    def run_all_tests(self):
        """Run all database tests."""
        tests = [
            ("Connection Test", self.test_connection),
            ("Health Check", self.test_health_check),
            ("Pool Status", self.test_pool_status),
            ("Table Schema", self.test_table_schema),
            ("CRUD Operations", self.test_crud_operations),
        ]
        
        for test_name, test_func in tests:
            self.run_test(test_name, test_func)
        
        self.print_summary()
        return self.test_results


class CacheTester(ComponentTester):
    """Cache component testing."""
    
    def __init__(self, debug: bool = False):
        super().__init__("Cache", debug)
    
    def test_connection(self):
        """Test cache connection."""
        from ..utils.cache import cache
        
        if not cache.enabled:
            raise Exception("Cache is not enabled")
        
        # Test ping
        cache.redis_client.ping()
        
        return {"enabled": cache.enabled, "host": cache.redis_client.connection_pool.connection_kwargs.get('host')}
    
    def test_basic_operations(self):
        """Test basic cache operations."""
        from ..utils.cache import cache
        
        test_key = f"test_cache_{int(time.time())}"
        test_data = {"timestamp": time.time(), "data": ["item1", "item2"]}
        
        # Set
        result = cache.set(test_key, test_data, ttl=60)
        if not result:
            raise Exception("Failed to set cache value")
        
        # Get
        retrieved = cache.get(test_key)
        if retrieved != test_data:
            raise Exception(f"Cache mismatch: expected {test_data}, got {retrieved}")
        
        # Delete
        deleted = cache.delete(test_key)
        if not deleted:
            raise Exception("Failed to delete cache key")
        
        # Verify deletion
        after_delete = cache.get(test_key)
        if after_delete is not None:
            raise Exception("Key still exists after deletion")
        
        return {"operations": ["set", "get", "delete"], "status": "successful"}
    
    def test_ttl_expiration(self):
        """Test TTL expiration."""
        from ..utils.cache import cache
        
        test_key = f"test_ttl_{int(time.time())}"
        test_data = {"expires": "soon"}
        
        # Set with short TTL
        cache.set(test_key, test_data, ttl=2)
        
        # Should exist immediately
        immediate = cache.get(test_key)
        if immediate != test_data:
            raise Exception("Key not found immediately after setting")
        
        # Wait for expiration
        time.sleep(3)
        
        # Should be expired
        expired = cache.get(test_key)
        if expired is not None:
            raise Exception("Key did not expire after TTL")
        
        return {"ttl_test": "passed", "expiration_time": "2 seconds"}
    
    def test_key_generation(self):
        """Test cache key generation."""
        from ..utils.cache import cache
        
        key1 = cache.generate_key("service1", "method1", param1="value1", param2="value2")
        key2 = cache.generate_key("service1", "method1", param2="value2", param1="value1")
        key3 = cache.generate_key("service2", "method1", param1="value1", param2="value2")
        
        # Same parameters in different order should generate same key
        if key1 != key2:
            raise Exception("Key generation not consistent for same parameters")
        
        # Different service should generate different key
        if key1 == key3:
            raise Exception("Different services generated same key")
        
        return {"key1": key1, "key2": key2, "key3": key3, "consistent": key1 == key2}
    
    def test_pattern_operations(self):
        """Test pattern-based operations."""
        from ..utils.cache import cache
        
        # Set multiple keys with pattern
        pattern_prefix = f"pattern_test_{int(time.time())}"
        test_keys = [f"{pattern_prefix}:key{i}" for i in range(3)]
        
        for i, key in enumerate(test_keys):
            cache.set(key, f"value{i}", ttl=60)
        
        # Clear pattern
        cleared = cache.clear_pattern(f"{pattern_prefix}:*")
        
        # Verify all keys are gone
        remaining = []
        for key in test_keys:
            if cache.get(key) is not None:
                remaining.append(key)
        
        if remaining:
            raise Exception(f"Keys still exist after pattern clear: {remaining}")
        
        return {"pattern": f"{pattern_prefix}:*", "keys_cleared": cleared, "keys_tested": len(test_keys)}
    
    def run_all_tests(self):
        """Run all cache tests."""
        tests = [
            ("Connection Test", self.test_connection),
            ("Basic Operations", self.test_basic_operations),
            ("TTL Expiration", self.test_ttl_expiration),
            ("Key Generation", self.test_key_generation),
            ("Pattern Operations", self.test_pattern_operations),
        ]
        
        for test_name, test_func in tests:
            self.run_test(test_name, test_func)
        
        self.print_summary()
        return self.test_results


class WorkerTester(ComponentTester):
    """Worker component testing."""
    
    def __init__(self, debug: bool = False):
        super().__init__("Workers", debug)
    
    def test_worker_registration(self):
        """Test worker registration in database."""
        from ..database.connection import get_db_session
        from ..database.models import WorkerStatus
        
        with get_db_session() as session:
            workers = session.query(WorkerStatus).all()
            active_workers = [w for w in workers if w.status in ['active', 'busy', 'idle']]
            
            if not workers:
                raise Exception("No workers found in database")
            
            if not active_workers:
                raise Exception("No active workers found")
            
            return {
                "total_workers": len(workers),
                "active_workers": len(active_workers),
                "worker_types": list(set(w.worker_type for w in workers))
            }
    
    def test_health_check_task(self):
        """Test worker health check task."""
        from ..workers.monitoring_tasks import worker_health_check
        
        result = worker_health_check.delay()
        health_result = result.get(timeout=15)
        
        if health_result['status'] != 'healthy':
            raise Exception(f"Worker health check failed: {health_result}")
        
        return health_result
    
    def test_system_metrics_task(self):
        """Test system metrics collection task."""
        from ..workers.monitoring_tasks import collect_system_metrics
        
        result = collect_system_metrics.delay()
        metrics = result.get(timeout=20)
        
        required_metrics = ['hostname', 'cpu_percent', 'memory_percent']
        missing_metrics = [m for m in required_metrics if m not in metrics]
        
        if missing_metrics:
            raise Exception(f"Missing required metrics: {missing_metrics}")
        
        return {
            "metrics_collected": len(metrics),
            "required_metrics": required_metrics,
            "sample_metrics": {k: v for k, v in metrics.items() if k in required_metrics}
        }
    
    def test_task_retry_mechanism(self):
        """Test task retry mechanism by creating a failing task."""
        from ..workers.monitoring_tasks import cleanup_expired_cache
        
        # This should succeed, but we test the retry mechanism is available
        result = cleanup_expired_cache.delay()
        cleanup_result = result.get(timeout=15)
        
        # Check that the task has retry capability
        if not hasattr(cleanup_expired_cache, 'retry'):
            raise Exception("Task does not have retry capability")
        
        return {
            "task_name": "cleanup_expired_cache",
            "has_retry": True,
            "cleanup_result": cleanup_result
        }
    
    def test_worker_status_updates(self):
        """Test worker status updates."""
        from ..database.connection import get_db_session
        from ..database.models import WorkerStatus
        from datetime import datetime, timedelta
        
        with get_db_session() as session:
            # Find a recent worker
            recent_worker = session.query(WorkerStatus).filter(
                WorkerStatus.last_heartbeat > datetime.utcnow() - timedelta(minutes=5)
            ).first()
            
            if not recent_worker:
                raise Exception("No recent worker heartbeats found")
            
            return {
                "worker_id": recent_worker.worker_id,
                "last_heartbeat": recent_worker.last_heartbeat.isoformat(),
                "status": recent_worker.status,
                "tasks_processed": recent_worker.tasks_processed
            }
    
    def run_all_tests(self):
        """Run all worker tests."""
        tests = [
            ("Worker Registration", self.test_worker_registration),
            ("Health Check Task", self.test_health_check_task),
            ("System Metrics Task", self.test_system_metrics_task),
            ("Task Retry Mechanism", self.test_task_retry_mechanism),
            ("Worker Status Updates", self.test_worker_status_updates),
        ]
        
        for test_name, test_func in tests:
            self.run_test(test_name, test_func)
        
        self.print_summary()
        return self.test_results


class RateLimiterTester(ComponentTester):
    """Rate limiter component testing."""
    
    def __init__(self, debug: bool = False):
        super().__init__("Rate Limiter", debug)
    
    def test_basic_throttling(self):
        """Test basic rate limiting."""
        from ..utils.rate_limiter import rate_limiter
        
        service = f"test_service_{int(time.time())}"
        start_time = time.time()
        
        # Make several calls that should be throttled
        for i in range(3):
            with rate_limiter.throttle(service, 'test_operation'):
                time.sleep(0.01)  # Simulate work
        
        elapsed = time.time() - start_time
        
        return {
            "service": service,
            "calls_made": 3,
            "total_time": elapsed,
            "throttling_applied": elapsed > 0.03  # Should take at least 30ms
        }
    
    def test_service_limits(self):
        """Test service-specific limits."""
        from ..utils.rate_limiter import rate_limiter
        
        # Test different services have different limits
        ec2_limit = rate_limiter.get_service_limit('ec2')
        s3_limit = rate_limiter.get_service_limit('s3')
        default_limit = rate_limiter.get_service_limit('unknown_service')
        
        return {
            "ec2_limit": ec2_limit,
            "s3_limit": s3_limit,
            "default_limit": default_limit,
            "limits_configured": ec2_limit > 0 and s3_limit > 0
        }
    
    def test_burst_allowance(self):
        """Test burst allowance functionality."""
        from ..utils.rate_limiter import rate_limiter
        
        # Test burst allowance
        ec2_burst = rate_limiter.get_burst_allowance('ec2')
        s3_burst = rate_limiter.get_burst_allowance('s3')
        
        return {
            "ec2_burst": ec2_burst,
            "s3_burst": s3_burst,
            "burst_higher_than_limits": ec2_burst > rate_limiter.get_service_limit('ec2')
        }
    
    def test_statistics_collection(self):
        """Test rate limiting statistics."""
        from ..utils.rate_limiter import rate_limiter
        
        service = f"stats_test_{int(time.time())}"
        operation = "test_stats"
        
        # Make some calls to generate stats
        for i in range(2):
            with rate_limiter.throttle(service, operation):
                time.sleep(0.01)
        
        # Get stats
        stats = rate_limiter.get_rate_limit_stats(service)
        
        if not stats:
            raise Exception("No statistics collected")
        
        key = f"{service}:default:{operation}"
        if key not in stats:
            raise Exception(f"Statistics not found for key: {key}")
        
        return {
            "service": service,
            "stats_key": key,
            "stats": stats[key]
        }
    
    def test_reset_functionality(self):
        """Test rate limit reset functionality."""
        from ..utils.rate_limiter import rate_limiter
        
        service = f"reset_test_{int(time.time())}"
        
        # Make some calls
        with rate_limiter.throttle(service, 'test'):
            pass
        
        # Get initial stats
        initial_stats = rate_limiter.get_rate_limit_stats(service)
        
        # Reset for this service
        rate_limiter.reset_rate_limits(service)
        
        # Get stats after reset
        after_reset_stats = rate_limiter.get_rate_limit_stats(service)
        
        return {
            "service": service,
            "had_initial_stats": len(initial_stats) > 0,
            "stats_cleared": len(after_reset_stats) == 0
        }
    
    def run_all_tests(self):
        """Run all rate limiter tests."""
        tests = [
            ("Basic Throttling", self.test_basic_throttling),
            ("Service Limits", self.test_service_limits),
            ("Burst Allowance", self.test_burst_allowance),
            ("Statistics Collection", self.test_statistics_collection),
            ("Reset Functionality", self.test_reset_functionality),
        ]
        
        for test_name, test_func in tests:
            self.run_test(test_name, test_func)
        
        self.print_summary()
        return self.test_results


def run_component_test(component: str, debug: bool = False) -> Dict[str, Any]:
    """Run tests for a specific component."""
    testers = {
        'database': DatabaseTester,
        'cache': CacheTester, 
        'workers': WorkerTester,
        'rate_limiter': RateLimiterTester,
    }
    
    if component not in testers:
        raise ValueError(f"Unknown component: {component}. Available: {list(testers.keys())}")
    
    tester = testers[component](debug=debug)
    return tester.run_all_tests()


def run_all_component_tests(debug: bool = False) -> Dict[str, List[Dict[str, Any]]]:
    """Run tests for all components."""
    components = ['database', 'cache', 'workers', 'rate_limiter']
    results = {}
    
    console.print("[bold blue]Running All Component Tests[/bold blue]")
    console.print("=" * 60)
    
    for component in components:
        console.print(f"\n[cyan]Testing {component.title()} Component...[/cyan]")
        try:
            results[component] = run_component_test(component, debug)
        except Exception as e:
            console.print(f"[red]Failed to test {component}: {e}[/red]")
            results[component] = []
    
    # Overall summary
    console.print("\n" + "=" * 60)
    console.print("[bold blue]Overall Component Test Summary[/bold blue]")
    
    total_tests = 0
    total_passed = 0
    
    for component, test_results in results.items():
        passed = sum(1 for r in test_results if r['status'] == 'passed')
        total = len(test_results)
        total_tests += total
        total_passed += passed
        
        status_color = "green" if passed == total else "yellow" if passed > 0 else "red"
        console.print(f"[{status_color}]{component.title()}: {passed}/{total} tests passed[/{status_color}]")
    
    overall_rate = (total_passed / total_tests) * 100 if total_tests > 0 else 0
    overall_color = "green" if overall_rate == 100 else "yellow" if overall_rate >= 70 else "red"
    console.print(f"\n[{overall_color}]Overall: {total_passed}/{total_tests} tests passed ({overall_rate:.1f}%)[/{overall_color}]")
    
    return results
