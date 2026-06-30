#!/bin/bash

# Deployment Verification Script for AWS Tag Manager CLI
# This script runs after Docker deployment to ensure everything is working

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}===============================================${NC}"
echo -e "${BLUE}   AWS Tag Manager - Deployment Verification${NC}"
echo -e "${BLUE}===============================================${NC}\n"

# Track overall status
OVERALL_STATUS=0

# Function to print status
print_status() {
    if [ $1 -eq 0 ]; then
        echo -e "${GREEN}[PASS]${NC} $2"
    else
        echo -e "${RED}[FAIL]${NC} $2"
        OVERALL_STATUS=1
    fi
}

print_warning() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

# 1. Check Docker Compose Services
echo -e "\n${BLUE}1. Checking Docker Services...${NC}"
echo "----------------------------------------"

# Check if docker compose command works
if docker compose version &>/dev/null; then
    COMPOSE_CMD="docker compose"
else
    COMPOSE_CMD="docker-compose"
fi

# Get service status
SERVICES=("postgres" "redis" "migrate" "celery-worker" "celery-beat")
for service in "${SERVICES[@]}"; do
    if [ "$service" == "migrate" ]; then
        # Migration service should have exited successfully
        STATUS=$($COMPOSE_CMD ps --status=exited $service 2>/dev/null | grep -c "tag-manager-migrate" || echo "0")
        if [ "$STATUS" -gt 0 ]; then
            print_status 0 "$service: Completed successfully"
        else
            print_warning "$service: Not run yet (will run on first startup)"
        fi
    else
        # Other services should be running
        STATUS=$($COMPOSE_CMD ps --status=running $service 2>/dev/null | grep -c "tag-manager" 2>/dev/null || echo "0")
        if [ "$STATUS" -gt 0 ]; then
            print_status 0 "$service: Running"
        else
            print_status 1 "$service: Not running"
        fi
    fi
done

# 2. Check PostgreSQL Database
echo -e "\n${BLUE}2. Checking PostgreSQL Database...${NC}"
echo "----------------------------------------"

