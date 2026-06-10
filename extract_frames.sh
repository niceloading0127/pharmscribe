#!/usr/bin/env bash
# Sample evenly-spaced keyframes from a local video file (for slides/blackboard).
# Usage: extract_frames.sh <video_file> [out_dir=./video_work] [max_frames=80]
set -euo pipefail
VIDEO="${1:?Usage: extract_frames.sh <video_file> [out_dir] [max_frames]}"
OUTDIR="${2:-./video_work}"
MAX_FRAMES="${3:-80}"

command -v ffmpeg  >/dev/null || { echo "ERROR: ffmpeg not found (brew/apt install ffmpeg)."; exit 1; }
command -v ffprobe >/dev/null || { echo "ERROR: ffprobe not found (ships with ffmpeg)."; exit 1; }
[ -f "$VIDEO" ] || { echo "ERROR: video not found: $VIDEO"; exit 1; }
mkdir -p "$OUTDIR/frames"

DURATION=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$VIDEO" 2>/dev/null | cut -d. -f1)
[ -z "${DURATION:-}" ] && DURATION=1
[ "$DURATION" -lt 1 ] && DURATION=1
INTERVAL=$(( DURATION / MAX_FRAMES )); [ "$INTERVAL" -lt 1 ] && INTERVAL=1

echo "Duration ${DURATION}s -> 1 frame every ${INTERVAL}s (~${MAX_FRAMES} frames)"
ffmpeg -hide_banner -loglevel error -y -i "$VIDEO" -vf "fps=1/${INTERVAL}" "$OUTDIR/frames/frame_%04d.jpg"

cat > "$OUTDIR/meta.json" <<META
{ "video": "$VIDEO", "duration_seconds": $DURATION, "frame_interval_seconds": $INTERVAL }
META
N=$(ls "$OUTDIR/frames" | wc -l | tr -d ' ')
echo "Done: $N frames + meta.json in $OUTDIR"
