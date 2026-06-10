#!/usr/bin/env python3
"""Split the SRT transcript into time windows and map frames to each window.

Reads <workdir>/audio.srt and <workdir>/meta.json, writes <workdir>/chunks.json.
Each chunk has: index, start, end (seconds + hh:mm:ss), transcript text, and the
list of frame image paths whose timestamps fall inside the window.

Usage: python3 segment.py <workdir> [--window 600]
"""
import argparse
import glob
import json
import os
import re
import sys


def srt_time_to_seconds(ts: str) -> float:
    ts = ts.strip().replace(",", ".")
    h, m, s = ts.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def hhmmss(seconds: float) -> str:
    seconds = int(seconds)
    return f"{seconds // 3600:02d}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"


def parse_srt(path: str):
    """Return list of (start_seconds, text)."""
    with open(path, encoding="utf-8") as f:
        raw = f.read()
    entries = []
    for block in re.split(r"\n\s*\n", raw.strip()):
        lines = [l for l in block.splitlines() if l.strip()]
        ts_line = next((l for l in lines if "-->" in l), None)
        if not ts_line:
            continue
        start = srt_time_to_seconds(ts_line.split("-->")[0])
        text_lines = [l for l in lines if "-->" not in l and not l.strip().isdigit()]
        text = " ".join(text_lines).strip()
        if text:
            entries.append((start, text))
    return entries


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("workdir")
    ap.add_argument("--window", type=int, default=600, help="window size in seconds")
    args = ap.parse_args()

    srt_path = os.path.join(args.workdir, "transcript.srt")
    meta_path = os.path.join(args.workdir, "meta.json")
    if not os.path.exists(srt_path):
        sys.exit(f"ERROR: transcript not found: {srt_path} "
                 f"(run fetch.sh for captions, or transcribe.sh for Whisper)")

    meta = {}
    if os.path.exists(meta_path):
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
    interval = float(meta.get("frame_interval_seconds", 5))
    duration = float(meta.get("duration_seconds", 0))

    entries = parse_srt(srt_path)
    if entries and not duration:
        duration = entries[-1][0] + args.window

    frames = sorted(glob.glob(os.path.join(args.workdir, "frames", "frame_*.jpg")))
    # frame_0001.jpg is the first sample at t≈0, frame_000N at t≈(N-1)*interval
    frame_times = [(i * interval, p) for i, p in enumerate(frames)]

    chunks = []
    n_windows = max(1, int((duration + args.window - 1) // args.window))
    for w in range(n_windows):
        w_start = w * args.window
        w_end = w_start + args.window
        text = " ".join(t for (s, t) in entries if w_start <= s < w_end).strip()
        win_frames = [p for (ft, p) in frame_times if w_start <= ft < w_end]
        if not text and not win_frames:
            continue
        chunks.append({
            "index": len(chunks),
            "start_seconds": w_start,
            "end_seconds": min(w_end, duration) if duration else w_end,
            "start": hhmmss(w_start),
            "end": hhmmss(min(w_end, duration) if duration else w_end),
            "transcript": text,
            "frames": win_frames,
        })

    out_path = os.path.join(args.workdir, "chunks.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "duration_seconds": duration,
            "window_seconds": args.window,
            "num_chunks": len(chunks),
            "chunks": chunks,
        }, f, ensure_ascii=False, indent=2)

    print(f"Wrote {len(chunks)} chunks to {out_path} "
          f"({len(frames)} frames, {len(entries)} transcript lines)")


if __name__ == "__main__":
    main()
