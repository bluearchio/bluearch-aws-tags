#!/bin/bash

# AWS Tag Manager CLI - Complete Clean Uninstall Script
# Removes all components for clean testing

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

echo -e "${BLUE}==================================================================================="
echo -e "   AWS Tag Manager CLI - Complete Clean Uninstall"
echo -e "==================================================================================="
echo -e "${NC}"

echo -e "${YELLOW}This will remove ALL Tag Manager CLI components including:${NC}"
echo -e "  - Binary installations (/usr/local/bin, ~/.local/bin)"
echo -e "  - System services (systemd/launchd)"
echo -e "  - Configuration files and directories"
echo -e "  - Python virtual environments"
echo -e "  - Docker containers and volumes"
echo -e "  - Local development files"
echo -e "  - AWS DynamoDB tables (optional)"
echo -e "  - AWS Parameter Store entries (optional)"
echo

read -p "Continue with complete uninstall? (y/N): " confirm
if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
    echo -e "${YELLOW}Uninstall cancelled${NC}"
    exit 0
fi

echo -e "${CYAN}Starting clean uninstall...${NC}"

# 1. Stop and remove system services
echo -e "${YELLOW}[1/10] Stopping and removing system services...${NC}"

if command -v systemctl &> /dev/null; then
    # Linux systemd
    echo "  Stopping systemd service..."
    sudo systemctl stop tag-manager-worker 2>/dev/null || true
    sudo systemctl disable tag-manager-worker 2>/dev/null || true
    sudo rm -f /etc/systemd/system/tag-manager-worker.service
    sudo systemctl daemon-reload 2>/dev/null || true
    echo "  [OK] systemd service removed"
elif [[ "$OSTYPE" == "darwin"* ]]; then
    # macOS launchd
    echo "  Stopping launchd service..."
    launchctl unload ~/Library/LaunchAgents/com.bluearch.tag-manager-worker.plist 2>/dev/null || true
    rm -f ~/Library/LaunchAgents/com.bluearch.tag-manager-worker.plist
    echo "  [OK] launchd service removed"
fi

# 2. Remove binary installations
echo -e "${YELLOW}[2/10] Removing binary installations...${NC}"

# Remove from common installation paths
sudo rm -f /usr/local/bin/tag-manager 2>/dev/null || true
rm -f ~/.local/bin/tag-manager 2>/dev/null || true
sudo rm -f /opt/tag-manager/tag-manager 2>/dev/null || true
sudo rm -rf /opt/tag-manager 2>/dev/null || true

# Remove symlinks
sudo rm -f /usr/bin/tag-manager 2>/dev/null || true
rm -f ~/bin/tag-manager 2>/dev/null || true

echo "  [OK] Binary installations removed"

# 3. Remove configuration directories
echo -e "${YELLOW}[3/10] Removing configuration directories...${NC}"

rm -rf ~/.tag-manager 2>/dev/null || true
rm -rf ~/.config/tag-manager 2>/dev/null || true
sudo rm -rf /etc/tag-manager 2>/dev/null || true
rm -rf ~/Library/Application\ Support/tag-manager 2>/dev/null || true

echo "  [OK] Configuration directories removed"

# 4. Remove environment files
echo -e "${YELLOW}[4/10] Removing environment files...${NC}"

rm -f ~/.env.tag-manager 2>/dev/null || true
rm -f .env.production 2>/dev/null || true
rm -f .env.development 2>/dev/null || true
rm -f .env.local 2>/dev/null || true

echo "  [OK] Environment files removed"

# 5. Stop and remove Docker containers/volumes
echo -e "${YELLOW}[5/10] Removing Docker containers and volumes...${NC}"

if command -v docker &> /dev/null; then
    # Stop containers
    docker stop tag-manager-postgres tag-manager-redis tag-manager-worker 2>/dev/null || true
    
    # Remove containers
    docker rm tag-manager-postgres tag-manager-redis tag-manager-worker 2>/dev/null || true
    
    # Remove volumes
    docker volume rm tag-manager_postgres_data tag-manager_redis_data 2>/dev/null || true
    
    # Remove networks
    docker network rm tag-manager_default 2>/dev/null || true
    
    echo "  [OK] Docker components removed"
