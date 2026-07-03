#!/bin/bash

# AWS Tag Manager CLI - Installation Script
# Downloads the CLI binary from CDN and sets up required Docker services

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# CDN URLs
CDN_BASE_URL="https://d1b3wqbsyafyi0.cloudfront.net/tag-manager-cli"
INSTALL_SCRIPT_URL="${CDN_BASE_URL}/install"

# Installation configuration
BINARY_NAME="tag-manager"

# Detect appropriate installation directory
detect_install_dir() {
    # Check if running on macOS
    if [[ "$(uname -s)" == "Darwin" ]]; then
        # For macOS, prefer user-specific directories to avoid permission issues
        if [[ -w "$HOME/.local/bin" ]]; then
            INSTALL_DIR="$HOME/.local/bin"
        elif [[ -w "$HOME/bin" ]]; then
            INSTALL_DIR="$HOME/bin"
        elif [[ -w "$HOME/Library/Application Support" ]]; then
            INSTALL_DIR="$HOME/Library/Application Support/tag-manager/bin"
        elif [[ -w "/usr/local/bin" ]]; then
            INSTALL_DIR="/usr/local/bin"
        else
            # Fallback to creating a user directory
            INSTALL_DIR="$HOME/.local/bin"
        fi
    else
        # For Linux, check system directories first
        if [[ -w "/usr/local/bin" ]]; then
            INSTALL_DIR="/usr/local/bin"
        elif [[ -w "$HOME/.local/bin" ]]; then
            INSTALL_DIR="$HOME/.local/bin"
        elif [[ -w "$HOME/bin" ]]; then
            INSTALL_DIR="$HOME/bin"
        else
            # Fallback to creating a user directory
            INSTALL_DIR="$HOME/.local/bin"
        fi
    fi
    
    # Allow environment variable override
    if [[ -n "${TAG_MANAGER_INSTALL_DIR:-}" ]]; then
        INSTALL_DIR="$TAG_MANAGER_INSTALL_DIR"
    fi
}

# Call the detection function
detect_install_dir

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Function to print status messages
print_status() {
    echo -e "${GREEN}✓${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

# Check if Docker is installed and running
check_docker() {
    echo -e "\n${BLUE}Checking Docker installation...${NC}"
    
    if ! command -v docker &> /dev/null; then
        print_error "Docker is not installed. Please install Docker and try again."
        print_error "Visit: https://docs.docker.com/get-docker/"
        exit 1
    fi
    
    if ! docker info &> /dev/null; then
        print_error "Docker is not running. Please start Docker and try again."
        exit 1
    fi
    
    print_status "Docker is installed and running"
}

# Check if Docker Compose is available
check_docker_compose() {
    echo -e "\n${BLUE}Checking Docker Compose...${NC}"
    
    if docker compose version &> /dev/null; then
        COMPOSE_CMD="docker compose"
    elif command -v docker-compose &> /dev/null; then
        COMPOSE_CMD="docker-compose"
    else
        print_error "Docker Compose is not available. Please install Docker Compose and try again."
        exit 1
    fi
    
    print_status "Docker Compose is available ($COMPOSE_CMD)"
}

# Detect operating system and architecture
detect_platform() {
    echo -e "\n${BLUE}Detecting platform...${NC}"
    
    OS=$(uname -s | tr '[:upper:]' '[:lower:]')
    ARCH=$(uname -m)
    
    # Map OS names
    case "$OS" in
        darwin*)
            PLATFORM="macos"
            ;;
        linux*)
            PLATFORM="linux"
            ;;
        *)
            print_error "Unsupported operating system: $OS"
            exit 1
            ;;
    esac
    
    # Map architecture names
    case "$ARCH" in
        x86_64|amd64)
            ARCHITECTURE="x86_64"
            ;;
        arm64|aarch64)
            ARCHITECTURE="arm64"
            ;;
        *)
            print_error "Unsupported architecture: $ARCH"
            exit 1
            ;;
    esac
    
    # For macOS, we currently only have arm64 builds from M1/M2 runners
    if [ "$PLATFORM" = "macos" ]; then
        ARCHITECTURE="arm64"
        if [ "$ARCH" = "x86_64" ]; then
            print_warning "Running macOS on Intel - ARM64 binary will run via Rosetta 2"
        fi
    fi
    
    BINARY_FILE="tag-manager_${PLATFORM}_${ARCHITECTURE}"
    DOWNLOAD_URL="${CDN_BASE_URL}/latest/${BINARY_FILE}"
    
    print_status "Platform: $PLATFORM ($OS)"
    print_status "Architecture: $ARCHITECTURE ($ARCH)"
    print_status "Binary: $BINARY_FILE"
}

