# Contributing

Thanks for helping improve `bluearch-aws-tags`.

## Local Setup

```bash
python -m venv .venv
. .venv/bin/activate
pip install -U pip
pip install -r requirements.txt -e . pytest httpx2

cd frontend
npm ci
```

## Run Locally

Start core first:

```bash
bluearch-core start --daemon
```

Run the backend/dashboard:

```bash
tag-manager web start --host 127.0.0.1 --port 8096
```

Run the frontend:

```bash
cd frontend
npm run dev
```

## Test

```bash
python -m pytest tag_manager_cli/tests tests
python -m compileall tag_manager_cli
cd frontend && npm run build
```

Or use:

```bash
make setup
make test
```

## Pull Requests

- Keep changes small and focused.
- Include tests or explain why a test is not practical.
- Update the README when commands, configuration, APIs, frontend behavior, or AWS permissions change.
- Update IAM policy files when adding new AWS API calls.
- Do not commit secrets, AWS account IDs, local databases, generated reports, screenshots with account data, or local `.env` files.
- Do not add hosted telemetry, hosted sign-in, private release URLs, license gates, internal AWS account IDs, Slack ops hooks, or private deployment automation.

## Security-Sensitive Changes

Changes to AWS credential handling, tagging writes, lifecycle workflows, service-token handling, local persistence, or generated reports need extra review. Describe the security impact in the PR.
