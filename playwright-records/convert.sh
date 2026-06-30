#!/bin/bash
# Convert Playwright WebM recordings to MP4 for website embedding.
# Usage: ./convert.sh [input_dir] [output_dir]

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INPUT_DIR="${1:-$SCRIPT_DIR/videos}"
OUTPUT_DIR="${2:-$SCRIPT_DIR/../bluearch-website/frontend/app/public/demos/web}"

mkdir -p "$OUTPUT_DIR"

if [ ! -d "$INPUT_DIR" ]; then
    echo "Error: Input directory $INPUT_DIR does not exist"
    exit 1
fi

WEBM_FILES=$(find "$INPUT_DIR" -name "*.webm" -type f 2>/dev/null)

if [ -z "$WEBM_FILES" ]; then
    echo "No WebM files found in $INPUT_DIR"
    exit 0
fi

for webm in $WEBM_FILES; do
    filename=$(basename "$webm" .webm)
    output="$OUTPUT_DIR/${filename}.mp4"
    echo "Converting: $webm -> $output"
    ffmpeg -y -i "$webm" -c:v libx264 -preset slow -crf 23 -pix_fmt yuv420p -an "$output"
    echo "  Done: $(du -h "$output" | cut -f1)"
done

echo ""
echo "All conversions complete. Files in: $OUTPUT_DIR"
ls -lh "$OUTPUT_DIR"/*.mp4 2>/dev/null
