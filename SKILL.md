---
name: pharmscribe
description: >-
  Turn pharmacology and pharmaceutical-science video lectures and course
  playlists into bilingual (English term + Chinese explanation) Word study notes,
  AND build a local, queryable knowledge base with exact source traceability. Use
  whenever the user wants to summarize, take notes on, study, or "read" a
  pharmacology, pharmacokinetics, pharmacodynamics, or medicinal-chemistry video,
  lecture, or course — even tens of hours across many videos, and even if they
  don't say "skill". Also use whenever the user asks to query, search, or
  cross-reference what their video library says about a drug, target, enzyme,
  pathway, or topic (e.g. "everything about CYP3A4", "where was clearance
  explained"). Claude cannot watch raw video, so run the pipeline: pull captions
  with yt-dlp, sample frames for mechanism diagrams, extract pharmacology
  knowledge tagged by drug, target, pathway, and topic, write a Word doc with
  jump-back timestamps and embedded frames, and ingest every entry into the
  knowledge base for cross retrieval.
compatibility: Requires yt-dlp and ffmpeg on PATH, and python-docx (pip3 install python-docx). sqlite3 is in the Python standard library. Whisper (pip install openai-whisper) is only a fallback when a video has no captions.
---

# PharmScribe

A pharmacology-focused study system. It does two things a plain chat cannot:
(1) processes tens of hours of real video locally into deep, bilingual notes, and
(2) accumulates every extracted knowledge point into a **local knowledge base**
that can be cross-queried by drug, target, pathway, or topic — with every answer
traced back to the exact video and timestamp.

Claude reads text and images, not raw video, so always run the pipeline below.

## Two modes

- **Ingest mode** — "summarize / take notes on this video (or course)". Run the
  full pipeline; produce a Word doc AND add the knowledge to the KB.
- **Query mode** — "what does my library say about X", "where was Y explained",
  "compare how Z is taught". Do NOT process new video; query the KB.

Detect query mode when the user asks about their existing library/notes rather
than giving a new video. Then just run `kb.py query` (see Query mode below).

## Conventions

- **Bilingual:** every knowledge point keeps the English term (`term_en`) AND a
  Chinese explanation (`explanation_zh`); add `term_zh` when a standard Chinese
  term exists. This serves graduate pharmacy readers working from English sources.
- **Knowledge base path:** default `~/pharm-notes/kb.db`. Create it once with
  `kb.py init` if absent. All videos across all courses go into the same KB so
  cross-course retrieval works.
- **Per-video folder:** keep each video's working files in their own folder so
  nothing is overwritten, e.g. `~/pharm-notes/<course>/<NN>-<id>/`.

## Ingest workflow (single video)

### 1. Fetch captions + video (frames needed for diagrams)

```bash
bash scripts/fetch.sh "<youtube_url>" ./work both
```

Pharmacology lectures are diagram-heavy (mechanisms, pathways, dose–response,
structures), so default to `both` (captions + low-res video) and sample frames.

### 2. Sample frames

```bash
bash scripts/extract_frames.sh ./work/video.mp4 ./work 80
```

### 3. Transcript

Captions are at `work/transcript.srt`. If none exist, fall back to Whisper:
`bash scripts/transcribe.sh ./work/video.mp4 ./work small auto`.

### 4. Segment plan

```bash
python3 scripts/segment.py ./work --window 600
```

### 5. Extract pharmacology knowledge (pass 1, per segment)

For EACH chunk in `work/chunks.json`, read the transcript AND view the frames in
that window (frames matter: mechanism diagrams, pathway maps, structures, and
slides often carry the real content that captions render as "this binds here").
Extract discrete knowledge points and DROP filler (admin, repetition, asides).
For each point capture, in your working notes, all of:
- `term_en`, `term_zh` (if a standard Chinese term exists)
- `category`: one of mechanism, PK, PD, SAR, indication, contraindication, ADR,
  interaction, concept
- `explanation_zh`: a real 2–4 sentence explanation in Chinese (study-ready)
- `ts_seconds`, `ts_hhmmss`: timestamp for source traceability
- tags: `drugs`, `targets` (receptors/enzymes/proteins), `pathways`, `topics`
- `frame`: path to the most relevant frame for this point, IF a diagram/structure
  on screen materially helps (embedded into the Word doc)

When a frame shows a mechanism/structure, describe what is visible in
`explanation_zh` (Claude can read the image) — do not just transcribe audio.

### 6. Assemble entries.json (pass 2)

Merge and de-duplicate the per-segment points into one `work/entries.json`:

```json
{
  "video": {"video_id":"<id>","title":"<title>","url":"<url>",
            "duration":"hh:mm:ss","course":"<course>"},
  "overview_zh": "几句话:本讲覆盖什么、在课程中的位置。",
  "entries": [ { ...one object per knowledge point, fields from step 5... } ]
}
```

Aim for depth: a 50-minute lecture typically yields 15–40 substantive entries.

### 7. Produce the Word doc

```bash
python3 scripts/make_docx.py ./work/entries.json ./work/notes.docx
```

Bilingual, grouped by category, with clickable "▶ 回看 Re-watch @ mm:ss" links
back to the exact YouTube moment and embedded frames. Tell the user the path.

### 8. Ingest into the knowledge base

```bash
python3 scripts/kb.py init ~/pharm-notes/kb.db      # first time only
python3 scripts/kb.py add ~/pharm-notes/kb.db ./work/entries.json
```

Re-running a video replaces its old entries (no duplicates).

## Playlists (full courses)

List with `bash scripts/playlist.sh "<playlist_url>"`, then run the ingest
workflow per video into its own folder, all feeding the SAME `kb.db`. Confirm
scope before processing dozens of videos; offer a sample first. The KB is what
makes a whole course valuable — every lecture becomes cross-queryable.

## Query mode (the differentiator)

When the user asks about their existing library, translate it to a `kb.py query`.
Dimensions combine with AND:

```bash
# Everything about an enzyme/target, across ALL videos
python3 scripts/kb.py query ~/pharm-notes/kb.db --target CYP3A4

# A drug, narrowed to interactions
python3 scripts/kb.py query ~/pharm-notes/kb.db --drug warfarin --category interaction

# A pathway + free text
python3 scripts/kb.py query ~/pharm-notes/kb.db --pathway "hepatic metabolism" --text clearance

# What's in the library
python3 scripts/kb.py videos ~/pharm-notes/kb.db
python3 scripts/kb.py stats  ~/pharm-notes/kb.db
```

Each result carries its source video and a jump-back link. Present results
grouped sensibly, and when the user asks to "compare" or "connect", synthesize
across the returned entries (noting where different lectures agree or differ),
always citing the source video + timestamp. Use `--json` when you need to
post-process results yourself.

## Quality bar

- Organize by knowledge, not timestamps; explain concepts, don't just name them.
- Use frames for anything visual; describe what the diagram/structure shows.
- Every entry traceable to video + timestamp; flag garbled captions in the
  explanation rather than guessing drug names, doses, or mechanisms.
- Be careful with clinical specifics (doses, contraindications): report what the
  lecture states and attribute it; do not invent or "correct" from memory.

## Roadmap hooks (not yet enabled)

- Chemical structure → SMILES (OSR via DECIMER/MolScribe) is a heavy optional
  module; `entries` already supports a `frame` so structures are captured as
  images today and can be machine-encoded later.
- Spaced-repetition export (Anki) can read directly from `kb.db`.
