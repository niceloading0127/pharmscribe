#!/usr/bin/env python3
"""PharmScribe knowledge base — a local, queryable store of pharmacology
knowledge extracted from videos, with multi-dimensional cross retrieval and
exact source traceability (video + timestamp, with a jump-back YouTube link).

Subcommands:
  init   <db>
  add    <db> <entries.json>         ingest one video's structured entries
  query  <db> [--drug D] [--target T] [--pathway P] [--topic K]
             [--category C] [--text "free text"] [--json]
  videos <db>                         list processed videos
  stats  <db>                         counts by category / top tags

entries.json schema (also consumed by make_docx.py):
{
  "video": {"video_id": "...", "title": "...", "url": "...",
            "duration": "hh:mm:ss", "course": "..."},
  "entries": [
    {"ts_seconds": 1230, "ts_hhmmss": "00:20:30", "category": "mechanism",
     "term_en": "CYP3A4 inhibition", "term_zh": "CYP3A4 抑制",
     "explanation_zh": "中文解释 ...",
     "drugs": ["ketoconazole"], "targets": ["CYP3A4"],
     "pathways": ["hepatic metabolism"], "topics": ["drug interaction", "PK"]}
  ]
}

Categories (suggested): mechanism, PK, PD, ADR, interaction, SAR,
indication, contraindication, concept.
"""
import argparse
import json
import os
import sqlite3
import sys

SCHEMA = """
CREATE TABLE IF NOT EXISTS videos (
  video_id TEXT PRIMARY KEY, title TEXT, url TEXT,
  duration TEXT, course TEXT, processed_at TEXT
);
CREATE TABLE IF NOT EXISTS entries (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  video_id TEXT, ts_seconds INTEGER, ts_hhmmss TEXT,
  category TEXT, term_en TEXT, term_zh TEXT, explanation_zh TEXT,
  FOREIGN KEY(video_id) REFERENCES videos(video_id)
);
CREATE TABLE IF NOT EXISTS tags (
  entry_id INTEGER, tag_type TEXT, tag_value TEXT,
  FOREIGN KEY(entry_id) REFERENCES entries(id)
);
CREATE INDEX IF NOT EXISTS idx_tags ON tags(tag_type, tag_value);
CREATE INDEX IF NOT EXISTS idx_entry_cat ON entries(category);
"""

TAG_DIMENSIONS = ("drugs", "targets", "pathways", "topics")
# map plural json key -> singular tag_type stored in db
TAG_TYPE = {"drugs": "drug", "targets": "target",
            "pathways": "pathway", "topics": "topic"}


def connect(db):
    con = sqlite3.connect(db)
    con.execute("PRAGMA foreign_keys=ON")
    return con


def cmd_init(args):
    con = connect(args.db)
    con.executescript(SCHEMA)
    con.commit()
    print(f"Initialized knowledge base: {args.db}")


def jump_url(url, ts_seconds):
    """Build a YouTube deep link that jumps to the timestamp."""
    if not url or ts_seconds is None:
        return url or ""
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}t={int(ts_seconds)}s"


def cmd_add(args):
    if not os.path.exists(args.db):
        con = connect(args.db)
        con.executescript(SCHEMA)
        con.commit()
    else:
        con = connect(args.db)
        con.executescript(SCHEMA)  # ensure tables exist
    with open(args.entries, encoding="utf-8") as f:
        data = json.load(f)
    v = data.get("video", {})
    vid = v.get("video_id") or v.get("url") or "unknown"
    import datetime
    con.execute(
        "INSERT OR REPLACE INTO videos(video_id,title,url,duration,course,processed_at)"
        " VALUES (?,?,?,?,?,?)",
        (vid, v.get("title", ""), v.get("url", ""), v.get("duration", ""),
         v.get("course", ""), datetime.datetime.now().isoformat(timespec="seconds")))
    # remove any prior entries for this video (so re-runs don't duplicate)
    old = [r[0] for r in con.execute("SELECT id FROM entries WHERE video_id=?", (vid,))]
    if old:
        con.executemany("DELETE FROM tags WHERE entry_id=?", [(i,) for i in old])
        con.execute("DELETE FROM entries WHERE video_id=?", (vid,))
    n_entries = n_tags = 0
    for e in data.get("entries", []):
        cur = con.execute(
            "INSERT INTO entries(video_id,ts_seconds,ts_hhmmss,category,term_en,term_zh,explanation_zh)"
            " VALUES (?,?,?,?,?,?,?)",
            (vid, e.get("ts_seconds"), e.get("ts_hhmmss", ""), e.get("category", "concept"),
             e.get("term_en", ""), e.get("term_zh", ""), e.get("explanation_zh", "")))
        eid = cur.lastrowid
        n_entries += 1
        for dim in TAG_DIMENSIONS:
            for val in e.get(dim, []) or []:
                con.execute("INSERT INTO tags(entry_id,tag_type,tag_value) VALUES (?,?,?)",
                            (eid, TAG_TYPE[dim], str(val).strip().lower()))
                n_tags += 1
    con.commit()
    print(f"Added '{v.get('title', vid)}': {n_entries} entries, {n_tags} tags")


