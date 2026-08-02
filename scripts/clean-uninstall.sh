#!/usr/bin/env bash
set -euo pipefail

PUBLIC_BINARY="bluearch-aws-tags"
PUBLIC_FORMULA="bluearchio/tap/bluearch-aws-tags"
CLEANUP_FAILED=0

log() {
  printf '[bluearch] %s\n' "$*"
}

canonical_target() {
  local candidate="$1"
  if command -v realpath >/dev/null 2>&1; then
    realpath "$candidate" 2>/dev/null
  elif [[ ! -L "$candidate" ]]; then
    printf '%s\n' "$candidate"
  else
    return 1
  fi
}

is_homebrew_cellar_target() {
  local target="$1"
  [[ "$target" == */Cellar/bluearch-aws-tags/* ]]
}

remove_manual_public_path() {
  local candidate="$1"
  local target
  [[ -e "$candidate" || -L "$candidate" ]] || return 0
  target="$(canonical_target "$candidate")" || {
    log "warning: could not validate public launcher target; preserved $candidate"
    CLEANUP_FAILED=1
    return 0
  }
  if is_homebrew_cellar_target "$target"; then
    log "warning: Homebrew-managed launcher remains at $candidate; it was not unlinked directly"
    CLEANUP_FAILED=1
    return 0
  fi
  if [[ "$(basename -- "$candidate")" != "$PUBLIC_BINARY" || \
        "$(basename -- "$target")" != "$PUBLIC_BINARY" || \
        ! -f "$target" || ! -x "$target" ]]; then
    log "warning: non-public or invalid launcher preserved at $candidate"
    CLEANUP_FAILED=1
    return 0
  fi
  if rm -f -- "$candidate"; then
    log "Removed manual public launcher: $candidate"
  else
    log "warning: could not remove manual public launcher: $candidate"
    CLEANUP_FAILED=1
  fi
}

if [[ "${BLUEARCH_UNINSTALL_CONFIRM:-}" != "yes" ]]; then
  printf 'Remove only the public %s installation? [y/N] ' "$PUBLIC_BINARY"
  read -r answer
  [[ "$answer" =~ ^[Yy]$ ]] || { log "Uninstall cancelled"; exit 0; }
fi

log "Removing only public BlueArch AWS Tags installation surfaces"

if command -v brew >/dev/null 2>&1; then
  brew_path="$(command -v brew)"
  if "$brew_path" trust --formula "$PUBLIC_FORMULA"; then
    if "$brew_path" list --formula "$PUBLIC_FORMULA" >/dev/null 2>&1; then
      if ! "$brew_path" uninstall "$PUBLIC_FORMULA"; then
        log "warning: Homebrew could not uninstall $PUBLIC_FORMULA; its launcher will be preserved"
        CLEANUP_FAILED=1
      fi
    fi
  else
    log "warning: exact formula trust failed; continuing with manual public-path cleanup"
    CLEANUP_FAILED=1
  fi
fi

# Curl/manual installations use public-specific filenames. Validate canonical
# targets before removing links, and never unlink a Homebrew Cellar target.
remove_manual_public_path "$HOME/.local/bin/$PUBLIC_BINARY"
remove_manual_public_path "$HOME/bin/$PUBLIC_BINARY"
remove_manual_public_path "/opt/homebrew/bin/$PUBLIC_BINARY"
remove_manual_public_path "/usr/local/bin/$PUBLIC_BINARY"

if command -v python3 >/dev/null 2>&1; then
  python3 -m pip uninstall --yes bluearch-aws-tags >/dev/null 2>&1 || true
fi

if command -v "$PUBLIC_BINARY" >/dev/null 2>&1; then
  log "warning: another $PUBLIC_BINARY installation remains at $(command -v "$PUBLIC_BINARY")"
  CLEANUP_FAILED=1
else
  log "Public $PUBLIC_BINARY installation removed"
fi

log "Preserved deprecated closed-source tag-manager binary and all legacy data/configuration directories"
log "Preserved bluearch-aws-core because it may be shared by other public products"

if ((CLEANUP_FAILED != 0)); then
  log "error: public uninstall finished with unresolved items"
  exit 1
fi
