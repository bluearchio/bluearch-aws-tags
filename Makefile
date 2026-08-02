PYTHON ?= python
VENV ?= .venv
PY := $(if $(wildcard $(VENV)/bin/python),$(VENV)/bin/python,$(PYTHON))
PIP := $(VENV)/bin/pip

.PHONY: setup backend-dev frontend-dev test clean

setup:
	$(PYTHON) -m venv $(VENV)
	$(PIP) install -U pip
	$(PIP) install -r requirements.txt -e . pytest httpx2
	cd frontend && npm ci

backend-dev:
	BLUEARCH_CORE_MANAGED_WEB_START=1 PYTHONPATH=. $(PY) -m tag_manager_cli.main web start --host 127.0.0.1 --port 8096

frontend-dev:
	cd frontend && npm run dev

test:
	$(PY) -m pytest tag_manager_cli/tests tests
	$(PY) -m compileall tag_manager_cli
	cd frontend && npm run build

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf .pytest_cache build dist *.egg-info frontend/node_modules frontend/dist frontend/.vite frontend/tsconfig.tsbuildinfo
