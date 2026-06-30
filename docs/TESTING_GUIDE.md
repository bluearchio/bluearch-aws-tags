# Testing Guide for AWS Tag Manager CLI

This guide explains how to test the Tag Manager CLI locally with all Phase 1 components.

## 🛠️ Prerequisites

### 1. Install Dependencies

```bash
# Activate virtual environment
source .venv/bin/activate

# Install all dependencies
pip install -r requirements.txt

# Install package in development mode
pip install -e .
```

### 2. Start Infrastructure Services

```bash
# Run the installation script (sets up Docker services)
./install.sh
```

This will start:
- PostgreSQL database (port 5432)
- Redis cache (port 6379)  
- Celery workers
- Celery beat scheduler

### 3. Configure AWS Credentials

```bash
# Configure AWS SSO
aws configure sso

# Set your profile in .env
echo "AWS_PROFILE=your-sso-profile" >> .env
echo "AWS_REGION=us-east-1" >> .env
```

## 🧪 Testing Steps

### Step 1: Test Environment Configuration

```bash
# Test environment loading
python test_env_integration.py

# Show current configuration
python -m tag_manager_cli.main config
```

### Step 2: Initialize Database

```bash
# Setup database schema and migrations
python -c "
from tag_manager_cli.database.setup import setup_database_command
setup_database_command()
"
```

Expected output:
```
✓ Database connection successful
✓ Migrations initialized  
✓ Initial migration created
✓ Database migrations applied
✓ Database health check passed
🎉 Database setup completed successfully!
```

### Step 3: Test Database Connection

```bash
# Check database status
python -c "
from tag_manager_cli.database.setup import show_database_status
show_database_status()
"
```

### Step 4: Test Worker Framework

```bash
# Test worker registration (in separate terminal)
celery -A tag_manager_cli.workers.celery_app worker --loglevel=info

# Test task execution
python -c "
from tag_manager_cli.workers.monitoring_tasks import worker_health_check
result = worker_health_check.delay()
print('Task result:', result.get(timeout=30))
"
```

### Step 5: Test Resource Discovery

```bash
# Test EC2 discovery
python -c "
from tag_manager_cli.workers.discovery_tasks import discover_ec2_resources
result = discover_ec2_resources.delay('us-east-1')
print('Discovery result:', result.get(timeout=60))
"

# Test S3 discovery  
python -c "
from tag_manager_cli.workers.discovery_tasks import discover_s3_resources
result = discover_s3_resources.delay()
print('S3 result:', result.get(timeout=60))
"
```

### Step 6: Test Rate Limiting

```bash
# Test rate limiter
python -c "
from tag_manager_cli.utils.rate_limiter import rate_limiter
import time

# Test rate limiting
for i in range(5):
    with rate_limiter.throttle('ec2', 'describe_instances', 'us-east-1'):
        print(f'Call {i+1} completed at {time.time()}')
        time.sleep(0.1)

# Check stats
stats = rate_limiter.get_rate_limit_stats('ec2')
print('Rate limit stats:', stats)
"
```

### Step 7: Test Cache System

```bash
# Test Redis cache
python -c "
from tag_manager_cli.utils.cache import cache

# Test cache operations
cache.set('test_key', {'data': 'test_value'}, ttl=60)
result = cache.get('test_key')
print('Cache test result:', result)

# Test cache stats
print('Cache enabled:', cache.enabled)
"
```

## 🔍 Monitoring and Debugging

### View Worker Status

```bash
# Check Celery worker status
celery -A tag_manager_cli.workers.celery_app status

# Monitor tasks with Flower (if enabled)
# Access http://localhost:5555
```

### Check Database Tables

```bash
# Connect to PostgreSQL
psql postgresql://tag_manager:tag_manager_dev_password@localhost:5432/tag_manager

# List tables
\dt

# Check resources table
SELECT COUNT(*) FROM resources;
SELECT resource_type, COUNT(*) FROM resources GROUP BY resource_type;

# Check worker status
SELECT worker_id, status, last_heartbeat FROM worker_status;
```

### Monitor Redis

```bash
# Connect to Redis
redis-cli

# Check keys
KEYS "tagmanager:*"

# Check worker queues
LLEN default
LLEN discovery
LLEN tagging
```

## 🧪 Test Scripts

### Complete Integration Test

