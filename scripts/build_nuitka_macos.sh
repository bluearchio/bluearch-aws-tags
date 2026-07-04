#!/usr/bin/env bash

set -euo pipefail

BINARY_NAME="${BINARY_NAME:-tag-manager}"
PACKAGE_NAME="${PACKAGE_NAME:-tag_manager_cli}"
ENTRY_IMPORT="${ENTRY_IMPORT:-tag_manager_cli.main}"
APP_OBJECT="${APP_OBJECT:-cli}"
if [ -z "${ONEFILE_TEMPDIR:-}" ]; then
  ONEFILE_TEMPDIR="{HOME}/.tag-manager/bin"
fi

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENTRY_FILE="${BINARY_NAME//-/_}_nuitka_entry.py"

cd "$PROJECT_ROOT"

echo "========================================="
echo "$BINARY_NAME macOS production build"
echo "Package: $PACKAGE_NAME"
echo "Nuitka + LTO"
echo "========================================="

echo "Cleaning previous build artifacts..."
rm -rf dist build "$ENTRY_FILE" *.build *.dist *.onefile-build
mkdir -p dist

if [ -d "frontend" ] && [ -f "frontend/package.json" ]; then
  echo "Building frontend..."
  (
    cd frontend
    npm ci --prefer-offline 2>/dev/null || npm install
    npm run build
  )
fi

echo "Creating temporary CLI entry point..."
cat > "$ENTRY_FILE" <<PY
from ${ENTRY_IMPORT} import ${APP_OBJECT}

if __name__ == "__main__":
    ${APP_OBJECT}()
PY

cleanup() {
  rm -f "$ENTRY_FILE"
}
trap cleanup EXIT

EXTRA_DATA_FLAGS=()
for rel_path in templates integrations web/static; do
  if [ -d "$PACKAGE_NAME/$rel_path" ]; then
    EXTRA_DATA_FLAGS+=("--include-data-dir=$PACKAGE_NAME/$rel_path=$PACKAGE_NAME/$rel_path")
    echo "[OK] Including $PACKAGE_NAME/$rel_path"
  fi
done

python -m nuitka --version

python -m nuitka \
  --standalone \
  --onefile \
  --output-filename="$BINARY_NAME" \
  --output-dir=dist \
  --onefile-tempdir-spec="$ONEFILE_TEMPDIR" \
  --onefile-no-compression \
  --include-package="$PACKAGE_NAME" \
  --include-package-data="$PACKAGE_NAME" \
  --include-package=shellingham \
  --include-package-data=limits \
  --include-package-data=rich \
  --include-package-data=pydantic \
  --include-package-data=pydantic_core \
  "${EXTRA_DATA_FLAGS[@]}" \
  --follow-imports \
  --lto=yes \
  --assume-yes-for-downloads \
  --show-progress \
  "$ENTRY_FILE"

if [ ! -x "dist/$BINARY_NAME" ]; then
  echo "ERROR: expected binary not found at dist/$BINARY_NAME" >&2
  exit 1
fi

chmod 755 "dist/$BINARY_NAME"
"dist/$BINARY_NAME" --version
echo "[OK] Built dist/$BINARY_NAME"
