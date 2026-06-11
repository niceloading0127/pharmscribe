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

CRITICAL — TAGS ARE REQUIRED: the tag arrays ({tag_keys}) are the most important
fields. For EVERY entry you MUST fill at least one or two of them with the actual
named entities mentioned (lowercase). Never return all tag arrays empty. Pull
every relevant {tag_examples} you can identify from the term and explanation.

Example of ONE well-formed entry (follow this shape and tagging discipline):
{example}

Extract only substantive knowledge (definitions, mechanisms, methods, worked examples, key distinctions).
Drop filler, admin, greetings, repetition. If the segment has no real content, return [].
Use the timestamp given for the segment start. Keep technical terms accurate; do not invent facts."""

DOMAIN_PRESETS = {
    "pharma": {
        "domain": "pharmacology / pharmaceutical science",
        "categories": "mechanism, PK, PD, SAR, indication, contraindication, ADR, interaction, concept",
        "tag_fields": '"drugs": [], "targets": [], "pathways": [], "topics": []',
        "tag_keys": "drugs, targets, pathways, topics",
        "tag_examples": "drug names, receptors/enzymes/proteins (targets), metabolic pathways",
        "example": ('{"ts_seconds": 1450, "ts_hhmmss": "00:24:10", "category": "interaction", '
                    '"term_en": "CYP3A4 inhibition", "term_zh": "CYP3A4 抑制", '
                    '"explanation_zh": "酮康唑强效抑制肝脏 CYP3A4,使经该酶代谢的药物血药浓度升高。", '
                    '"drugs": ["ketoconazole"], "targets": ["cyp3a4"], '
                    '"pathways": ["hepatic metabolism"], "topics": ["drug interaction"]}'),
    },
    "finance": {
        "domain": "economics / finance",
        "categories": "concept, model, formula, mechanism, metric, application, risk, other",
        "tag_fields": '"concepts": [], "models": [], "metrics": [], "markets": [], "topics": []',
        "tag_keys": "concepts, models, metrics, markets, topics",
        "tag_examples": "core concepts, named models/theories, metrics/ratios, markets/instruments",
        "example": ('{"ts_seconds": 540, "ts_hhmmss": "00:09:00", "category": "model", '
                    '"term_en": "Capital Asset Pricing Model", "term_zh": "资本资产定价模型", '
                    '"explanation_zh": "用系统性风险 beta 解释资产预期收益:E(R)=Rf+β(Rm−Rf)。", '
                    '"concepts": ["systematic risk"], "models": ["capm"], '
                    '"metrics": ["beta", "expected return"], "markets": ["equities"], '
                    '"topics": ["valuation"]}'),
    },
}

# tag json-keys per domain, used by the code-side fallback
DOMAIN_TAG_KEYS = {
    "pharma": ["drugs", "targets", "pathways", "topics"],
    "finance": ["concepts", "models", "metrics", "markets", "topics"],
}


def build_prompt(domain_key, segment_text, ts_seconds, ts_hhmmss):
    p = DOMAIN_PRESETS[domain_key]
    sys_p = SYSTEM_PROMPT.format(**p)
    user_p = (f"Segment start: {ts_hhmmss} ({ts_seconds}s)\n"
              f"Transcript:\n{segment_text}\n\nReturn the JSON array now.")
    return sys_p, user_p


def _extract_json_array(text):
    """Pull a JSON array out of a model response, tolerating stray prose and the
    {"entries": [...]} object wrapper that JSON-mode backends produce."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    # Case 1: an object wrapper like {"entries": [...]}
    if text.lstrip().startswith("{"):
        try:
            obj = json.loads(text)
            for key in ("entries", "items", "data", "results"):
                if isinstance(obj.get(key), list):
                    return obj[key]
            # a single entry object -> wrap it
            if "term_en" in obj:
                return [obj]
        except json.JSONDecodeError:
            pass
    # Case 2: a bare array
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
    Install: https://ollama.com ; then e.g. `ollama pull qwen2.5`.
    Uses format=json so even small models return parseable JSON."""
    model = model or os.environ.get("PHARMSCRIBE_LOCAL_MODEL", "qwen2.5")
    # Ollama's format=json forces a single JSON value; ask for an object that
    # wraps the array so the constraint is satisfiable, then unwrap below.
    user_p2 = user_p + '\n\nReturn a JSON object of the form {"entries": [ ... ]}.'
    payload = json.dumps({
        "model": model, "stream": False, "format": "json",
        "options": {"temperature": 0.1},
        "messages": [{"role": "system", "content": sys_p},
                     {"role": "user", "content": user_p2}],
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

# Small known-entity lexicons used ONLY as a last-resort backfill when the model
# returns an entry with all tag arrays empty. Lowercase, matched as whole words.
# Not exhaustive — just enough to keep cross-retrieval working on common terms.
LEXICON = {
    "pharma": {
        # ---- 分子靶点:受体 / 酶 / 转运体 / 离子通道 ----
        "targets": [
            # CYP 及代谢酶
            "cyp3a4", "cyp2d6", "cyp2c9", "cyp2c19", "cyp1a2", "cyp2e1", "cyp2b6", "cyp51",
            # 受体
            "beta receptor", "alpha receptor", "muscarinic receptor", "nicotinic receptor",
            "dopamine receptor", "serotonin receptor", "5-ht", "histamine receptor", "h1", "h2",
            "opioid receptor", "adrenergic receptor", "gaba", "nmda", "glutamate receptor",
            # 酶
            "cox-1", "cox-2", "ace", "hmg-coa reductase", "acetylcholinesterase",
            "monoamine oxidase", "mao", "phosphodiesterase", "pde5", "dna gyrase",
            "topoisomerase", "dihydrofolate reductase", "na-k-atpase", "proton pump",
            "xanthine oxidase", "beta-lactamase",
            # 转运体 / 通道
            "p-gp", "p-glycoprotein", "oatp", "bcrp", "oct", "oat",
            "sodium channel", "calcium channel", "potassium channel",
            # 中文
            "受体", "转运体", "离子通道", "钠通道", "钙通道", "钾通道",
            "乙酰胆碱酯酶", "单胺氧化酶", "环氧合酶", "磷酸二酯酶", "质子泵", "拓扑异构酶",
        ],
        # ---- 通路:代谢 / 生物合成 / 信号 / 药剂过程 ----
        "pathways": [
            # 代谢
            "hepatic metabolism", "first-pass metabolism", "renal excretion", "biliary excretion",
            "phase i metabolism", "phase ii metabolism", "glucuronidation", "sulfation",
            "acetylation", "methylation", "oxidation", "conjugation",
            "absorption", "distribution", "metabolism", "excretion",
            # 生物合成 / 微生物
            "cell wall synthesis", "peptidoglycan synthesis", "folate synthesis",
            "protein synthesis", "ergosterol biosynthesis",
            # 信号
            "signal transduction", "second messenger", "camp", "gpcr signaling",
            # 药剂过程
            "dissolution", "disintegration", "sustained release", "controlled release",
            # 中文
            "肝代谢", "首过代谢", "肾排泄", "胆汁排泄", "I相代谢", "II相代谢",
            "葡萄糖醛酸化", "结合反应", "乙酰化", "甲基化", "氧化", "吸收", "分布", "代谢", "排泄",
            "细胞壁合成", "蛋白质合成", "信号转导", "崩解", "溶出", "缓释", "控释",
        ],
        # ---- 主题:按学科分组 ----
        "topics": [
            # 药理学 / 药效学
            "mechanism of action", "agonist", "antagonist", "partial agonist",
            "receptor binding", "dose-response", "efficacy", "potency", "affinity",
            "therapeutic index", "selectivity",
            "激动剂", "拮抗剂", "部分激动剂", "量效关系", "效价", "亲和力", "选择性", "治疗指数",
            # 药代动力学
            "bioavailability", "half-life", "clearance", "volume of distribution",
            "auc", "cmax", "tmax", "steady state", "first-order kinetics", "zero-order kinetics",
            "pharmacokinetics", "pharmacodynamics",
            "生物利用度", "半衰期", "清除率", "表观分布容积", "稳态", "药代动力学", "药效动力学",
            # 药物化学
            "structure-activity relationship", "sar", "pharmacophore", "prodrug",
            "chirality", "functional group", "lead compound", "bioisostere", "drug design",
            "构效关系", "药效团", "前药", "手性", "官能团", "先导化合物", "药物设计",
            # 药剂学
            "dosage form", "tablet", "capsule", "suspension", "emulsion", "ointment",
            "bioequivalence", "excipient", "formulation", "stability",
            "剂型", "片剂", "胶囊", "混悬剂", "乳剂", "软膏", "生物等效性", "辅料", "处方", "稳定性",
            # 药物分析
            "hplc", "lc-ms", "uv spectroscopy", "titration", "chromatography",
            "mass spectrometry", "assay", "purity",
            "高效液相色谱", "质谱", "紫外", "滴定", "色谱", "含量测定", "纯度",
            # 生药学 / 天然药物
            "alkaloid", "glycoside", "flavonoid", "terpenoid", "saponin", "volatile oil",
            "生物碱", "苷类", "黄酮", "萜类", "皂苷", "挥发油",
            # 临床药学 / 治疗
            "drug interaction", "adverse drug reaction", "contraindication", "indication",
            "dosing regimen", "toxicity", "hepatotoxicity", "nephrotoxicity",
            "药物相互作用", "不良反应", "禁忌症", "适应症", "给药方案", "毒性", "肝毒性", "肾毒性",
            # 抗菌 / 微生物
            "antibiotic resistance", "mic", "spectrum of activity",
            "耐药性", "最低抑菌浓度", "抗菌谱",
            # 通用
            "adme", "dosing", "bioavailability",
        ],
    },
    "finance": {
        "models": ["capm", "wacc", "dcf", "black-scholes", "is-lm", "solow",
                   "资本资产定价模型", "加权平均资本成本"],
        "metrics": ["beta", "p/e", "sharpe ratio", "duration", "gdp", "cpi",
                    "roe", "roi", "irr", "npv", "yield",
                    "贝塔", "市盈率", "夏普比率", "久期", "收益率", "波动率", "相关性"],
        "markets": ["equities", "bonds", "options", "derivatives", "forex", "fx",
                    "commodities", "futures",
                    "股票", "债券", "期权", "衍生品", "外汇", "大宗商品", "期货"],
        "topics": ["valuation", "risk management", "monetary policy", "diversification",
                   "portfolio", "arbitrage", "liquidity",
                   "估值", "风险管理", "货币政策", "分散化", "投资组合", "套利", "流动性"],
    },
}


def _backfill_tags(domain_key, entry):
    """If a model entry has all tag arrays empty, scan its term+explanation against
    a small lexicon and fill what we can find. Keeps cross-retrieval working even
    when a small local model forgets to tag."""
    keys = DOMAIN_TAG_KEYS[domain_key]
    has_any = any(entry.get(k) for k in keys)
    if has_any:
        return entry
    blob = (entry.get("term_en", "") + " " + entry.get("term_zh", "") + " " +
            entry.get("explanation_zh", "")).lower()
    lex = LEXICON.get(domain_key, {})
    for tag_type, words in lex.items():
        found = [w for w in words if re.search(r"(?<![a-z0-9])" + re.escape(w) + r"(?![a-z0-9])", blob)]
        if found:
            entry[tag_type] = sorted(set(found))
    # last resort: if still nothing, at least tag the term itself as a topic
    if not any(entry.get(k) for k in keys) and entry.get("term_en"):
        entry["topics"] = [entry["term_en"].strip().lower()]
    return entry


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
    entries = _extract_json_array(raw)
    return [_backfill_tags(domain_key, e) for e in entries if isinstance(e, dict)]


if __name__ == "__main__":
    # tiny self-test of the offline parser + JSON extractor (no network needed)
    sample = "Transcript:\nCYP3A4 inhibition raises drug levels. Bioavailability matters."
    out = call_none("", "x\n" + sample)
    print("offline self-test ->", _extract_json_array(out))
