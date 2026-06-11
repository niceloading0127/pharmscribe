#!/usr/bin/env python3
"""pharmscribe — a standalone, vendor-neutral CLI.

Turns a video into bilingual Word study notes + a queryable knowledge base,
using whichever extraction engine you choose (Claude / OpenAI / Gemini / local /
none). No specific AI membership is required: the download, transcription,
knowledge base, and Word generation are plain programs; only the "extract
knowledge" step uses an AI engine, and that engine is swappable.

Examples:
  pharmscribe ingest "https://youtu.be/XXXX" --engine local
  pharmscribe ingest "https://youtu.be/XXXX" --engine openai --domain finance
  pharmscribe query --target CYP3A4
  pharmscribe videos
"""
import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import engine  # noqa: E402
import preprocess  # noqa: E402

DEFAULT_KB = os.path.expanduser("~/pharmscribe-data/kb.db")


def sh(cmd):
    print("· " + " ".join(cmd))
    subprocess.run(cmd, check=True)


def video_meta(url):
    """Get id/title/duration via yt-dlp without downloading."""
    try:
        out = subprocess.check_output(
            ["yt-dlp", "--skip-download", "--print",
             "%(id)s\t%(title)s\t%(duration_string)s", url], text=True).strip().splitlines()[0]
        vid, title, dur = (out.split("\t") + ["", "", ""])[:3]
        return vid, title, dur
    except Exception:
        return "unknown", url, ""


def cmd_ingest(args):
    work = args.workdir or os.path.join(os.path.dirname(args.kb),
                                        "work-" + os.urandom(3).hex())
    os.makedirs(work, exist_ok=True)
    mode = "subs" if args.no_frames else "both"

    sh(["bash", os.path.join(HERE, "fetch.sh"), args.url, work, mode])
    srt = os.path.join(work, "transcript.srt")
    if not os.path.exists(srt):
        sys.exit("没有字幕。No captions found. Re-run with a video that has "
                 "captions, or add Whisper via transcribe.sh.")
    if not args.no_frames and os.path.exists(os.path.join(work, "video.mp4")):
        sh(["bash", os.path.join(HERE, "extract_frames.sh"),
            os.path.join(work, "video.mp4"), work, "80"])
    sh([sys.executable, os.path.join(HERE, "segment.py"), work, "--window", str(args.window)])

    with open(os.path.join(work, "chunks.json"), encoding="utf-8") as f:
        chunks = json.load(f)["chunks"]

    # --- token-saving preprocessing (rule-based, zero tokens) ---
    if args.no_preprocess:
        packed = [c for c in chunks if c.get("transcript", "").strip()]
    else:
        packed = preprocess.pack_chunks(
            chunks, target_words=args.batch_words, min_words=args.min_words)
        print(preprocess.report(chunks, packed))

    vid, title, dur = video_meta(args.url)
    print(f"\n提炼引擎 Engine = {args.engine} · 领域 Domain = {args.domain} · "
          f"{len(packed)} 批待处理\n")
    all_entries = []
    for i, ch in enumerate(packed, 1):
        if not ch.get("transcript", "").strip():
            continue
        print(f"  [{i}/{len(packed)}] {ch['start']} 提炼中 ...")
        ents = engine.extract(args.domain, ch["transcript"],
                              ch["start_seconds"], ch["start"],
                              engine=args.engine, model=args.model)
        for e in ents:
            e.setdefault("ts_seconds", ch["start_seconds"])
            e.setdefault("ts_hhmmss", ch["start"])
        all_entries.extend(ents)

    entries_path = os.path.join(work, "entries.json")
    payload = {"video": {"video_id": vid, "title": title, "url": args.url,
                         "duration": dur, "course": args.course or ""},
               "entries": all_entries}
    with open(entries_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"\n共提炼 {len(all_entries)} 条知识点 -> {entries_path}")

    docx = os.path.join(work, "notes.docx")
    sh([sys.executable, os.path.join(HERE, "make_docx.py"), entries_path, docx])
    sh([sys.executable, os.path.join(HERE, "kb.py"), "init", args.kb])
    sh([sys.executable, os.path.join(HERE, "kb.py"), "add", args.kb, entries_path])
    print(f"\n✅ 完成 Done\n   Word: {docx}\n   知识库 KB: {args.kb}")


def cmd_query(args):
    cmd = [sys.executable, os.path.join(HERE, "kb.py"), "query", args.kb]
    for flag in ("drug", "target", "pathway", "topic", "concept", "model",
                 "metric", "market", "category", "text"):
        val = getattr(args, flag, None)
        if val:
            cmd += [f"--{flag}", val]
    if args.json:
        cmd.append("--json")
    subprocess.run(cmd)


def cmd_passthru(args, sub):
    subprocess.run([sys.executable, os.path.join(HERE, "kb.py"), sub, args.kb])


def main():
    ap = argparse.ArgumentParser(prog="pharmscribe", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--kb", default=DEFAULT_KB, help=f"knowledge base path (default {DEFAULT_KB})")
    sub = ap.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("ingest", help="process a video into notes + KB")
    pi.add_argument("url")
    pi.add_argument("--engine", default=os.environ.get("PHARMSCRIBE_ENGINE", "none"),
                    choices=list(engine.BACKENDS), help="extraction backend")
    pi.add_argument("--model", default=None, help="override model name for the engine")
    pi.add_argument("--domain", default="pharma", choices=list(engine.DOMAIN_PRESETS))
    pi.add_argument("--window", type=int, default=600)
    pi.add_argument("--course", default=None)
    pi.add_argument("--workdir", default=None)
    pi.add_argument("--no-frames", action="store_true", help="captions only, skip video/frames")
    pi.add_argument("--no-preprocess", action="store_true",
                    help="disable token-saving cleaning/skipping/batching")
    pi.add_argument("--batch-words", type=int, default=700,
                    help="merge segments into batches of ~this many words (default 700)")
    pi.add_argument("--min-words", type=int, default=12,
                    help="skip segments shorter than this after cleaning (default 12)")
    pi.set_defaults(fn=cmd_ingest)

    pq = sub.add_parser("query", help="cross-query the knowledge base")
    for flag in ("drug", "target", "pathway", "topic", "concept", "model",
                 "metric", "market", "category", "text"):
        pq.add_argument(f"--{flag}")
    pq.add_argument("--json", action="store_true")
    pq.set_defaults(fn=cmd_query)

    pv = sub.add_parser("videos"); pv.set_defaults(fn=lambda a: cmd_passthru(a, "videos"))
    ps = sub.add_parser("stats"); ps.set_defaults(fn=lambda a: cmd_passthru(a, "stats"))

    args = ap.parse_args()
    os.makedirs(os.path.dirname(args.kb), exist_ok=True)
    args.fn(args)


if __name__ == "__main__":
    main()
