# bluearch-aws-tags

`bluearch-aws-tags` is the AWS tagging, lifecycle, tag policy governance, FinOps, and local dashboard tool. It helps discover resources, manage tags, evaluate compliance, configure lifecycle policies, and analyze cost allocation data.

## What This Repo Is Not

This repo is not a hosted account system, analytics collector, or commercial license service. The public build keeps all product features local and removes private BlueArch services.

## How It Works With The Other Repos

- Requires `bluearch-aws-core` running locally first.
- Uses core for setup, account context, shared storage, templates, and service-token protected backend calls.
- Works alongside `bluearch-aws-ops` for recommendations and alerting.
- Works alongside `bluearch-aws-governance` for governance catalog findings.

## Install

```bash
brew tap bluearchio/tap
brew install bluearchio/tap/bluearch-aws-core
brew install bluearchio/tap/bluearch-aws-tags
bluearch-core start --daemon
tag-manager discover
tag-manager web start
```

From source:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e .
bluearch-core start --daemon
tag-manager discover
```

## Local Development

Backend:

```bash
. .venv/bin/activate
tag-manager web start --host 127.0.0.1 --port 8096
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

## Tests

```bash
python -m pytest tag_manager_cli/tests
python -m compileall tag_manager_cli
cd frontend && npm run build
```

## Contributing

Keep AWS authentication user-owned through profiles, SSO, and assume-role. Do not add hosted analytics, product sign-in, commercial feature gates, private release URLs, internal account IDs, or private signing/obfuscation flows. Update IAM policy files when adding new AWS API calls.
