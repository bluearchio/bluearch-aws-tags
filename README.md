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
npm ci
npm run dev
```

Shortcut:

```bash
make setup
make backend-dev
make frontend-dev
```

## Tests

```bash
python -m pytest tag_manager_cli/tests
python -m compileall tag_manager_cli
cd frontend && npm run build
```

Shortcut:

```bash
make test
```

## Verifying Release Assets

Tagged releases are published from GitHub Actions after Linux and signed/notarized macOS artifacts are built. Release assets include platform archives, CycloneDX SBOMs, `SHA256SUMS`, and GitHub artifact attestations.

```bash
sha256sum -c SHA256SUMS
# macOS: shasum -a 256 -c SHA256SUMS
gh attestation verify tag-manager-linux-x86_64.tar.gz --repo bluearchio/bluearch-aws-tags
```

For macOS, verify `tag-manager-macos-arm64.zip` with `gh attestation verify`.

Release workflows also open a pull request against `bluearchio/homebrew-tap` to update `bluearch-aws-tags`. Configure `HOMEBREW_TAP_TOKEN_2` before cutting a public tag.

## Security And Privacy Defaults

- The dashboard binds to loopback by default.
- Calls to `bluearch-aws-core` use the local service token.
- AWS credentials stay in the user's local AWS config/credential chain.
- No BlueArch-hosted telemetry, hosted sign-in, license gates, or private release services are included.
- Tag inventories, lifecycle results, reports, logs, and screenshots may contain sensitive account data.
- Report suspected vulnerabilities privately; see `SECURITY.md`.

## Contributing

Keep AWS authentication user-owned through profiles, SSO, and assume-role. Do not add hosted analytics, product sign-in, commercial feature gates, private release URLs, internal account IDs, or private signing/obfuscation flows. Update IAM policy files when adding new AWS API calls.

See `CONTRIBUTING.md` for the full contribution workflow.