def cmd_query(args):
    con = connect(args.db)
    where, params = [], []
    # each tag dimension becomes an EXISTS constraint -> AND across dimensions
    for dim_flag, ttype in (("drug", "drug"), ("target", "target"),
                            ("pathway", "pathway"), ("topic", "topic")):
        val = getattr(args, dim_flag)
        if val:
            where.append(
                "EXISTS (SELECT 1 FROM tags t WHERE t.entry_id=e.id "
                "AND t.tag_type=? AND t.tag_value LIKE ?)")
            params += [ttype, f"%{val.lower()}%"]
    if args.category:
        where.append("e.category=?")
        params.append(args.category)
    if args.text:
        where.append("(e.term_en LIKE ? OR e.term_zh LIKE ? OR e.explanation_zh LIKE ?)")
        params += [f"%{args.text}%"] * 3
    sql = (
        "SELECT e.term_en,e.term_zh,e.category,e.explanation_zh,e.ts_hhmmss,e.ts_seconds,"
        "v.title,v.url,v.course FROM entries e JOIN videos v ON e.video_id=v.video_id")
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY v.title, e.ts_seconds"
    rows = con.execute(sql, params).fetchall()

    results = []
    for r in rows:
        term_en, term_zh, cat, expl, ts, tss, vtitle, vurl, course = r
        results.append({
            "term_en": term_en, "term_zh": term_zh, "category": cat,
            "explanation_zh": expl, "timestamp": ts,
            "source_video": vtitle, "course": course,
            "jump_url": jump_url(vurl, tss),
        })
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return
    if not results:
        print("（无匹配结果）No matching entries.")
        return
    print(f"找到 {len(results)} 条匹配 / {len(results)} matches\n")
    for x in results:
        head = x["term_en"]
        if x["term_zh"]:
            head += f" / {x['term_zh']}"
        print(f"● [{x['category']}] {head}")
        print(f"  {x['explanation_zh']}")
        print(f"  来源 Source: 《{x['source_video']}》 @ {x['timestamp']}")
        print(f"  跳转 Jump: {x['jump_url']}\n")


def cmd_videos(args):
    con = connect(args.db)
    rows = con.execute(
        "SELECT v.title,v.course,v.duration,COUNT(e.id) FROM videos v "
        "LEFT JOIN entries e ON e.video_id=v.video_id GROUP BY v.video_id "
        "ORDER BY v.processed_at").fetchall()
    if not rows:
        print("知识库为空 / Knowledge base is empty.")
        return
    print(f"已处理 {len(rows)} 个视频 / {len(rows)} videos processed\n")
    for title, course, dur, n in rows:
        c = f"[{course}] " if course else ""
        print(f"  {c}{title} · {dur} · {n} 条知识点")


def cmd_stats(args):
    con = connect(args.db)
    print("按类别 / By category:")
    for cat, n in con.execute(
            "SELECT category,COUNT(*) FROM entries GROUP BY category ORDER BY COUNT(*) DESC"):
        print(f"  {cat}: {n}")
    print("\n高频标签 / Top tags:")
    for ttype, val, n in con.execute(
            "SELECT tag_type,tag_value,COUNT(*) c FROM tags GROUP BY tag_type,tag_value "
            "ORDER BY c DESC LIMIT 15"):
        print(f"  [{ttype}] {val}: {n}")


def main():
    ap = argparse.ArgumentParser(description="PharmScribe knowledge base")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init"); p.add_argument("db"); p.set_defaults(fn=cmd_init)
    p = sub.add_parser("add"); p.add_argument("db"); p.add_argument("entries"); p.set_defaults(fn=cmd_add)
    p = sub.add_parser("query"); p.add_argument("db")
    p.add_argument("--drug"); p.add_argument("--target"); p.add_argument("--pathway")
    p.add_argument("--topic"); p.add_argument("--category"); p.add_argument("--text")
    p.add_argument("--json", action="store_true"); p.set_defaults(fn=cmd_query)
    p = sub.add_parser("videos"); p.add_argument("db"); p.set_defaults(fn=cmd_videos)
    p = sub.add_parser("stats"); p.add_argument("db"); p.set_defaults(fn=cmd_stats)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
