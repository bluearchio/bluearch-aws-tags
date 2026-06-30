# AWS Tag Manager CLI - Development Makefile

.PHONY: help install format lint typecheck test quality run clean venv web-restart

# Default target
.DEFAULT_GOAL := help

# Virtual environment activation
VENV_PATH = .venv
VENV_ACTIVATE = $(VENV_PATH)/bin/activate
PYTHON = $(VENV_PATH)/bin/python
PIP = $(VENV_PATH)/bin/pip

help:  ## Show this help message
	@echo "AWS Tag Manager CLI - Development Commands"
	@echo ""
	@echo "Available targets:"
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  %-12s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

venv:  ## Create virtual environment
	python3 -m venv $(VENV_PATH)
	$(PIP) install --upgrade pip

install: venv  ## Install dependencies
	$(PIP) install -r requirements.txt
	$(PIP) install -e .

format:  ## Format code with black
	$(PYTHON) -m black tag_manager_cli/

lint:  ## Run flake8 linting
	$(PYTHON) -m flake8 tag_manager_cli/

typecheck:  ## Run mypy type checking
	$(PYTHON) -m mypy tag_manager_cli/

test:  ## Run pytest
	$(PYTHON) -m pytest

test-cov:  ## Run pytest with coverage
	$(PYTHON) -m pytest --cov=tag_manager_cli --cov-report=html --cov-report=term

quality: format lint typecheck test  ## Run all quality checks

run:  ## Run the CLI in interactive mode
	$(PYTHON) -m tag_manager_cli.main

clean:  ## Clean up generated files
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache/ .mypy_cache/ htmlcov/ 2>/dev/null || true

clean-all: clean  ## Clean everything including virtual environment
	rm -rf $(VENV_PATH)

# Development shortcuts
dev-setup: install  ## Complete development setup
	@echo "Development environment setup complete!"
	@echo "Run 'make run' to start the CLI or 'make quality' to run all checks"

dev-check: quality  ## Quick development check (all quality tools)

# Web dashboard
WEB_PORT ?= 8095

web-restart:  ## Rebuild frontend and restart web server
	cd frontend && npm run build
	-$(PYTHON) -m tag_manager_cli.main web stop
	TAG_MANAGER_WEB_AUTH_DISABLED=true $(PYTHON) -m tag_manager_cli.main web start --port $(WEB_PORT) --daemon

# AWS specific commands (require virtual environment and AWS setup)
aws-check:  ## Check AWS configuration
	@echo "Checking AWS configuration..."
	@if [ -z "$$AWS_PROFILE" ]; then \
		echo "Warning: AWS_PROFILE not set"; \
	else \
		echo "AWS_PROFILE: $$AWS_PROFILE"; \
	fi
	$(PYTHON) -c "import boto3; print('Boto3 version:', boto3.__version__)"

# Example commands
example-cost:  ## Run example cost analysis command
	$(PYTHON) -m tag_manager_cli.main cost report --tag-key Environment --start 2024-01-01 --end 2024-01-31

example-version:  ## Show version
	$(PYTHON) -m tag_manager_cli.main version

# Docker and deployment commands
docker-up:  ## Start Docker services
	docker compose up -d

docker-down:  ## Stop Docker services  
	docker compose down

docker-logs:  ## View Docker logs
	docker compose logs -f

docker-status:  ## Show Docker service status
	docker compose ps

verify:  ## Verify deployment health
	@if [ -f "scripts/verify-deployment.sh" ]; then \
		chmod +x scripts/verify-deployment.sh && ./scripts/verify-deployment.sh; \
	else \
		echo "Verification script not found at scripts/verify-deployment.sh"; \
	fi

install-full:  ## Complete installation with Docker
	./install.sh