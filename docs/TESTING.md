# Testing Documentation - AWS Tag Manager CLI

## Overview

This document describes the testing infrastructure and practices for the Tag Manager CLI.

## Test Suite Structure

```
tests/
├── __init__.py
├── conftest.py              # Shared pytest fixtures
└── e2e/
    ├── __init__.py
    └── test_critical_flows.py    # End-to-end tests for critical workflows
```

## Running Tests

### Run All Tests
```bash
source .venv/bin/activate
pytest tests/
```

### Run Specific Test File
```bash
pytest tests/e2e/test_critical_flows.py -v
```

### Run with Output Visible
```bash
pytest tests/e2e/test_critical_flows.py -s -v
```

### Run Specific Test Class or Method
```bash
# Run all tests in a class
pytest tests/e2e/test_critical_flows.py::TestDatabaseInitialization -v

# Run single test
pytest tests/e2e/test_critical_flows.py::TestCLIUsability::test_help_command_works -v
```

## Test Categories

### 1. Database Initialization Tests
- **test_database_auto_initializes**: Verifies database automatically initializes
- **test_database_schema_matches_models**: Ensures schema matches model definitions

### 2. Resource Discovery Tests
- **test_discovery_completes_without_errors**: Discovery completes successfully
- **test_discovery_handles_multiple_regions**: Multi-region discovery works

### 3. Tag Scanning Tests
- **test_scan_identifies_untagged_resources**: Identifies resources missing tags
- **test_scan_shows_compliant_resources**: Shows properly tagged resources

### 4. Rule Management Tests
- **test_create_tagging_rule**: Creates and queries tagging rules

### 5. Error Handling Tests
- **test_helpful_error_when_aws_credentials_missing**: Helpful error for missing credentials
- **test_helpful_error_when_database_not_initialized**: Helpful error for uninitialized DB

### 6. CLI Usability Tests
- **test_help_command_works**: --help shows useful information
- **test_command_groups_are_accessible**: All command groups accessible
- **test_interactive_mode_accessible**: Interactive mode is registered

### 7. Concurrent Discovery Tests
- **test_concurrent_discovery_faster_than_sequential**: Parallel execution improves speed
- **test_tree_display_shows_hierarchy**: Tree display works correctly

## Test Results Summary

Current test status: **8 PASSING / 6 FAILING / 2 ERRORS**

### Passing Tests
- Database schema validation
- CLI help commands
- Error handling for missing credentials
- Command group accessibility
- Interactive mode registration

### Known Issues
- Some mocking issues with AWS clients need refinement
- Database pooling configuration in test environment
- Discovery tests need better AWS service mocking

## Fixtures Available

### Database Fixtures
- `temp_db_path`: Temporary database file for testing
- `init_test_database`: Initialized test database with schema
- `sample_resources`: Pre-populated test resources

### Environment Fixtures
- `test_env_vars`: Test environment variables
- `cli_runner`: Typer CLI runner for invoking commands

### AWS Mocking Fixtures
- `mock_aws_credentials`: Mocked AWS credentials
- `mock_boto3_client`: Mocked boto3 client with sample responses

## Writing New Tests

### Basic Test Structure
```python
def test_my_feature(cli_runner, init_test_database):
    """Test that my feature works correctly."""
    result = cli_runner.invoke(app, ['my', 'command'])

    assert result.exit_code == 0
    assert 'expected output' in result.stdout
```

### Testing with Mocked AWS
```python
@patch('tag_manager_cli.utils.aws_auth.aws_auth.get_client')
def test_aws_operation(mock_get_client, cli_runner):
    """Test AWS operation with mocked client."""
    mock_client = Mock()
    mock_client.my_operation.return_value = {'Result': 'success'}
    mock_get_client.return_value = mock_client

    result = cli_runner.invoke(app, ['my', 'aws', 'command'])

    assert result.exit_code == 0
```

### Testing Database Operations
```python
def test_database_operation(init_test_database):
    """Test database operation."""
    from tag_manager_cli.database.connection import get_db_session
    from tag_manager_cli.database.models import Resource

    with get_db_session() as session:
        count = session.query(Resource).count()
        assert count >= 0
```

## Best Practices

1. **Isolation**: Each test should be independent
2. **Cleanup**: Use fixtures for automatic cleanup
3. **Mocking**: Mock external AWS API calls
4. **Assertions**: Use clear, descriptive assertions
5. **Documentation**: Add docstrings to all tests

## Continuous Integration

Tests can be integrated into CI/CD pipelines:

```yaml
# Example GitHub Actions workflow
- name: Run tests
  run: |
    source .venv/bin/activate
    pytest tests/ -v --tb=short
```

## Troubleshooting

### Tests Not Collecting
- Ensure test files start with `test_`
- Ensure test functions start with `test_`
- Check for syntax errors in test files

### Import Errors
- Activate virtual environment: `source .venv/bin/activate`
- Install dependencies: `pip install -r requirements.txt`

### Database Errors in Tests
- Check `TAG_MANAGER_DB_PATH` environment variable
- Ensure test database is properly isolated
- Verify migrations are applied

## Next Steps

- [ ] Fix remaining test failures
- [ ] Add integration tests with real AWS (using test accounts)
- [ ] Add performance benchmarks
- [ ] Increase test coverage to >80%
- [ ] Add mutation testing
- [ ] Set up code coverage reporting
