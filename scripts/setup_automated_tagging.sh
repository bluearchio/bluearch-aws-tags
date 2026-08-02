#!/bin/bash

# BlueArch AWS Tags - lifecycle workflow setup helper
# Legacy worker/tag-rule automation is not part of the public CLI surface.

set -e

echo "Setting up the BlueArch AWS Tags lifecycle workflow..."

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${GREEN}[OK]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
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
pip install "jinja2>=3.1.0" --quiet
print_status "Dependencies installed"

# Step 2: Initialize database (if needed)
print_info "Step 2: Checking database setup..."
if $PYTHON_CMD -m tag_manager_cli.main setup database > /dev/null 2>&1; then
    print_status "Database is ready"
else
    print_warning "Database setup needs attention. Run: bluearch-aws-tags setup database"
fi

# Step 3: Direct users to the registered lifecycle policy workflow.
print_info "Step 3: Configure lifecycle policies..."
print_warning "Legacy sample tag-rule loading is unavailable in the public CLI."
echo "Run: bluearch-aws-tags lifecycle policies create"

# Step 4: Show configuration summary
print_info "Step 4: Configuration Summary"
echo ""
echo "Public lifecycle components:"
echo ""
echo "Core infrastructure:"
echo "   - Core-owned database and local services"
echo "   - Resource discovery for supported AWS services"
echo "   - Lifecycle policies and TTL previews"
echo ""
echo "Supported policy workflow:"
echo "   - Create lifecycle policies"
echo "   - Discover and scan matching resources"
echo "   - Preview TTL tag changes with --dry-run"
echo "   - Review expiring resources"
echo ""

# Step 5: Next steps
print_info "Next Steps - Lifecycle Management:"
echo ""
echo "1. Scan for untagged resources:"
echo "   bluearch-aws-tags policy check-compliance --details"
echo ""
echo "2. Start the guided lifecycle workflow:"
echo "   bluearch-aws-tags lifecycle wizard"
echo ""
echo "3. Create lifecycle policies:"
echo "   bluearch-aws-tags lifecycle policies create"
echo ""
echo "4. Preview policy-driven TTL tags:"
echo "   bluearch-aws-tags lifecycle set-ttl --dry-run"
echo ""
echo "5. Review expiring resources:"
echo "   bluearch-aws-tags lifecycle review"
echo ""

print_info "Public Runtime:"
echo ""
echo "1. Start shared local services:"
echo "   bluearch-aws-core start --daemon"
echo ""
echo "2. Validate the Tags installation:"
echo "   bluearch-aws-tags setup validate"
echo ""
echo "3. Check the managed dashboard:"
echo "   bluearch-aws-tags web status"
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
print_status "Lifecycle workflow setup complete!"
echo ""
print_info "The public workflow is explicit and review-driven:"
echo "   - Run discovery when you need fresh inventory"
echo "   - Preview TTL changes before applying them"
echo "   - Review expiring resources before deletion"
echo ""

# Optional: Test setup
read -p "Would you like to run a quick test? (y/n): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    print_info "Running quick test..."
    
    # Test database connection
    if $PYTHON_CMD -m tag_manager_cli.main setup database > /dev/null 2>&1; then
        print_status "Database connection: OK"
    else
        print_error "Database connection: FAILED"
    fi

    if $PYTHON_CMD -m tag_manager_cli.main --version > /dev/null 2>&1; then
        print_status "Public CLI entrypoint: OK"
    else
        print_error "Public CLI entrypoint: FAILED"
    fi
    
    echo ""
    print_status "Quick test completed!"
fi

echo ""
print_info "Use bluearch-aws-tags --help for the full public command list."
