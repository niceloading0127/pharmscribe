#!/usr/bin/env bash
# Whisper fallback: transcribe a video/audio file to transcript.srt (timestamped).
# Use ONLY when a video has no captions. Slow on long videos.
# Usage: transcribe.sh <video_or_audio> [out_dir=./video_work] [model=small] [lang=auto]
set -euo pipefail
SRC="${1:?Usage: transcribe.sh <video_or_audio> [out_dir] [model] [lang]}"
OUTDIR="${2:-./video_work}"
MODEL="${3:-small}"
LANG="${4:-auto}"

command -v whisper >/dev/null || { echo "ERROR: whisper not found. Install with 'pip install openai-whisper'."; exit 1; }
command -v ffmpeg  >/dev/null || { echo "ERROR: ffmpeg not found."; exit 1; }
[ -f "$SRC" ] || { echo "ERROR: file not found: $SRC"; exit 1; }
mkdir -p "$OUTDIR"

echo "Extracting 16kHz mono audio ..."
ffmpeg -hide_banner -loglevel error -y -i "$SRC" -ar 16000 -ac 1 "$OUTDIR/audio.wav"

ARGS=(--model "$MODEL" --output_format srt --output_dir "$OUTDIR" --verbose False)
[ "$LANG" != "auto" ] && ARGS+=(--language "$LANG")
echo "Transcribing with Whisper (model=$MODEL) — this can be slow on long videos ..."
whisper "$OUTDIR/audio.wav" "${ARGS[@]}"
[ -f "$OUTDIR/audio.srt" ] && cp "$OUTDIR/audio.srt" "$OUTDIR/transcript.srt"
echo "Transcript saved to $OUTDIR/transcript.srt"
