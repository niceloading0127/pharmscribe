#!/usr/bin/env bash
# Fetch captions (and optionally a low-res video) from a YouTube URL with yt-dlp.
# Usage: fetch.sh <url> [out_dir=./video_work] [mode=subs] [sub_langs=en.*,en]
#   mode: subs (captions only) | video (low-res video only) | both
set -euo pipefail

URL="${1:?Usage: fetch.sh <url> [out_dir] [mode=subs] [sub_langs]}"
OUTDIR="${2:-./video_work}"
MODE="${3:-subs}"
SUBLANGS="${4:-en.*,en}"

command -v yt-dlp >/dev/null || { echo "ERROR: yt-dlp not found. Install with 'pip install yt-dlp'."; exit 1; }
mkdir -p "$OUTDIR"

if [ "$MODE" = "subs" ] || [ "$MODE" = "both" ]; then
  echo "Fetching captions ($SUBLANGS) ..."
  yt-dlp --skip-download --write-subs --write-auto-subs \
    --sub-langs "$SUBLANGS" --sub-format vtt --convert-subs srt \
    -o "$OUTDIR/sub.%(ext)s" "$URL" || true
  SRT=$(ls "$OUTDIR"/sub*.srt 2>/dev/null | head -1 || true)
  if [ -n "${SRT:-}" ]; then
    cp "$SRT" "$OUTDIR/transcript.srt"
    echo "Captions saved to $OUTDIR/transcript.srt"
  else
    echo "WARN: no captions found for this video. Use mode=video + transcribe.sh (Whisper) instead."
  fi
fi

if [ "$MODE" = "video" ] || [ "$MODE" = "both" ]; then
  echo "Downloading low-res video for frame sampling ..."
  yt-dlp -f "best[height<=480][ext=mp4]/best[height<=480]/best" \
    -o "$OUTDIR/video.%(ext)s" "$URL"
  # normalize to video.mp4 if needed
  VID=$(ls "$OUTDIR"/video.* 2>/dev/null | grep -v '\.srt$' | head -1 || true)
  [ -n "${VID:-}" ] && [ "$VID" != "$OUTDIR/video.mp4" ] && mv "$VID" "$OUTDIR/video.mp4" || true
  echo "Video saved to $OUTDIR/video.mp4"
fi
