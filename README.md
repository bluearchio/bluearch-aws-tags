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

Installing a fully qualified formula automatically adds the tap and trusts only
that formula. Install Core explicitly first so Homebrew records trust for the
separate dependency before resolving Tags. A separate `brew tap` or `brew trust`
command is not needed for a first-time install. See
[Homebrew's tap-trust documentation](https://docs.brew.sh/Tap-Trust).

```bash
brew install bluearchio/tap/bluearch-aws-core
brew install bluearchio/tap/bluearch-aws-tags
bluearch-aws-core start --daemon
bluearch-aws-tags discover all
```

`brew tap bluearchio/tap` only downloads and registers the repository; it does
not grant trust. Whole-tap trust is unnecessary.

### Recovery for an existing tap

If an existing or partially completed installation refuses to load either
formula, trust only Core and Tags, then retry the product installation:

```bash
brew trust --formula bluearchio/tap/bluearch-aws-core
brew trust --formula bluearchio/tap/bluearch-aws-tags
brew install bluearchio/tap/bluearch-aws-tags
```

Linux:

```bash
curl -fsSL https://github.com/bluearchio/bluearch-aws-tags/releases/latest/download/install-linux.sh | bash
export PATH="$HOME/.local/bin:$PATH"
bluearch-aws-core start --daemon
bluearch-aws-tags discover all
```

The Linux installer downloads verified assets directly from GitHub Releases and
installs `bluearch-aws-core` automatically if it is missing. Set
`BLUEARCH_VERSION=vX.Y.Z` (and optionally `BLUEARCH_CORE_VERSION=vX.Y.Z`) to pin
an immutable release. `BLUEARCH_DIST_BASE_URL` is available only as an explicit
mirror override; it is not used by default.

From source:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e .
bluearch-aws-core start --daemon
bluearch-aws-tags discover all
```

## Local Development

Backend:

```bash
. .venv/bin/activate
bluearch-aws-core start --daemon
make backend-dev
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
gh attestation verify bluearch-aws-tags-linux-x86_64.tar.gz --repo bluearchio/bluearch-aws-tags
```

For macOS, verify `bluearch-aws-tags-macos-arm64.zip` with `gh attestation verify`.

Before publishing, the release workflow validates that the dedicated
cross-repository token has the required access to `bluearchio/homebrew-tap`.
Configure that fine-grained token with least privilege: repository access only
to the tap, with Contents and Pull requests write permissions. The tap repository
must have auto-merge enabled, and tap `main` must protect the formula-validation
checks as required status checks. After the
GitHub Release is published, it checks out the tap's `main` branch with
credentials disabled, creates or updates
`release/bluearch-aws-tags-<tag>`, and runs the tap's
`scripts/update_formula.py`. That script generates the immutable GitHub Release
URL from the exact signed macOS asset and its verified SHA-256.

The workflow opens a pull request against the tap's `main` branch and requests
native GitHub auto-merge with `--auto --squash --delete-branch`. GitHub merges
only after the protected required tap checks pass; the product workflow never
bypasses checks or pushes directly to tap `main`. The release workflow remains
pending until the formula pull request is actually `MERGED`; a closed pull
request or a two-hour timeout fails the workflow. If the formula is already
current, no pull request or auto-merge is requested.

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
