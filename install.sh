#!/usr/bin/env bash
set -euo pipefail

REPO="bluearchio/bluearch-aws-tags"
APP_NAME="BlueArch AWS Tags"
VERSION="${BLUEARCH_VERSION:-latest}"
DIST_BASE_URL="${BLUEARCH_DIST_BASE_URL:-}"
INSTALLER_NAME="install-linux.sh"

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

macos_install() {
  local brew
  brew="$(command -v brew 2>/dev/null || true)"
  [[ -n "$brew" ]] || fail "Homebrew is required. Then run: brew trust --formula bluearchio/tap/bluearch-aws-core; brew trust --formula bluearchio/tap/bluearch-aws-tags; brew install bluearchio/tap/bluearch-aws-tags"

  "$brew" tap bluearchio/tap
  "$brew" trust --formula bluearchio/tap/bluearch-aws-core || \
    fail "Core formula trust failed. Run: brew trust --formula bluearchio/tap/bluearch-aws-core"
  "$brew" trust --formula bluearchio/tap/bluearch-aws-tags || \
    fail "Tags formula trust failed. Run: brew trust --formula bluearchio/tap/bluearch-aws-tags"
  "$brew" install bluearchio/tap/bluearch-aws-tags || \
    fail "Install failed. Trust both exact formulae first: brew trust --formula bluearchio/tap/bluearch-aws-core; brew trust --formula bluearchio/tap/bluearch-aws-tags"
  log "Installed ${APP_NAME}. Start with: bluearch-aws-core start --daemon"
  log "Then run: bluearch-aws-tags --help"
}

verify_installer() {
  local checksums_file="$1"
  local installer_file="$2"
  local selected_file="$3"
  if ! awk -v asset="$INSTALLER_NAME" '
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
    fail "SHA256SUMS must contain exactly one row for ${INSTALLER_NAME}"
  fi
  (cd "$(dirname "$installer_file")" && sha256sum -c "$(basename "$selected_file")") || \
    fail "Checksum verification failed for ${INSTALLER_NAME}"
}

canonical_release_version() {
  local version="$1"
  case "$version" in
    latest) printf '%s' "$version" ;;
    v[0-9]*.[0-9]*.[0-9]*)
      [[ "$version" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || \
        fail "Release version must be latest, X.Y.Z, or vX.Y.Z: ${version}"
      printf '%s' "$version"
      ;;
    [0-9]*.[0-9]*.[0-9]*)
      [[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || \
        fail "Release version must be latest, X.Y.Z, or vX.Y.Z: ${version}"
      printf 'v%s' "$version"
      ;;
    *) fail "Release version must be latest, X.Y.Z, or vX.Y.Z: ${version}" ;;
  esac
}

linux_install() {
  local script_dir local_installer tmp_dir release_url resolved_version
  script_dir="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
  local_installer="${script_dir}/scripts/${INSTALLER_NAME}"
  export BLUEARCH_DIST_BASE_URL="$DIST_BASE_URL"
  export BLUEARCH_VERSION="$VERSION"
  export BLUEARCH_CORE_VERSION="latest"
  export BLUEARCH_INSTALL_CORE="missing"
  if [[ -f "$local_installer" ]]; then
    exec bash "$local_installer"
  fi

  require_command curl
  require_command sha256sum
  require_command awk
  tmp_dir="$(mktemp -d)"
  trap 'rm -rf "$tmp_dir"' EXIT
  resolved_version="$(canonical_release_version "$VERSION")" || return 1
  if [[ -n "$DIST_BASE_URL" ]]; then
    release_url="${DIST_BASE_URL%/}/releases/${REPO##*/}/${resolved_version}"
  elif [[ "$resolved_version" == "latest" ]]; then
    release_url="https://github.com/${REPO}/releases/latest/download"
  else
    release_url="https://github.com/${REPO}/releases/download/${resolved_version}"
  fi
  log "Downloading verified ${APP_NAME} release installer (${VERSION})..."
  curl -fsSL "${release_url}/${INSTALLER_NAME}" -o "${tmp_dir}/${INSTALLER_NAME}"
  curl -fsSL "${release_url}/SHA256SUMS" -o "${tmp_dir}/SHA256SUMS"
  verify_installer "${tmp_dir}/SHA256SUMS" "${tmp_dir}/${INSTALLER_NAME}" "${tmp_dir}/SHA256SUMS.selected"
  exec bash "${tmp_dir}/${INSTALLER_NAME}"
}

usage() {
  cat <<'EOF'
Usage: ./install.sh [install|update|--help]

Installs or updates the public bluearch-aws-tags binary and its
bluearch-aws-core dependency. Deprecated closed-source installations are not
read, executed, replaced, or removed.
EOF
}

case "${1:-install}" in
  install|update)
    case "$(uname -s)" in
      Darwin) macos_install ;;
      Linux) linux_install ;;
      *) fail "Unsupported operating system. On macOS, trust the exact formulae with: brew trust --formula bluearchio/tap/bluearch-aws-core; brew trust --formula bluearchio/tap/bluearch-aws-tags" ;;
    esac
    ;;
  -h|--help|help) usage ;;
  *) usage >&2; exit 2 ;;
esac