else
    echo "  [SKIP] Docker not installed"
fi

# 6. Remove Python virtual environments
echo -e "${YELLOW}[6/10] Removing Python virtual environments...${NC}"

rm -rf .venv 2>/dev/null || true
rm -rf venv 2>/dev/null || true
rm -rf ~/.virtualenvs/tag-manager 2>/dev/null || true

echo "  [OK] Python virtual environments removed"

# 7. Remove development files
echo -e "${YELLOW}[7/10] Removing development files...${NC}"

rm -rf dist 2>/dev/null || true
rm -rf build 2>/dev/null || true
rm -rf *.egg-info 2>/dev/null || true
rm -rf __pycache__ 2>/dev/null || true
find . -name "*.pyc" -delete 2>/dev/null || true
find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true

echo "  [OK] Development files removed"

# 8. Remove logs and cache
echo -e "${YELLOW}[8/10] Removing logs and cache files...${NC}"

rm -rf ~/.cache/tag-manager 2>/dev/null || true
rm -rf /var/log/tag-manager 2>/dev/null || true
sudo rm -rf /var/log/tag-manager 2>/dev/null || true
rm -f tag-manager.log 2>/dev/null || true
rm -f worker.log 2>/dev/null || true

echo "  [OK] Logs and cache removed"

# 9. Remove pip installations
echo -e "${YELLOW}[9/10] Removing pip installations...${NC}"

if command -v pip &> /dev/null; then
    pip uninstall tag-manager-cli -y 2>/dev/null || true
    pip uninstall tag_manager_cli -y 2>/dev/null || true
    echo "  [OK] Pip installations removed"
else
    echo "  [SKIP] Pip not available"
fi

# 10. Optional: AWS resources cleanup
echo -e "${YELLOW}[10/10] AWS resources cleanup (optional)...${NC}"

read -p "Remove AWS DynamoDB tables and Parameter Store entries? (y/N): " aws_cleanup
if [[ "$aws_cleanup" =~ ^[Yy]$ ]]; then
    if command -v aws &> /dev/null; then
        echo "  Removing DynamoDB tables..."
        aws dynamodb delete-table --table-name tag-manager-config 2>/dev/null || true
        
        echo "  Removing Parameter Store entries..."
        aws ssm delete-parameter --name "/tag-manager/dev/sqs-queue-url" 2>/dev/null || true
        aws ssm delete-parameter --name "/tag-manager/prod/sqs-queue-url" 2>/dev/null || true
        
        echo "  [OK] AWS resources cleanup completed"
    else
        echo "  [SKIP] AWS CLI not available"
    fi
else
    echo "  [SKIP] AWS resources cleanup skipped"
fi

# Final cleanup verification
echo -e "${CYAN}Verifying cleanup...${NC}"

# Check if binary still exists
if command -v tag-manager &> /dev/null; then
    echo -e "${YELLOW}  [WARN] tag-manager binary still found in PATH${NC}"
    echo -e "  Location: $(which tag-manager)"
else
    echo -e "${GREEN}  [OK] No tag-manager binary found in PATH${NC}"
fi

# Check for remaining processes
if pgrep -f "tag-manager" &> /dev/null; then
    echo -e "${YELLOW}  [WARN] Tag Manager processes still running${NC}"
    pgrep -af "tag-manager"
else
    echo -e "${GREEN}  [OK] No Tag Manager processes running${NC}"
fi

echo -e "${GREEN}==================================================================================="
echo -e "   Clean Uninstall Complete!"
echo -e "==================================================================================="
echo -e "${NC}"

echo -e "${CYAN}To test clean installation, run:${NC}"
echo -e "  ${BLUE}curl -sSL https://your-domain.com/install | bash${NC}"
echo -e "  ${BLUE}# OR for development:${NC}"
echo -e "  ${BLUE}curl -sSL https://your-domain.com/install | ENVIRONMENT=dev bash${NC}"
echo
echo -e "${CYAN}To reinstall from local development:${NC}"
echo -e "  ${BLUE}./install.sh${NC}"
echo
