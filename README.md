# PharmScribe

Turn pharmacology / pharmaceutical-science video lectures into **bilingual
(English term + Chinese explanation) Word study notes**, and accumulate every
lecture into a **local, queryable knowledge base** with exact source
traceability (jump back to the precise video + timestamp).

**Vendor-neutral.** You do *not* need a specific AI membership. Downloading,
transcription, the knowledge base, and Word generation are plain programs. Only
the "extract knowledge from the transcript" step uses an AI model — and that
model is **swappable**: Claude, OpenAI (ChatGPT), Gemini, a free local model via
Ollama, or none at all.

## Two ways to use it

### A. Standalone CLI (works for everyone)

```bash
# Pharmacology lecture, using a free local model (no API key, no membership)
pharmscribe ingest "https://youtu.be/XXXX" --engine local

# Using your own API key from any one vendor
pharmscribe ingest "https://youtu.be/XXXX" --engine openai      # ChatGPT/OpenAI
pharmscribe ingest "https://youtu.be/XXXX" --engine gemini      # Google Gemini
pharmscribe ingest "https://youtu.be/XXXX" --engine claude      # Anthropic

# Cross-query your whole library (no AI needed)
pharmscribe query --target CYP3A4
pharmscribe query --drug warfarin --category interaction
pharmscribe videos
```

The engine is chosen with `--engine` or the `PHARMSCRIBE_ENGINE` env var.

### B. Claude Code skill (for Claude users)

Drop the folder in `~/.claude/skills/` and just ask Claude to summarize a video.
In this mode Claude does the extraction itself (and can additionally *see* the
video frames — slides, mechanism diagrams, structures — for richer notes).

## Choosing an engine

| `--engine` | Needs | Membership? | Notes |
|-----------|-------|-------------|-------|
| `local`   | [Ollama](https://ollama.com) + a model (`ollama pull qwen2.5`) | None | Free, private, offline |
| `openai`  | `pip install openai`, `OPENAI_API_KEY` | Your own key | |
| `gemini`  | `pip install google-generativeai`, `GEMINI_API_KEY` | Your own key | |
| `claude`  | `pip install anthropic`, `ANTHROPIC_API_KEY` | Your own key | |
| `none`    | nothing | None | Offline keyword fallback; low quality |

Only the engine you pick needs installing.

## Requirements

- `yt-dlp`, `ffmpeg` on PATH
- `pip install python-docx`
- `sqlite3` (Python standard library)
- An engine from the table above (or `--engine none`)
- Whisper (`pip install openai-whisper`) — optional, only when a video lacks captions

## Output

1. A bilingual **Word document** per lecture, grouped by pharmacology category
   (mechanism / PK / PD / ADR / interactions / SAR / indications), with clickable
   "re-watch @ timestamp" links (and embedded frames in skill mode).
2. A growing **SQLite knowledge base** queryable by drug, target, pathway, topic,
   or free text — combinable as AND filters, every result traced to its source.

## Notes & limits

- The portable CLI extracts from **captions/transcript** (text), so it runs
  identically across all engines. Frame-aware (multimodal) extraction currently
  requires the Claude skill path, where the model can view images directly.
- Educational note-taking only — not medical or clinical advice.

## Roadmap

- Chemical structure → SMILES (optical structure recognition)
- Anki / spaced-repetition export straight from the knowledge base
- Frame-aware extraction for the CLI engines as their vision APIs allow

## License

MIT — see [LICENSE](LICENSE).
