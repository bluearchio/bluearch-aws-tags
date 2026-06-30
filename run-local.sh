#!/bin/bash

# AWS Tag Manager CLI - Local Development Runner
# This script helps you run the CLI locally with Python or Docker

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_color() {
    color=$1
    message=$2
    echo -e "${color}${message}${NC}"
}

# Function to check prerequisites
check_prerequisites() {
    print_color "$BLUE" "Checking prerequisites..."
    
    # Check Python
    if command -v python3 &> /dev/null; then
        print_color "$GREEN" "✓ Python3 found: $(python3 --version)"
    else
        print_color "$RED" "✗ Python3 not found"
        exit 1
    fi
    
    # Check Docker
    if command -v docker &> /dev/null; then
        print_color "$GREEN" "✓ Docker found: $(docker --version)"
    else
        print_color "$YELLOW" "⚠ Docker not found (needed for containers)"
    fi
    
    # Check AWS Profile
    if [ -n "$AWS_PROFILE" ]; then
        print_color "$GREEN" "✓ AWS Profile set: $AWS_PROFILE"
    else
        print_color "$YELLOW" "⚠ AWS_PROFILE not set (using default)"
    fi
}

# Function to setup Python environment
setup_python_env() {
    print_color "$BLUE" "Setting up Python environment..."
    
    # Create virtual environment if it doesn't exist
    if [ ! -d ".venv" ]; then
        print_color "$YELLOW" "Creating virtual environment..."
        python3 -m venv .venv
    fi
    
    # Activate virtual environment
    source .venv/bin/activate
    
    # Install dependencies
    print_color "$YELLOW" "Installing dependencies..."
    pip install -q --upgrade pip
    pip install -q -r requirements.txt
    pip install -q -e .
    
    print_color "$GREEN" "✓ Python environment ready"
}

# Function to run CLI with Python
run_python_cli() {
    setup_python_env
    print_color "$BLUE" "Running Tag Manager CLI with Python..."
    echo ""
    python3 -m tag_manager_cli.main "$@"
}

# Function to build local Docker containers
build_local_containers() {
    print_color "$BLUE" "Building local Docker containers..."
    docker compose -f docker-compose.local.yml build
    print_color "$GREEN" "✓ Containers built successfully"
}

# Function to start local Docker services
start_docker_services() {
    print_color "$BLUE" "Starting Docker services..."
    
    # Stop ALL existing tag-manager containers (both compose files and any stragglers)
    print_color "$YELLOW" "Stopping existing containers..."
    docker compose -f docker-compose.yml down 2>/dev/null || true
    docker compose -f docker-compose.local.yml down 2>/dev/null || true
    
    # Force stop and remove containers by name pattern
    docker ps -a --format '{{.Names}}' | grep -E "tag-manager-" | xargs -r docker rm -f 2>/dev/null || true
    
    # Clean up any orphaned volumes
    docker volume prune -f 2>/dev/null || true
    
    # Start local containers with force recreate
    print_color "$BLUE" "Starting fresh local containers..."
    docker compose -f docker-compose.local.yml up -d --force-recreate --remove-orphans
    
    # Wait for services to be healthy
    print_color "$YELLOW" "Waiting for services to be healthy..."
    sleep 15
    
    # Check service health
    if docker compose -f docker-compose.local.yml ps | grep -q "healthy"; then
        print_color "$GREEN" "✓ All services healthy"
    else
        print_color "$YELLOW" "⚠ Some services may not be ready yet"
    fi
    
    print_color "$GREEN" "Services started:"
    docker compose -f docker-compose.local.yml ps
}

# Function to stop Docker services
stop_docker_services() {
    print_color "$BLUE" "Stopping Docker services..."
    docker compose -f docker-compose.local.yml down
    print_color "$GREEN" "✓ Services stopped"
}

# Function to view logs
view_logs() {
    service=$1
    if [ -z "$service" ]; then
        docker compose -f docker-compose.local.yml logs -f
    else
        docker compose -f docker-compose.local.yml logs -f "$service"
    fi
}

# Main menu
show_menu() {
    echo ""
    print_color "$BLUE" "=== AWS Tag Manager CLI - Local Development ==="
    echo ""
    echo "1) Run CLI with Python (local)"
    echo "2) Build Docker containers locally"
    echo "3) Start Docker services (local build)"
    echo "4) Stop Docker services"
    echo "5) View Docker logs"
    echo "6) Run both Python CLI and Docker services"
    echo "7) Quick test (discover resources)"
    echo "8) Clean up ALL Docker containers"
    echo "9) Exit"
    echo ""
    read -p "Select an option: " choice
    
    case $choice in
        1)
            shift
            run_python_cli "$@"
            ;;
        2)
            build_local_containers
            ;;
        3)
            build_local_containers
            start_docker_services
            ;;
        4)
            stop_docker_services
            ;;
        5)
            read -p "Service name (leave empty for all): " service
            view_logs "$service"
            ;;
        6)
            # Stop all existing containers first
            print_color "$YELLOW" "Stopping any existing containers..."
            docker compose -f docker-compose.yml down 2>/dev/null || true
            docker compose -f docker-compose.local.yml down 2>/dev/null || true
            docker ps -a --format '{{.Names}}' | grep -E "tag-manager-" | xargs -r docker rm -f 2>/dev/null || true
            
            # Now build and start fresh
            build_local_containers
            start_docker_services
            setup_python_env
            print_color "$GREEN" "✓ Both Python and Docker environments ready!"
            print_color "$YELLOW" "Run: python3 -m tag_manager_cli.main --help"
            ;;
        7)
            setup_python_env
            print_color "$BLUE" "Running quick test..."
            python3 -m tag_manager_cli.main workers discover ec2 --region us-east-1
            ;;
        8)
            print_color "$RED" "Cleaning up ALL Docker containers..."
            docker compose -f docker-compose.yml down -v 2>/dev/null || true
            docker compose -f docker-compose.local.yml down -v 2>/dev/null || true
            docker ps -a --format '{{.Names}}' | grep -E "tag-manager-" | xargs -r docker rm -f 2>/dev/null || true
            print_color "$GREEN" "✓ All tag-manager containers removed"
            ;;
        9)
            exit 0
            ;;
        *)
            print_color "$RED" "Invalid option"
            show_menu
            ;;
    esac
}

# Parse command line arguments
if [ $# -eq 0 ]; then
    check_prerequisites
    show_menu
else
    case "$1" in
        python)
            shift
            run_python_cli "$@"
            ;;
        docker-build)
            build_local_containers
            ;;
        docker-start)
            build_local_containers
            start_docker_services
            ;;
        docker-stop)
            stop_docker_services
            ;;
        docker-logs)
            shift
            view_logs "$@"
            ;;
        test)
            setup_python_env
            python3 -m tag_manager_cli.main workers discover ec2 --region us-east-1
            ;;
        *)
            run_python_cli "$@"
            ;;
    esac
fi