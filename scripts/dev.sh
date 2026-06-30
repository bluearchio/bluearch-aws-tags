#!/bin/bash
# Development utility scripts for AWS Tag Manager CLI

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if virtual environment is activated
check_venv() {
    if [[ -z "$VIRTUAL_ENV" ]]; then
        print_warning "Virtual environment not activated. Activating .venv..."
        if [[ -f ".venv/bin/activate" ]]; then
            source .venv/bin/activate
            print_status "Virtual environment activated"
        else
            print_error "Virtual environment not found. Run 'python -m venv .venv' first"
            exit 1
        fi
    else
        print_status "Virtual environment is active: $VIRTUAL_ENV"
    fi
}

# Install dependencies
install() {
    print_status "Installing dependencies..."
    pip install -r requirements.txt
    pip install -e .
    print_status "Dependencies installed successfully"
}

# Run code formatting
format() {
    print_status "Formatting code with black..."
    black tag_manager_cli/
    print_status "Code formatted successfully"
}

# Run linting
lint() {
    print_status "Running flake8 linting..."
    flake8 tag_manager_cli/
    print_status "Linting completed successfully"
}

# Run type checking
typecheck() {
    print_status "Running mypy type checking..."
    mypy tag_manager_cli/
    print_status "Type checking completed successfully"
}

# Run tests
test() {
    print_status "Running pytest..."
    pytest
    print_status "Tests completed successfully"
}

# Run all quality checks
quality() {
    print_status "Running all quality checks..."
    format
    lint
    typecheck
    test
    print_status "All quality checks passed!"
}

# Run the application in interactive mode
run() {
    print_status "Starting Tag Manager CLI in interactive mode..."
    python -m tag_manager_cli.main
}

# Run with specific command
run_cmd() {
    if [[ -z "$1" ]]; then
        print_error "Usage: $0 run-cmd <command> [args...]"
        exit 1
    fi
    print_status "Running command: $*"
    python -m tag_manager_cli.main "$@"
}

# Clean up generated files
clean() {
    print_status "Cleaning up generated files..."
    find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
    find . -type f -name "*.pyc" -delete 2>/dev/null || true
    find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
    rm -rf .pytest_cache/ 2>/dev/null || true
    rm -rf .mypy_cache/ 2>/dev/null || true
    print_status "Cleanup completed"
}

# Show help
help() {
    echo "AWS Tag Manager CLI Development Script"
    echo ""
    echo "Usage: $0 <command>"
    echo ""
    echo "Commands:"
    echo "  install     Install dependencies"
    echo "  format      Format code with black"
    echo "  lint        Run flake8 linting"
    echo "  typecheck   Run mypy type checking"
    echo "  test        Run pytest"
    echo "  quality     Run all quality checks (format, lint, typecheck, test)"
    echo "  run         Run the CLI in interactive mode"
    echo "  run-cmd     Run a specific CLI command"
    echo "  clean       Clean up generated files"
    echo "  help        Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0 quality"
    echo "  $0 run"
    echo "  $0 run-cmd cost report --tag-key Environment"
}

# Main script logic
main() {
    if [[ $# -eq 0 ]]; then
        help
        exit 0
    fi

    # Always check virtual environment for commands that need it
    case "$1" in
        install|format|lint|typecheck|test|quality|run|run-cmd)
            check_venv
            ;;
    esac

    case "$1" in
        install)
            install
            ;;
        format)
            format
            ;;
        lint)
            lint
            ;;
        typecheck)
            typecheck
            ;;
        test)
            test
            ;;
        quality)
            quality
            ;;
        run)
            run
            ;;
        run-cmd)
            shift
            run_cmd "$@"
            ;;
        clean)
            clean
            ;;
        help|--help|-h)
            help
            ;;
        *)
            print_error "Unknown command: $1"
            echo ""
            help
            exit 1
            ;;
    esac
}

main "$@"