# Test database connection
if $COMPOSE_CMD exec -T postgres pg_isready -U tag_manager -d tag_manager &>/dev/null; then
    print_status 0 "PostgreSQL connection: Ready"
    
    # Check if tables exist
    TABLE_COUNT=$($COMPOSE_CMD exec -T postgres psql -U tag_manager -d tag_manager -t -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public';" 2>/dev/null | tr -d ' \n\r' | grep -o '[0-9]*' | head -1)
    
    if [ -n "$TABLE_COUNT" ] && [ "$TABLE_COUNT" -gt 0 ]; then
        print_status 0 "Database tables: $TABLE_COUNT tables found"
        
        # List tables
        echo -e "\n  Tables in database:"
        $COMPOSE_CMD exec -T postgres psql -U tag_manager -d tag_manager -c "\dt" 2>/dev/null | grep "^ public" | awk '{print "    - " $3}'
    else
        print_status 1 "Database tables: No tables found (migrations may not have run)"
    fi
else
    print_status 1 "PostgreSQL connection: Failed"
fi

# 3. Check Redis
echo -e "\n${BLUE}3. Checking Redis Cache...${NC}"
echo "----------------------------------------"

if $COMPOSE_CMD exec -T redis redis-cli ping 2>/dev/null | grep -q "PONG"; then
    print_status 0 "Redis connection: Ready"
    
    # Get Redis info
    REDIS_KEYS=$($COMPOSE_CMD exec -T redis redis-cli DBSIZE 2>/dev/null | grep -o '[0-9]*' || echo "0")
    print_info "Redis keys in database: $REDIS_KEYS"
else
    print_status 1 "Redis connection: Failed"
fi

# 4. Check Celery Workers
echo -e "\n${BLUE}4. Checking Celery Workers...${NC}"
echo "----------------------------------------"

# Check if Celery worker can be pinged
if $COMPOSE_CMD exec -T celery-worker celery -A tag_manager_cli.workers.celery_app inspect ping 2>/dev/null | grep -q "OK"; then
    print_status 0 "Celery worker: Responding to ping"
    
    # Get active tasks
    ACTIVE_TASKS=$($COMPOSE_CMD exec -T celery-worker celery -A tag_manager_cli.workers.celery_app inspect active 2>/dev/null | grep -c "empty" || echo "0")
    if [ "$ACTIVE_TASKS" -gt 0 ]; then
        print_info "Celery worker: No active tasks (idle)"
    fi
else
    print_status 1 "Celery worker: Not responding"
fi

# Check Celery beat scheduler
if $COMPOSE_CMD logs celery-beat 2>/dev/null | tail -5 | grep -q "beat: Starting"; then
    print_status 0 "Celery beat: Scheduler running"
else
    print_warning "Celery beat: Status uncertain (check logs)"
fi

# 5. Check Application Connectivity
echo -e "\n${BLUE}5. Checking Application Connectivity...${NC}"
echo "----------------------------------------"

# Check if Python environment can connect to database
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
    
    # Test database connection from Python
    python -c "
import sys
try:
    from sqlalchemy import create_engine, text
    engine = create_engine('postgresql://tag_manager:tag_manager_dev_password@localhost:5432/tag_manager')
    with engine.connect() as conn:
        result = conn.execute(text('SELECT 1'))
    print('Python to PostgreSQL: Connected')
    sys.exit(0)
except Exception as e:
    print(f'Python to PostgreSQL: Failed - {e}')
    sys.exit(1)
" && print_status 0 "Python to PostgreSQL: Connected" || print_status 1 "Python to PostgreSQL: Failed"
    
    # Test Redis connection from Python
    python -c "
import sys
try:
    import redis
    r = redis.Redis(host='localhost', port=6379, db=0)
    r.ping()
    print('Python to Redis: Connected')
    sys.exit(0)
except Exception as e:
    print(f'Python to Redis: Failed - {e}')
    sys.exit(1)
" && print_status 0 "Python to Redis: Connected" || print_status 1 "Python to Redis: Failed"
else
    print_warning "Python virtual environment not found (skipping Python connectivity tests)"
fi

# 6. Check Optional Services
echo -e "\n${BLUE}6. Checking Optional Services...${NC}"
echo "----------------------------------------"

# Check if monitoring profile is enabled
if grep -q "COMPOSE_PROFILES.*monitoring" .env 2>/dev/null; then
    print_info "Monitoring profile enabled in .env"
    
    # Check Flower
    if curl -s http://localhost:5555/ &>/dev/null; then
        print_status 0 "Flower (Celery monitoring): Available at http://localhost:5555"
    else
        print_warning "Flower: Not accessible (may not be running)"
    fi
    
    # Check pgAdmin
    if curl -s http://localhost:8080/ &>/dev/null; then
        print_status 0 "pgAdmin: Available at http://localhost:8080"
    else
        print_warning "pgAdmin: Not accessible (may not be running)"
    fi
    
    # Check Redis Commander
    if curl -s http://localhost:8081/ &>/dev/null; then
        print_status 0 "Redis Commander: Available at http://localhost:8081"
    else
        print_warning "Redis Commander: Not accessible (may not be running)"
    fi
else
    print_info "Optional monitoring services not enabled (set COMPOSE_PROFILES in .env to enable)"
fi

# 7. Port Availability Check
echo -e "\n${BLUE}7. Checking Port Availability...${NC}"
echo "----------------------------------------"

PORTS=("5432:PostgreSQL" "6379:Redis")
if grep -q "COMPOSE_PROFILES.*monitoring" .env 2>/dev/null; then
    PORTS+=("5555:Flower" "8080:pgAdmin" "8081:Redis-Commander")
fi

for port_info in "${PORTS[@]}"; do
    PORT=$(echo $port_info | cut -d: -f1)
    SERVICE=$(echo $port_info | cut -d: -f2)
    
    # Check if port is listening (Docker containers map to 0.0.0.0)
    if ss -tlnp 2>/dev/null | grep -q ":$PORT " || netstat -tlnp 2>/dev/null | grep -q ":$PORT " || lsof -i :$PORT &>/dev/null; then
        print_status 0 "Port $PORT ($SERVICE): Open and listening"
    else
        # For Docker services, also check if container port is mapped
        if docker ps --format "table {{.Names}}\t{{.Ports}}" | grep -q ":$PORT->"; then
            print_status 0 "Port $PORT ($SERVICE): Mapped via Docker"
        else
            print_warning "Port $PORT ($SERVICE): Not listening"
        fi
    fi
done

# 8. Final Summary
echo -e "\n${BLUE}===============================================${NC}"
echo -e "${BLUE}              Verification Summary${NC}"
echo -e "${BLUE}===============================================${NC}"

if [ $OVERALL_STATUS -eq 0 ]; then
    echo -e "\n${GREEN}SUCCESS: All critical services are running properly!${NC}"
    echo -e "\nYou can now:"
    echo "  1. Run the setup: python -m tag_manager_cli.main setup"
    echo "  2. Start using the CLI: python -m tag_manager_cli.main"
    echo "  3. Check logs: docker compose logs -f"
else
    echo -e "\n${RED}WARNING: Some services are not running properly.${NC}"
    echo -e "\nTroubleshooting steps:"
    echo "  1. Check logs: docker compose logs [service-name]"
    echo "  2. Restart services: docker compose restart"
    echo "  3. Full restart: docker compose down && docker compose up -d"
fi

echo -e "\n${BLUE}Quick Commands:${NC}"
echo "  View logs:        docker compose logs -f"
echo "  Service status:   docker compose ps"
echo "  Restart all:      docker compose restart"
echo "  Stop all:         docker compose down"

exit $OVERALL_STATUS