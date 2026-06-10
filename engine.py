#!/usr/bin/env python3
"""Pluggable extraction engine.

Turns a lecture transcript segment into structured knowledge entries (JSON).
The whole point: the AI backend is swappable, so the tool is not tied to any one
vendor. Pick a backend with --engine or the PHARMSCRIBE_ENGINE env var:

  claude  -> Anthropic API            (needs ANTHROPIC_API_KEY)
  openai  -> OpenAI API (ChatGPT)     (needs OPENAI_API_KEY)
  gemini  -> Google Gemini API        (needs GEMINI_API_KEY)
  local   -> local model via Ollama   (no key, no membership; needs `ollama`)
  none    -> offline heuristic         (no AI at all; rough keyword extraction)

All backends are optional dependencies — only the one you choose needs to be
installed. The prompt and the expected JSON schema are identical across
backends, so output is consistent no matter who does the inference.
"""
import json
import os
import re
import subprocess
import sys
import urllib.request

# The shared instruction. {domain} is injected by the caller (pharma / finance).
SYSTEM_PROMPT = """You extract structured study knowledge from a lecture transcript segment in the domain of {domain}.
Return ONLY a JSON array (no prose, no markdown fences). Each element:
{{"ts_seconds": int, "ts_hhmmss": "HH:MM:SS", "category": "<one of: {categories}>",
  "term_en": "English term", "term_zh": "中文术语 (if a standard one exists, else empty)",
  "explanation_zh": "2-4 sentence study-ready explanation in Chinese",
  {tag_fields}}}
Extract only substantive knowledge (definitions, mechanisms, methods, worked examples, key distinctions).
Drop filler, admin, greetings, repetition. If the segment has no real content, return [].
Use the timestamp given for the segment start. Keep technical terms accurate; do not invent facts."""

DOMAIN_PRESETS = {
    "pharma": {
        "domain": "pharmacology / pharmaceutical science",
        "categories": "mechanism, PK, PD, SAR, indication, contraindication, ADR, interaction, concept",
        "tag_fields": '"drugs": [], "targets": [], "pathways": [], "topics": []',
    },
    "finance": {
        "domain": "economics / finance",
        "categories": "concept, model, formula, mechanism, metric, application, risk, other",
        "tag_fields": '"concepts": [], "models": [], "metrics": [], "markets": [], "topics": []',
    },
}


def build_prompt(domain_key, segment_text, ts_seconds, ts_hhmmss):
    p = DOMAIN_PRESETS[domain_key]
    sys_p = SYSTEM_PROMPT.format(**p)
    user_p = (f"Segment start: {ts_hhmmss} ({ts_seconds}s)\n"
              f"Transcript:\n{segment_text}\n\nReturn the JSON array now.")
    return sys_p, user_p


def _extract_json_array(text):
    """Pull the first JSON array out of a model response, tolerating stray prose."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1:
        return []
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return []


# ---- Backends -------------------------------------------------------------

def call_claude(sys_p, user_p, model="claude-sonnet-4-6"):
    import anthropic  # pip install anthropic
    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY
    msg = client.messages.create(
        model=model, max_tokens=4096, system=sys_p,
        messages=[{"role": "user", "content": user_p}])
    return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")


def call_openai(sys_p, user_p, model="gpt-4o-mini"):
    from openai import OpenAI  # pip install openai
    client = OpenAI()  # reads OPENAI_API_KEY
    r = client.chat.completions.create(
        model=model, messages=[{"role": "system", "content": sys_p},
                                {"role": "user", "content": user_p}])
    return r.choices[0].message.content


def call_gemini(sys_p, user_p, model="gemini-1.5-flash"):
    import google.generativeai as genai  # pip install google-generativeai
    genai.configure(api_key=os.environ["GEMINI_API_KEY"])
    m = genai.GenerativeModel(model, system_instruction=sys_p)
    return m.generate_content(user_p).text


def call_local(sys_p, user_p, model=None):
    """Local model via Ollama's HTTP API. No key, no membership.
    Install: https://ollama.com ; then e.g. `ollama pull qwen2.5`."""
    model = model or os.environ.get("PHARMSCRIBE_LOCAL_MODEL", "qwen2.5")
    payload = json.dumps({
        "model": model, "stream": False,
        "messages": [{"role": "system", "content": sys_p},
                     {"role": "user", "content": user_p}],
    }).encode()
    req = urllib.request.Request("http://localhost:11434/api/chat", data=payload,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as resp:
        data = json.loads(resp.read())
    return data.get("message", {}).get("content", "")


def call_none(sys_p, user_p, model=None):
    """No AI at all: a crude heuristic so the pipeline still produces *something*
    offline. Picks capitalized/technical-looking terms. Quality is low — this is
    a fallback, not a real extractor."""
    text = user_p.split("Transcript:\n", 1)[-1]
    cands = re.findall(r"\b([A-Z][A-Za-z0-9\-]{3,}(?:\s[A-Z][A-Za-z0-9\-]+){0,2})\b", text)
    seen, out = set(), []
    for c in cands:
        k = c.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append({"ts_seconds": 0, "ts_hhmmss": "00:00:00", "category": "concept",
                    "term_en": c, "term_zh": "", "explanation_zh": "(离线模式未生成解释,请用 AI 引擎重跑)",
                    "topics": []})
        if len(out) >= 8:
            break
    return json.dumps(out, ensure_ascii=False)


BACKENDS = {"claude": call_claude, "openai": call_openai, "gemini": call_gemini,
            "local": call_local, "none": call_none}


def extract(domain_key, segment_text, ts_seconds, ts_hhmmss,
            engine=None, model=None):
    engine = engine or os.environ.get("PHARMSCRIBE_ENGINE", "none")
    if engine not in BACKENDS:
        sys.exit(f"Unknown engine '{engine}'. Choose: {', '.join(BACKENDS)}")
    sys_p, user_p = build_prompt(domain_key, segment_text, ts_seconds, ts_hhmmss)
    try:
        raw = BACKENDS[engine](sys_p, user_p, model=model) if model else BACKENDS[engine](sys_p, user_p)
    except ImportError as e:
        sys.exit(f"Engine '{engine}' needs a package that isn't installed: {e}. "
                 f"See README for the pip/install command.")
    except Exception as e:
        sys.exit(f"Engine '{engine}' failed: {e}")
    return _extract_json_array(raw)


if __name__ == "__main__":
    # tiny self-test of the offline parser + JSON extractor (no network needed)
    sample = "Transcript:\nCYP3A4 inhibition raises drug levels. Bioavailability matters."
    out = call_none("", "x\n" + sample)
    print("offline self-test ->", _extract_json_array(out))
