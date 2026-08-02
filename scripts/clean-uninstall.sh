#!/usr/bin/env bash
set -euo pipefail

PUBLIC_BINARY="bluearch-aws-tags"
PUBLIC_FORMULA="bluearchio/tap/bluearch-aws-tags"

log() {
  printf '[bluearch] %s\n' "$*"
}

if [[ "${BLUEARCH_UNINSTALL_CONFIRM:-}" != "yes" ]]; then
  printf 'Remove only the public %s installation? [y/N] ' "$PUBLIC_BINARY"
  read -r answer
  [[ "$answer" =~ ^[Yy]$ ]] || { log "Uninstall cancelled"; exit 0; }
fi

log "Removing only public BlueArch AWS Tags installation surfaces"

if command -v brew >/dev/null 2>&1; then
  brew_path="$(command -v brew)"
  "$brew_path" trust --formula "$PUBLIC_FORMULA"
  if "$brew_path" list --formula "$PUBLIC_FORMULA" >/dev/null 2>&1; then
    "$brew_path" uninstall "$PUBLIC_FORMULA"
  fi
fi

# Curl/manual installations use public-specific filenames. These exact paths
# cannot overlap the deprecated closed-source executable.
rm -f -- "$HOME/.local/bin/$PUBLIC_BINARY"
rm -f -- "$HOME/bin/$PUBLIC_BINARY"

if command -v python3 >/dev/null 2>&1; then
  python3 -m pip uninstall --yes bluearch-aws-tags >/dev/null 2>&1 || true
fi

if command -v "$PUBLIC_BINARY" >/dev/null 2>&1; then
  log "warning: another $PUBLIC_BINARY installation remains at $(command -v "$PUBLIC_BINARY")"
else
  log "Public $PUBLIC_BINARY installation removed"
fi

log "Preserved deprecated closed-source tag-manager binary and all legacy data/configuration directories"
log "Preserved bluearch-aws-core because it may be shared by other public products"