# Check for required tools
check_requirements() {
    echo -e "\n${BLUE}Checking requirements...${NC}"
    
    # Check for curl or wget
    if command -v curl &> /dev/null; then
        DOWNLOAD_CMD="curl -fsSL"
        print_status "Found curl for downloading"
    elif command -v wget &> /dev/null; then
        DOWNLOAD_CMD="wget -qO-"
        print_status "Found wget for downloading"
    else
        print_error "Neither curl nor wget found. Please install one of them."
        exit 1
    fi
    
    # Check permissions for the selected install directory
    echo "Selected installation directory: $INSTALL_DIR"
    
    # Check if we can write to the install directory or create it
    if [[ -d "$INSTALL_DIR" ]]; then
        if [[ -w "$INSTALL_DIR" ]]; then
            print_status "Installation directory is writable: $INSTALL_DIR"
            SUDO_CMD=""
        elif [[ "$INSTALL_DIR" == "/usr/local/bin" ]] && command -v sudo &> /dev/null; then
            print_status "Will use sudo for system directory installation"
            SUDO_CMD="sudo"
        else
            print_error "Cannot write to $INSTALL_DIR"
            print_error "Please run with sudo or set TAG_MANAGER_INSTALL_DIR to a writable location"
            print_error "Example: TAG_MANAGER_INSTALL_DIR=\$HOME/.local/bin $0"
            exit 1
        fi
    else
        # Directory doesn't exist, check if we can create it
        parent_dir=$(dirname "$INSTALL_DIR")
        if [[ -w "$parent_dir" ]]; then
            print_status "Will create installation directory: $INSTALL_DIR"
            SUDO_CMD=""
        elif [[ "$INSTALL_DIR" == "/usr/local/bin" ]] && command -v sudo &> /dev/null; then
            print_status "Will use sudo to create system directory"
            SUDO_CMD="sudo"
        else
            # Try to create the directory structure
            if mkdir -p "$INSTALL_DIR" 2>/dev/null; then
                print_status "Created installation directory: $INSTALL_DIR"
                SUDO_CMD=""
            else
                print_error "Cannot create directory: $INSTALL_DIR"
                print_error "Please ensure the parent directory exists and is writable"
                print_error "Or set TAG_MANAGER_INSTALL_DIR to a different location"
                exit 1
            fi
        fi
    fi
}

# Download the binary
download_binary() {
    echo -e "\n${BLUE}Downloading tag-manager CLI...${NC}"
    
    # Create temporary directory
    TEMP_DIR=$(mktemp -d)
    trap "rm -rf $TEMP_DIR" EXIT
    
    TEMP_BINARY="$TEMP_DIR/$BINARY_NAME"
    
    echo "Downloading from: $DOWNLOAD_URL"
    
    if [[ "$DOWNLOAD_CMD" == curl* ]]; then
        curl -fsSL "$DOWNLOAD_URL" -o "$TEMP_BINARY" || {
            print_error "Failed to download binary from $DOWNLOAD_URL"
            print_error "Please check your internet connection and try again"
            exit 1
        }
    else
        wget -q "$DOWNLOAD_URL" -O "$TEMP_BINARY" || {
            print_error "Failed to download binary from $DOWNLOAD_URL"
            print_error "Please check your internet connection and try again"
            exit 1
        }
    fi
    
    # Make binary executable
    chmod +x "$TEMP_BINARY"
    
    # Verify the binary works
    if "$TEMP_BINARY" --version &> /dev/null; then
        print_status "Binary downloaded and verified successfully"
    else
        print_warning "Binary downloaded but verification failed"
        print_warning "The binary may still work correctly"
    fi
    
    echo "$TEMP_BINARY"
}

