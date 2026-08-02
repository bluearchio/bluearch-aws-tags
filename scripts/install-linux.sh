#!/usr/bin/env bash
set -euo pipefail

APP_NAME="BlueArch AWS Tags"
REPO="bluearchio/bluearch-aws-tags"
BINARY_NAME="bluearch-aws-tags"
ASSET_NAME="bluearch-aws-tags-linux-x86_64.tar.gz"
VERSION="${BLUEARCH_VERSION:-latest}"
INSTALL_DIR="${INSTALL_DIR:-$HOME/.local/bin}"

CORE_APP_NAME="BlueArch AWS Core"
CORE_REPO="bluearchio/bluearch-aws-core"
CORE_BINARY_NAME="bluearch-aws-core"
CORE_ASSET_NAME="bluearch-aws-core-linux-x86_64.tar.gz"
CORE_VERSION="${BLUEARCH_CORE_VERSION:-latest}"
CORE_INSTALL_POLICY="${BLUEARCH_INSTALL_CORE:-missing}"
DEFAULT_MINIMUM_CORE_VERSION="0.2.6"
MINIMUM_CORE_VERSION="${BLUEARCH_MINIMUM_CORE_VERSION:-$DEFAULT_MINIMUM_CORE_VERSION}"

log() {
  printf '[bluearch] %s\n' "$*"
}

fail() {
  printf '[bluearch] error: %s\n' "$*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "Missing required command: $1"
}

release_base_url() {
  local repo="$1"
  local version="$2"
  local project="${repo##*/}"
  local dist_base="${BLUEARCH_DIST_BASE_URL:-https://dist.bluearch.io}"
  printf '%s/releases/%s/%s' "${dist_base%/}" "$project" "$version"
}

