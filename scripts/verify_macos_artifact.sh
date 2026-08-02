#!/usr/bin/env bash
set -euo pipefail

ZIP_PATH="${1:-}"
PUBLIC_BINARY_NAME="${2:-}"
EXPECTED_VERSION="${3:-}"

if [[ -z "$ZIP_PATH" || -z "$PUBLIC_BINARY_NAME" || -z "$EXPECTED_VERSION" ]]; then
  echo "usage: verify_macos_artifact.sh ZIP_PATH PUBLIC_BINARY_NAME EXPECTED_BARE_VERSION" >&2
  exit 2
fi
[[ -f "$ZIP_PATH" ]] || { echo "missing artifact: $ZIP_PATH" >&2; exit 1; }
[[ "$PUBLIC_BINARY_NAME" != */* ]] || { echo "binary name must not contain a path" >&2; exit 1; }
[[ "$EXPECTED_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || {
  echo "expected version must be bare semantic version (for example 0.12.4)" >&2
  exit 1
}

VERIFY_DIR="$(mktemp -d)"
trap 'rm -rf "$VERIFY_DIR"' EXIT

ditto -x -k "$ZIP_PATH" "$VERIFY_DIR"
MATCHES="$(find "$VERIFY_DIR" -type f -name "$PUBLIC_BINARY_NAME" -print)"
MATCH_COUNT="$(printf '%s\n' "$MATCHES" | awk 'NF { count += 1 } END { print count + 0 }')"
[[ "$MATCH_COUNT" -eq 1 ]] || {
  echo "artifact must contain exactly one $PUBLIC_BINARY_NAME" >&2
  exit 1
}
EXPECTED="$VERIFY_DIR/$PUBLIC_BINARY_NAME"
[[ "$MATCHES" == "$EXPECTED" && -x "$EXPECTED" && ! -L "$EXPECTED" ]] || {
  echo "artifact must contain one executable top-level $PUBLIC_BINARY_NAME" >&2
  exit 1
}

codesign --verify --deep --strict --verbose=2 "$EXPECTED"
spctl --assess --type execute --verbose=4 "$EXPECTED"
file "$EXPECTED" | grep -q 'arm64'
VERSION_OUTPUT="$("$EXPECTED" --version)"
[[ "$VERSION_OUTPUT" == "$PUBLIC_BINARY_NAME $EXPECTED_VERSION (production)" ]] || {
  echo "unexpected public version output: $VERSION_OUTPUT" >&2
  exit 1
}
"$EXPECTED" --help >/dev/null