# Install the binary
install_binary() {
    echo -e "\n${BLUE}Installing tag-manager CLI...${NC}"
    
    local SOURCE_BINARY="$1"
    local TARGET_PATH="$INSTALL_DIR/$BINARY_NAME"
    
    # Create installation directory if it doesn't exist
    if [ ! -d "$INSTALL_DIR" ]; then
        if [ -n "$SUDO_CMD" ]; then
            $SUDO_CMD mkdir -p "$INSTALL_DIR"
        else
            mkdir -p "$INSTALL_DIR"
        fi
    fi
    
    # Copy binary to installation directory
    if [ -n "$SUDO_CMD" ]; then
        echo "Installing to $TARGET_PATH (requires sudo)..."
        $SUDO_CMD cp "$SOURCE_BINARY" "$TARGET_PATH"
        $SUDO_CMD chmod 755 "$TARGET_PATH"
    else
        echo "Installing to $TARGET_PATH..."
        cp "$SOURCE_BINARY" "$TARGET_PATH"
        chmod 755 "$TARGET_PATH"
    fi
    
    print_status "Binary installed to $TARGET_PATH"
    
    # Check if installation directory is in PATH
    if [[ ":$PATH:" != *":$INSTALL_DIR:"* ]]; then
        print_warning "$INSTALL_DIR is not in your PATH"
        
        # Detect shell and provide instructions
        SHELL_NAME=$(basename "$SHELL")
        case "$SHELL_NAME" in
            bash)
                PROFILE_FILE="$HOME/.bashrc"
                ;;
            zsh)
                PROFILE_FILE="$HOME/.zshrc"
                ;;
            *)
                PROFILE_FILE="$HOME/.profile"
                ;;
        esac
        
        echo ""
        echo "Add the following line to your $PROFILE_FILE:"
        echo ""
        echo "  export PATH=\"$INSTALL_DIR:\$PATH\""
        echo ""
        echo "Then reload your shell configuration:"
        echo "  source $PROFILE_FILE"
        echo ""
        echo "Or run the binary directly:"
        echo "  $TARGET_PATH"
    else
        print_status "$INSTALL_DIR is already in PATH"
    fi
}