download_file() {
  local url="$1"
  local output="$2"
  local token="${GITHUB_TOKEN:-${GH_TOKEN:-}}"
  if [[ -n "$token" && "$url" == https://github.com/* ]]; then
    curl -fsSL -H "Authorization: Bearer ${token}" "$url" -o "$output"
  else
    curl -fsSL "$url" -o "$output"
  fi
}

verify_checksum() {
  local checksums_file="$1"
  local asset_name="$2"
  local selected_file="$3"

  if ! awk -v asset="$asset_name" '
    {
      name = $2
      sub(/^\*/, "", name)
      if (name == asset) {
        print
        matches += 1
      }
    }
    END { exit(matches == 1 ? 0 : 1) }
  ' "$checksums_file" > "$selected_file"; then
    fail "SHA256SUMS must contain exactly one row for ${asset_name}"
  fi

  (cd "$(dirname "$checksums_file")" && sha256sum -c "$(basename "$selected_file")") || \
    fail "Checksum verification failed for ${asset_name}"
}

install_release() (
  local app_name="$1"
  local repo="$2"
  local version="$3"
  local asset_name="$4"
  local binary_name="$5"
  local base_url
  local tmp_dir

  base_url="$(release_base_url "$repo" "$version")"
  tmp_dir="$(mktemp -d)"
  trap 'rm -rf "$tmp_dir"' EXIT

  log "Downloading ${app_name} (${version})..."
  download_file "${base_url}/${asset_name}" "${tmp_dir}/${asset_name}"

  download_file "${base_url}/SHA256SUMS" "${tmp_dir}/SHA256SUMS" || \
    fail "Could not download required SHA256SUMS"
  verify_checksum "${tmp_dir}/SHA256SUMS" "$asset_name" "${tmp_dir}/SHA256SUMS.selected"

  local archive_listing
  archive_listing="$(tar -tzf "${tmp_dir}/${asset_name}")" || fail "Malformed archive: ${asset_name}"
  local exact_binary_count=0
  local entry
  while IFS= read -r entry; do
    [[ -n "$entry" ]] || continue
    case "$entry" in
      /*|../*|*/../*|*/..|*\\*) fail "Unsafe archive path: ${entry}" ;;
    esac
    if [[ "$entry" == "$binary_name" ]]; then
      exact_binary_count=$((exact_binary_count + 1))
    fi
  done <<< "$archive_listing"
  [[ "$exact_binary_count" -eq 1 ]] || \
    fail "Archive must contain exactly one top-level ${binary_name} executable"

  local entry_types
  entry_types="$(tar -tvzf "${tmp_dir}/${asset_name}" | awk -v asset="$binary_name" '$NF == asset { print substr($1, 1, 1) }')"
  [[ "$entry_types" == "-" ]] || fail "Archive entry ${binary_name} must be a regular file"

  mkdir -p "${tmp_dir}/extract"
  tar --no-same-owner --no-same-permissions -xzf "${tmp_dir}/${asset_name}" -C "${tmp_dir}/extract"

  local extracted_binary="${tmp_dir}/extract/${binary_name}"
  [[ -f "$extracted_binary" && ! -L "$extracted_binary" ]] || fail "Archive did not contain a safe ${binary_name}"

  if [[ "$binary_name" == "$CORE_BINARY_NAME" ]]; then
    public_core_version_satisfies "$extracted_binary" || \
      fail "Verified Core release must be ${CORE_BINARY_NAME} >= ${MINIMUM_CORE_VERSION}"
  fi

  mkdir -p "$INSTALL_DIR"
  install -m 0755 "$extracted_binary" "${INSTALL_DIR}/${binary_name}"
  log "Installed ${binary_name} to ${INSTALL_DIR}/${binary_name}"
)

canonical_public_core_target() {
  local candidate="$1"
  local target
  [[ -n "$candidate" ]] || return 1
  target="$(readlink -f -- "$candidate" 2>/dev/null)" || return 1
  [[ -f "$target" && -x "$target" ]] || return 1
  [[ "$(basename -- "$target")" == "$CORE_BINARY_NAME" ]] || return 1
  printf '%s\n' "$target"
}

version_at_least() {
  local actual="$1"
  local required="$2"
  local actual_major actual_minor actual_patch
  local required_major required_minor required_patch
  IFS=. read -r actual_major actual_minor actual_patch <<< "$actual"
  IFS=. read -r required_major required_minor required_patch <<< "$required"
  [[ "$actual_major" =~ ^[0-9]+$ && "$actual_minor" =~ ^[0-9]+$ && "$actual_patch" =~ ^[0-9]+$ ]] || return 1
  [[ "$required_major" =~ ^[0-9]+$ && "$required_minor" =~ ^[0-9]+$ && "$required_patch" =~ ^[0-9]+$ ]] || return 1
  (( 10#$actual_major > 10#$required_major )) ||
    (( 10#$actual_major == 10#$required_major && 10#$actual_minor > 10#$required_minor )) ||
    (( 10#$actual_major == 10#$required_major && 10#$actual_minor == 10#$required_minor && 10#$actual_patch >= 10#$required_patch ))
}

public_core_version_satisfies() {
  local candidate="$1"
  local target output version_line version identity_pattern
  target="$(canonical_public_core_target "$candidate")" || return 1
  # Only the already-resolved, exact public target is executed. A legacy target
  # is rejected by basename before this point.
  output="$("$target" --version 2>/dev/null)" || return 1
  version_line="${output%%$'\n'*}"
  [[ "$output" != *$'\n'* ]] || return 1
  identity_pattern="^${CORE_BINARY_NAME} ([0-9]+\.[0-9]+\.[0-9]+)$"
  [[ "$version_line" =~ $identity_pattern ]] || return 1
  version="${BASH_REMATCH[1]}"
  version_at_least "$version" "$MINIMUM_CORE_VERSION"
}

existing_public_core_satisfies() {
  local candidate=""
  candidate="$(command -v "$CORE_BINARY_NAME" 2>/dev/null || true)"
  if [[ -n "$candidate" ]] && public_core_version_satisfies "$candidate"; then
    return 0
  fi
  if [[ -x "${INSTALL_DIR}/${CORE_BINARY_NAME}" ]] && \
    public_core_version_satisfies "${INSTALL_DIR}/${CORE_BINARY_NAME}"; then
    return 0
  fi
  return 1
}

case "$(uname -s)" in
  Linux) ;;
  *) fail "This installer supports Linux only. On macOS run: brew trust --formula bluearchio/tap/bluearch-aws-core; brew trust --formula bluearchio/tap/bluearch-aws-tags; brew install bluearchio/tap/bluearch-aws-tags" ;;
esac

case "$(uname -m)" in
  x86_64|amd64) ;;
  *) fail "Unsupported architecture: $(uname -m). Current release assets support linux-x86_64." ;;
esac

require_command curl
require_command tar
require_command sha256sum
require_command install
require_command readlink

version_at_least "$MINIMUM_CORE_VERSION" "$DEFAULT_MINIMUM_CORE_VERSION" || \
  fail "BLUEARCH_MINIMUM_CORE_VERSION cannot be lower than ${DEFAULT_MINIMUM_CORE_VERSION}"

case "$CORE_INSTALL_POLICY" in
  always)
    install_release "$CORE_APP_NAME" "$CORE_REPO" "$CORE_VERSION" "$CORE_ASSET_NAME" "$CORE_BINARY_NAME"
    ;;
  missing)
    if existing_public_core_satisfies; then
      log "Using existing ${CORE_BINARY_NAME} >= ${MINIMUM_CORE_VERSION}"
    else
      log "Existing Core is missing, non-canonical, or older than ${MINIMUM_CORE_VERSION}; installing a verified Core release"
      install_release "$CORE_APP_NAME" "$CORE_REPO" "$CORE_VERSION" "$CORE_ASSET_NAME" "$CORE_BINARY_NAME"
    fi
    ;;
  *) fail "Invalid BLUEARCH_INSTALL_CORE value: ${CORE_INSTALL_POLICY}. Use missing or always." ;;
esac

install_release "$APP_NAME" "$REPO" "$VERSION" "$ASSET_NAME" "$BINARY_NAME"

if ! command -v "$BINARY_NAME" >/dev/null 2>&1; then
  case ":$PATH:" in
    *":$INSTALL_DIR:"*) ;;
    *) printf '[bluearch] warning: %s\n' "${INSTALL_DIR} is not on PATH. Add it with: export PATH=\"${INSTALL_DIR}:\$PATH\"" >&2 ;;
  esac
fi

log "Start core with: ${CORE_BINARY_NAME} start --daemon"
log "Run the CLI with: ${BINARY_NAME} --help"