```bash
# Create and run comprehensive test
cat > test_integration.py << 'EOF'
#!/usr/bin/env python3
"""Complete integration test for Tag Manager CLI."""

import time
from tag_manager_cli.database.setup import setup_database_command, show_database_status
from tag_manager_cli.workers.monitoring_tasks import worker_health_check, collect_system_metrics
from tag_manager_cli.workers.discovery_tasks import discover_ec2_resources
from tag_manager_cli.utils.cache import cache
from tag_manager_cli.utils.rate_limiter import rate_limiter

def test_complete_integration():
    print("🧪 Starting complete integration test...")
    
    # Test 1: Database setup
    print("\n1. Testing database setup...")
    if setup_database_command():
        print("✅ Database setup: PASSED")
    else:
        print("❌ Database setup: FAILED")
        return False
    
    # Test 2: Cache system
    print("\n2. Testing cache system...")
    cache.set("integration_test", {"timestamp": time.time()})
    if cache.get("integration_test"):
        print("✅ Cache system: PASSED")
    else:
        print("❌ Cache system: FAILED")
    
    # Test 3: Rate limiter
    print("\n3. Testing rate limiter...")
    with rate_limiter.throttle('test_service', 'test_operation'):
        print("✅ Rate limiter: PASSED")
    
    # Test 4: Worker health check
    print("\n4. Testing worker health check...")
    try:
        result = worker_health_check.delay()
        health_result = result.get(timeout=30)
        if health_result['status'] == 'healthy':
            print("✅ Worker health check: PASSED")
        else:
            print(f"❌ Worker health check: FAILED - {health_result}")
    except Exception as e:
        print(f"❌ Worker health check: FAILED - {e}")
    
    # Test 5: System metrics
    print("\n5. Testing system metrics...")
    try:
        result = collect_system_metrics.delay()
        metrics = result.get(timeout=30)
        if 'timestamp' in metrics:
            print("✅ System metrics: PASSED")
        else:
            print(f"❌ System metrics: FAILED - {metrics}")
    except Exception as e:
        print(f"❌ System metrics: FAILED - {e}")
    
    # Test 6: Resource discovery (if AWS configured)
    print("\n6. Testing resource discovery...")
    try:
        result = discover_ec2_resources.delay('us-east-1')
        discovery_result = result.get(timeout=60)
        print(f"✅ Resource discovery: PASSED - Found {discovery_result.get('discovered_count', 0)} resources")
    except Exception as e:
        print(f"⚠️  Resource discovery: SKIPPED - {e} (AWS not configured?)")
    
    print("\n🎉 Integration test completed!")
    
    # Show final status
    print("\n" + "="*50)
    show_database_status()

if __name__ == "__main__":
    test_complete_integration()
EOF

chmod +x test_integration.py
python test_integration.py
```

## 🐛 Troubleshooting

### Common Issues

1. **Database Connection Error**
   ```bash
   # Check if PostgreSQL is running
   docker ps | grep postgres
   
   # Check database logs
   docker logs tag-manager-postgres
   ```

2. **Redis Connection Error**
   ```bash
   # Check if Redis is running
   docker ps | grep redis
   
   # Test Redis connection
   redis-cli ping
   ```

3. **Celery Worker Issues**
   ```bash
   # Check worker logs
   docker logs tag-manager-worker
   
   # Restart workers
   docker compose restart celery-worker celery-beat
   ```

4. **AWS Permission Issues**
   ```bash
   # Test AWS credentials
   aws sts get-caller-identity
   
   # Test specific permissions
   aws ec2 describe-instances --region us-east-1 --max-items 1
   ```

### Reset Everything

```bash
# Stop all services
docker compose down

# Remove volumes (deletes data)
docker compose down -v

# Restart fresh
./install.sh

# Reinitialize database
python -c "from tag_manager_cli.database.setup import setup_database_command; setup_database_command()"
```

## 📊 Expected Results

After successful testing, you should see:

1. **Database**: 6 tables created with proper schema
2. **Workers**: Active Celery workers processing tasks  
3. **Discovery**: AWS resources being discovered and cached
4. **Monitoring**: System metrics and worker health tracking
5. **Rate Limiting**: API calls properly throttled
6. **Caching**: Redis storing API responses and metadata

The system is now ready for **Phase 2: Tagging Logic Engine**!