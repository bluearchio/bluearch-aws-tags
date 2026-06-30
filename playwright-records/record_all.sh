#!/bin/bash
# Master script: seed data, start server, record all demos, convert, copy to website.
# Usage: ./record_all.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
OUTPUT_DIR="$PROJECT_DIR/../bluearch-website/frontend/app/public/demos/web"
PORT="${DEMO_PORT:-8095}"

cd "$PROJECT_DIR"

# Activate venv if available
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
fi

echo "=== Step 1: Seed mock data ==="
python "$SCRIPT_DIR/seed_mock_data.py"

echo ""
echo "=== Step 2: Start web server (auth disabled) ==="
TAG_MANAGER_WEB_AUTH_DISABLED=true python -m tag_manager_cli.main web start --port "$PORT" --daemon
sleep 3

echo ""
echo "=== Step 3: Record demos ==="
mkdir -p "$SCRIPT_DIR/videos"

DEMOS=(
    "record_lifecycle_tag"
    "record_lifecycle_misconfig"
    "record_ai_chat"
    "record_cost"
)

for demo in "${DEMOS[@]}"; do
    echo "Recording: $demo"
    DEMO_URL="http://localhost:$PORT" python "$SCRIPT_DIR/${demo}.py" || echo "  Warning: $demo failed"
    echo ""
done

echo "=== Step 4: Rename videos ==="
# Playwright saves videos with random names -- rename based on recording order
VIDEO_FILES=($(ls -t "$SCRIPT_DIR/videos/"*.webm 2>/dev/null))
NAMES=("cost" "ai-chat" "lifecycle-misconfig" "lifecycle-tag")

for i in "${!NAMES[@]}"; do
    if [ -f "${VIDEO_FILES[$i]}" ]; then
        mv "${VIDEO_FILES[$i]}" "$SCRIPT_DIR/videos/${NAMES[$i]}.webm"
        echo "  Renamed: ${VIDEO_FILES[$i]} -> ${NAMES[$i]}.webm"
    fi
done

echo ""
echo "=== Step 5: Convert WebM -> MP4 ==="
bash "$SCRIPT_DIR/convert.sh" "$SCRIPT_DIR/videos" "$OUTPUT_DIR"

echo ""
echo "=== Step 6: Stop web server ==="
python -m tag_manager_cli.main web stop || true

echo ""
echo "=== Done ==="
echo "MP4 files in: $OUTPUT_DIR"
ls -lh "$OUTPUT_DIR"/*.mp4 2>/dev/null