# Create missing Docker configuration files
create_docker_config_files() {
    echo -e "\n${BLUE}Creating Docker configuration files...${NC}"
    
    # Create config directory if it doesn't exist
    mkdir -p config
    
    # Create init-db.sql file if it doesn't exist
    if [ ! -f "config/init-db.sql" ]; then
        cat > config/init-db.sql << 'EOF'
-- PostgreSQL initialization script for Tag Manager CLI
-- This script runs automatically when the PostgreSQL container starts

-- Create the tag_manager database (if it doesn't already exist)
-- Note: The database is already created by POSTGRES_DB environment variable
-- but we include this for completeness

-- Set up any database-level configurations
-- Enable necessary extensions if needed
-- CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Log successful initialization
SELECT 'Tag Manager CLI PostgreSQL database initialized successfully' AS status;
EOF
        print_status "Created config/init-db.sql"
    else
        print_status "config/init-db.sql already exists"
    fi
    
    # Create redis.conf file if it doesn't exist
    if [ ! -f "config/redis.conf" ]; then
        cat > config/redis.conf << 'EOF'
# Redis configuration for Tag Manager CLI

# Basic settings
bind 0.0.0.0
port 6379
timeout 300
tcp-keepalive 60

# Memory and persistence
maxmemory 512mb
maxmemory-policy allkeys-lru
save 60 1000

# Logging
loglevel notice
logfile ""

# Security
# requirepass your_redis_password_here  # Uncomment and set password for production

# Persistence
dir /data
dbfilename dump.rdb
appendonly yes
appendfsync everysec

# Network
tcp-backlog 511

# General
databases 16
EOF
        print_status "Created config/redis.conf"
    else
        print_status "config/redis.conf already exists"
    fi
}

# Create .env file with default values
create_env_file() {
    echo -e "\n${BLUE}Creating .env file...${NC}"
    
    if [ -f ".env" ]; then
        print_warning ".env file already exists. Keeping existing configuration."
        return
    fi
    
    cat > .env << 'EOF'
# AWS Tag Manager CLI - Environment Configuration
# You can modify these values to customize your setup

# AWS Configuration  
# Note: Update AWS_PROFILE to match your AWS SSO profile name
AWS_PROFILE=default
AWS_REGION=us-east-1

# Database Configuration
DATABASE_URL=postgresql://tag_manager:tag_manager_dev_password@localhost:5432/tag_manager
POSTGRES_DB=tag_manager
POSTGRES_USER=tag_manager
POSTGRES_PASSWORD=tag_manager_dev_password

# Redis Configuration
REDIS_URL=redis://localhost:6379/0
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0

# Celery Configuration
CELERY_BROKER_URL=redis://localhost:6379/1
CELERY_RESULT_BACKEND=redis://localhost:6379/2

# Application Configuration
TAG_MANAGER_DEBUG=0

# Optional: Enable monitoring services (flower for Celery, pgadmin for PostgreSQL)
# Uncomment the line below to enable monitoring services
# COMPOSE_PROFILES=monitoring,gui
EOF
    
    print_status ".env file created with default values"
    print_warning "IMPORTANT: Update AWS_PROFILE in .env to match your AWS SSO profile"
}

# Build and start Docker Compose services
start_services() {
    echo -e "\n${BLUE}Starting Docker Compose services...${NC}"
    
    # Check if docker-compose.yml exists
    if [ ! -f "docker-compose.yml" ]; then
        print_error "docker-compose.yml not found in current directory"
        print_error "Please ensure you're in the tag-manager-cli directory"
        exit 1
    fi
    
    # Pull latest images
    echo "Pulling Docker images..."
    $COMPOSE_CMD pull postgres redis
    
    # Start core services (postgres, redis)
    echo "Starting core services..."
    $COMPOSE_CMD up -d postgres redis
    
    print_status "Core services started (PostgreSQL, Redis)"
    
    # Note about Celery workers
    print_warning "Note: Celery workers are not started automatically"
    print_warning "If you need background task processing, start them with:"
    echo "  $COMPOSE_CMD up -d celery-worker celery-beat"
}

# Wait for services to be healthy
wait_for_services() {
    echo -e "\n${BLUE}Waiting for services to be ready...${NC}"
    
    # Wait for PostgreSQL
    echo "Waiting for PostgreSQL..."
    for i in {1..30}; do
        if $COMPOSE_CMD exec -T postgres pg_isready -U tag_manager -d tag_manager &>/dev/null; then
            break
        fi
        sleep 2
    done
    
    if $COMPOSE_CMD exec -T postgres pg_isready -U tag_manager -d tag_manager &>/dev/null; then
        print_status "PostgreSQL is ready"
    else
        print_warning "PostgreSQL may not be fully ready yet"
    fi
    
    # Wait for Redis
    echo "Waiting for Redis..."
    for i in {1..15}; do
        if $COMPOSE_CMD exec -T redis redis-cli ping &>/dev/null; then
            break
        fi
        sleep 2
    done
    
    if $COMPOSE_CMD exec -T redis redis-cli ping &>/dev/null; then
        print_status "Redis is ready"
    else
        print_warning "Redis may not be fully ready yet"
    fi
}

# Setup AWS configuration
setup_aws() {
    echo -e "\n${BLUE}AWS Configuration${NC}"
    echo "=================="
    
    # Check if AWS CLI is installed
    if command -v aws &> /dev/null; then
        print_status "AWS CLI is installed"
        
        # Check if AWS is configured
        if aws sts get-caller-identity &> /dev/null; then
            print_status "AWS credentials are configured"
            
            # Show current identity
            echo ""
            echo "Current AWS identity:"
            aws sts get-caller-identity --output table
            echo ""
            print_status "Ready for production setup!"
            echo "Run 'tag-manager setup wizard' to complete configuration"
        else
            print_warning "AWS CLI found but not configured"
            echo ""
            echo "To configure AWS SSO, run:"
            echo "  aws configure sso"
            echo ""
            echo "Then set your profile:"
            echo "  export AWS_PROFILE=your-profile-name"
            echo ""
            echo "Finally, run the setup wizard:"
            echo "  tag-manager setup wizard"
        fi
    else
        print_warning "AWS CLI not installed"
        echo ""
        echo "To install AWS CLI:"
        echo "  macOS: brew install awscli"
        echo "  Linux: pip install awscli or use your package manager"
        echo ""
        echo "After installation, configure with:"
        echo "  aws configure sso"
        echo "  tag-manager setup wizard"
    fi
}

# Display connection information
show_connection_info() {
    echo -e "\n${BLUE}Service Connection Information:${NC}"
    echo "================================"
    echo "PostgreSQL:"
    echo "  Host: localhost"
    echo "  Port: 5432"
    echo "  Database: tag_manager"
    echo "  Username: tag_manager"
    echo "  Password: tag_manager_dev_password"
    echo ""
    echo "Redis:"
    echo "  Host: localhost"
    echo "  Port: 6379"
    echo "  Database: 0 (cache), 1 (broker), 2 (results)"
    echo ""
    echo "Docker Commands:"
    echo "  View logs: $COMPOSE_CMD logs -f"
    echo "  Stop services: $COMPOSE_CMD down"
    echo "  Restart services: $COMPOSE_CMD restart"
    echo "  Start workers: $COMPOSE_CMD up -d celery-worker celery-beat"
}

# Post-installation instructions
show_next_steps() {
    echo -e "\n${GREEN}Installation completed successfully!${NC}"
    echo ""
    echo "${BLUE}Next steps:${NC}"
    echo "==========="
    echo ""
    
    if [[ ":$PATH:" == *":$INSTALL_DIR:"* ]]; then
        echo "1. Run the setup wizard to configure everything:"
        echo "   $BINARY_NAME setup wizard"
        echo ""
        echo "2. Or configure manually:"
        echo "   aws configure sso"
        echo "   export AWS_PROFILE=your-profile-name"
        echo "   $BINARY_NAME setup wizard --skip-aws"
    else
        echo "1. Add $INSTALL_DIR to your PATH (see instructions above)"
        echo ""
        echo "2. Run the setup wizard:"
        echo "   $INSTALL_DIR/$BINARY_NAME setup wizard"
        echo ""
        echo "3. Or configure manually:"
        echo "   aws configure sso"
        echo "   export AWS_PROFILE=your-profile-name"
        echo "   $INSTALL_DIR/$BINARY_NAME setup wizard --skip-aws"
    fi
    
    echo ""
    echo "${BLUE}Production Setup Commands:${NC}"
    echo "  $BINARY_NAME setup wizard              # Complete guided setup"
    echo "  $BINARY_NAME setup validate            # Verify system health"
    echo "  $BINARY_NAME service status            # Check worker service"
    echo "  $BINARY_NAME service logs              # View service logs"
    echo ""
    echo "${BLUE}Common commands:${NC}"
    echo "  $BINARY_NAME interactive              # Start interactive mode"
    echo "  $BINARY_NAME cost report              # CUR-powered cost analysis"
    echo "  $BINARY_NAME resource-organization     # Organize resources"
    echo "  $BINARY_NAME unified-tags              # Manage unified tags"
    echo "  $BINARY_NAME --help                    # Show all commands"
    echo ""
    echo "${BLUE}Docker Services (Optional):${NC}"
    echo "  $COMPOSE_CMD ps                        # Check service status"
    echo "  $COMPOSE_CMD logs -f                   # View service logs"
    echo "  $COMPOSE_CMD down                      # Stop all services"
    echo "  $COMPOSE_CMD up -d                     # Start all services"
    echo ""
    echo "${BLUE}Local Features:${NC}"
    echo "  • User-owned AWS profiles and SSO"
    echo "  • Local dashboard and CLI workflows"
    echo "  • Optional webhook notifications"
    echo "  • Comprehensive error reporting and diagnostics"
    echo ""
    echo "For more information, visit:"
    echo "  https://github.com/bluearch-io/tag-manager-cli"
}

# Uninstall function
uninstall() {
    echo -e "\n${BLUE}Uninstalling tag-manager CLI...${NC}"
    
    # Try to detect where the binary was installed
    detect_install_dir
    
    # Remove binary
    local TARGET_PATH="$INSTALL_DIR/$BINARY_NAME"
    
    if [ -f "$TARGET_PATH" ]; then
        if [ -n "$SUDO_CMD" ]; then
            $SUDO_CMD rm -f "$TARGET_PATH"
        else
            rm -f "$TARGET_PATH"
        fi
        print_status "Removed $TARGET_PATH"
    else
        print_warning "$TARGET_PATH not found"
    fi
    
    # Check alternative locations including macOS specific paths
    for dir in "/usr/local/bin" "$HOME/.local/bin" "$HOME/bin" "$HOME/Library/Application Support/tag-manager/bin"; do
        if [ -f "$dir/$BINARY_NAME" ]; then
            print_warning "Found binary at $dir/$BINARY_NAME"
            read -p "Do you want to remove this binary? (y/N) " -n 1 -r
            echo ""
            if [[ $REPLY =~ ^[Yy]$ ]]; then
                if [[ -w "$dir/$BINARY_NAME" ]]; then
                    rm -f "$dir/$BINARY_NAME"
                    print_status "Removed $dir/$BINARY_NAME"
                else
                    sudo rm -f "$dir/$BINARY_NAME"
                    print_status "Removed $dir/$BINARY_NAME (with sudo)"
                fi
            fi
        fi
    done
    
    # Ask about Docker services
    echo ""
    read -p "Do you want to stop and remove Docker services? (y/N) " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        if [ -f "docker-compose.yml" ] && command -v docker &> /dev/null; then
            echo "Stopping Docker services..."
            $COMPOSE_CMD down -v
            print_status "Docker services stopped and volumes removed"
        fi
    else
        print_warning "Docker services left running"
        echo "To stop them manually, run: $COMPOSE_CMD down"
    fi
    
    echo ""
    print_status "Uninstallation complete"
}

# Update function
update() {
    echo -e "\n${BLUE}Updating tag-manager CLI...${NC}"
    
    # Check current version if binary exists
    if command -v $BINARY_NAME &> /dev/null; then
        CURRENT_VERSION=$($BINARY_NAME --version 2>/dev/null || echo "unknown")
        echo "Current version: $CURRENT_VERSION"
    fi
    
    # Detect installation directory first
    detect_install_dir
    
    # Download and install new binary
    detect_platform
    check_requirements
    TEMP_BINARY=$(download_binary)
    install_binary "$TEMP_BINARY"
    
    # Update Docker images
    echo ""
    echo "Updating Docker images..."
    if [ -f "docker-compose.yml" ] && command -v docker &> /dev/null; then
        $COMPOSE_CMD pull
        print_status "Docker images updated"
        
        echo ""
        read -p "Do you want to restart services with updated images? (y/N) " -n 1 -r
        echo ""
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            $COMPOSE_CMD restart
            print_status "Services restarted with updated images"
        fi
    fi
    
    print_status "Update complete!"
}

# Main installation process
main() {
    echo -e "${BLUE}AWS Tag Manager CLI Installer${NC}"
    echo "=============================="
    echo -e "${CYAN}Local-first AWS tagging and governance tooling${NC}"
    echo ""
    
    # Check Docker and Docker Compose first (optional for production)
    if command -v docker &> /dev/null; then
        check_docker
        check_docker_compose
        DOCKER_AVAILABLE=true
    else
        print_warning "Docker not found - Docker services will not be available"
        print_warning "This is OK for production deployment (services run in AWS)"
        DOCKER_AVAILABLE=false
    fi
    
    # Detect installation directory first
    detect_install_dir
    
    # Detect platform and download binary
    detect_platform
    check_requirements
    
    # Download and install binary
    TEMP_BINARY=$(download_binary)
    install_binary "$TEMP_BINARY"
    
    # Setup Docker environment (optional)
    if [[ "$DOCKER_AVAILABLE" == "true" ]]; then
        create_docker_config_files
        create_env_file
        
        read -p "Start Docker services? (y/N): " start_docker
        if [[ "$start_docker" =~ ^[Yy]$ ]]; then
            start_services
            wait_for_services
        else
            print_safe "Docker services not started - can be started later with: make docker-up"
        fi
    fi
    
    # Setup AWS
    setup_aws
    
    # Show final information
    if [[ "$DOCKER_AVAILABLE" == "true" ]]; then
        show_connection_info
    fi
    show_next_steps
}

# Parse command line arguments
case "${1:-}" in
    uninstall|--uninstall|-u)
        check_docker_compose
        uninstall
        ;;
    update|--update|-U)
        check_docker_compose
        update
        ;;
    services|--services)
        check_docker_compose
        echo -e "${BLUE}Managing Docker services...${NC}"
        case "${2:-}" in
            start)
                $COMPOSE_CMD up -d
                print_status "Services started"
                ;;
            stop)
                $COMPOSE_CMD down
                print_status "Services stopped"
                ;;
            restart)
                $COMPOSE_CMD restart
                print_status "Services restarted"
                ;;
            status)
                $COMPOSE_CMD ps
                ;;
            logs)
                $COMPOSE_CMD logs -f
                ;;
            *)
                echo "Usage: $0 services [start|stop|restart|status|logs]"
                ;;
        esac
        ;;
    help|--help|-h)
        echo "AWS Tag Manager CLI Installer"
        echo ""
        echo "Usage: $0 [OPTION]"
        echo ""
        echo "Options:"
        echo "  (no option)         Install tag-manager CLI and setup services"
        echo "  update, --update    Update CLI binary and Docker images"
        echo "  uninstall           Remove tag-manager CLI and optionally services"
        echo "  services [cmd]      Manage Docker services"
        echo "    start             Start all services"
        echo "    stop              Stop all services"
        echo "    restart           Restart all services"
        echo "    status            Show service status"
        echo "    logs              Show service logs"
        echo "  help, --help        Show this help message"
        echo ""
        echo "Environment variables:"
        echo "  INSTALL_DIR         Installation directory (default: /usr/local/bin)"
        echo ""
        echo "Examples:"
        echo "  $0                  # Install tag-manager and setup services"
        echo "  $0 update           # Update to latest version"
        echo "  $0 uninstall        # Remove tag-manager"
        echo "  $0 services start   # Start Docker services"
        echo "  $0 services logs    # View service logs"
        echo ""
        echo "For more information, visit:"
        echo "  https://github.com/bluearch-io/tag-manager-cli"
        ;;
    *)
        main
        ;;
esac
