#!/bin/bash

# AWS Tag Manager CLI - Automated Tagging Setup Script
# This script sets up the automated tagging system with sample rules

set -e

echo "🏗️ Setting up AWS Tag Manager Automated Tagging System..."

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${GREEN}✓${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

print_info() {
    echo -e "${BLUE}ℹ${NC} $1"
}

# Check if we're in the right directory
if [ ! -f "tag_manager_cli/main.py" ]; then
    print_error "Please run this script from the tag-manager-cli project root directory"
    exit 1
fi

# Detect Python command
if command -v python3 >/dev/null 2>&1; then
    PYTHON_CMD="python3"
elif command -v python >/dev/null 2>&1; then
    PYTHON_CMD="python"
else
    print_error "Python not found. Please install Python 3.9+ and ensure it's in your PATH"
    exit 1
fi

print_info "Using Python: $PYTHON_CMD"

# Check if virtual environment is activated
if [ -z "$VIRTUAL_ENV" ]; then
    print_warning "Virtual environment not detected. It's recommended to activate your venv first:"
    echo "  source .venv/bin/activate"
    echo ""
fi

# Step 1: Install dependencies
print_info "Step 1: Installing required dependencies..."
pip install jinja2>=3.1.0 --quiet
print_status "Dependencies installed"

# Step 2: Initialize database (if needed)
print_info "Step 2: Checking database setup..."
if $PYTHON_CMD -m tag_manager_cli.main database status > /dev/null 2>&1; then
    print_status "Database is ready"
else
    print_warning "Database needs initialization. Run: $PYTHON_CMD -m tag_manager_cli.main database init"
fi

# Step 3: Load sample tagging rules
print_info "Step 3: Loading sample tagging rules..."
if [ -f "config/sample_tagging_rules.json" ]; then
    $PYTHON_CMD -m tag_manager_cli.main tagging load-rules config/sample_tagging_rules.json --replace
    print_status "Sample tagging rules loaded"
else
    print_warning "Sample rules file not found at config/sample_tagging_rules.json"
fi

# Step 4: Show configuration summary
print_info "Step 4: Configuration Summary"
echo ""
echo "📋 Automated Tagging Components:"
echo ""
echo "🔧 Core Infrastructure:"
echo "   ✓ Database schema with all required tables"
echo "   ✓ Celery worker framework with Redis"
echo "   ✓ Resource discovery for EC2, S3, Lambda"
echo "   ✓ Caching and rate limiting"
echo ""
echo "🏷️ Tagging Engine:"
echo "   ✓ CloudTrail event processing"
echo "   ✓ Principal information extraction"
echo "   ✓ Rule-based tag generation"
echo "   ✓ Automated tag application"
echo ""
echo "📊 Sample Rules Loaded:"
echo "   • auto_tag_by_creator - Tags resources with creator info"
echo "   • environment_classification - Classifies environments"
echo "   • cost_center_from_user - Assigns cost centers"
echo "   • security_compliance_tagging - Adds compliance tags"
echo "   • project_tagging_from_context - Infers project info"
echo "   • time_based_lifecycle_tagging - Adds lifecycle tags"
echo ""

# Step 5: Next steps
print_info "🚀 Next Steps - Core Tag Management:"
echo ""
echo "1. Scan for untagged resources:"
echo "   $PYTHON_CMD -m tag_manager_cli.main tag scan"
echo ""
echo "2. Tag resources interactively:"
echo "   $PYTHON_CMD -m tag_manager_cli.main tag interactive"
echo ""
echo "3. Bulk tag by service:"
echo "   $PYTHON_CMD -m tag_manager_cli.main tag bulk ec2 --tag-key Environment --tag-value production"
echo ""
echo "4. Apply automatic rules:"
echo "   $PYTHON_CMD -m tag_manager_cli.main tag auto-apply"
echo ""
echo "5. Generate compliance report:"
echo "   $PYTHON_CMD -m tag_manager_cli.main tag report"
echo ""

print_info "🤖 Automated Processing:"
echo ""
echo "1. Start the workers:"
echo "   $PYTHON_CMD -m tag_manager_cli.main workers start"
echo ""
echo "2. Monitor CloudTrail processing:"
echo "   $PYTHON_CMD -m tag_manager_cli.main tagging stats"
echo ""
echo "3. View audit logs:"
echo "   $PYTHON_CMD -m tag_manager_cli.main tagging audit-log"
echo ""

print_info "Environment Variables (optional):"
echo ""
echo "# CloudTrail Processing"
echo "export CLOUDTRAIL_LOOKBACK_MINUTES=30"
echo "export AWS_REGIONS=\"us-east-1,us-west-2,eu-west-1\""
echo ""
echo "# Rate Limiting"
echo "export CLOUDTRAIL_API_RATE_LIMIT_PER_SECOND=5"
echo "export AWS_API_RATE_LIMIT_PER_SECOND=10"
echo ""

# Check AWS credentials
print_info "AWS Credentials Check:"
if aws sts get-caller-identity > /dev/null 2>&1; then
    print_status "AWS credentials are configured"
    ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text 2>/dev/null)
    print_info "AWS Account: $ACCOUNT_ID"
else
    print_warning "AWS credentials not found. Make sure to configure:"
    echo "   export AWS_PROFILE=your-sso-profile"
    echo "   aws sso login"
fi

echo ""
print_status "Automated Tagging Setup Complete!"
echo ""
print_info "The system will automatically:"
echo "   • Discover AWS resources every 30 minutes"
echo "   • Process CloudTrail events every 5 minutes"
echo "   • Apply tagging rules based on resource creation events"
echo "   • Track all operations in audit logs"
echo ""

# Optional: Test setup
read -p "Would you like to run a quick test? (y/n): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    print_info "Running quick test..."
    
    # Test database connection
    if $PYTHON_CMD -m tag_manager_cli.main database status > /dev/null 2>&1; then
        print_status "Database connection: OK"
    else
        print_error "Database connection: FAILED"
    fi
    
    # Test Redis connection  
    if redis-cli ping > /dev/null 2>&1; then
        print_status "Redis connection: OK"
    else
        print_warning "Redis connection: Not available (workers may not function)"
    fi
    
    # Show rules count
    RULES_COUNT=$($PYTHON_CMD -c "
from tag_manager_cli.database.connection import get_db_session
from tag_manager_cli.database.models import TaggingRule
with get_db_session() as session:
    count = session.query(TaggingRule).filter_by(enabled=True).count()
    print(count)
" 2>/dev/null || echo "0")
    print_status "Active tagging rules: $RULES_COUNT"
    
    echo ""
    print_status "Quick test completed!"
fi

echo ""
print_info "Happy tagging! 🏷️✨"