#!/usr/bin/env python3
"""Super Investing research agent.

Usage:
    python agent.py --ticker SRVCABLE --pack research_pack --today 2026-09-23 --mode staged
    python agent.py --ticker SRVCABLE --pack research_pack --mode naive     # baseline for the test log

Modes (each maps to a run in TEST_LOG.md):
    naive    one prompt, all docs, no rules                     (Run 1)
    triage   triage stage + system prompt, then draft           (Run 2)
    staged   triage -> claims+recompute -> conflicts -> draft -> verify  (Run 3+, default)

Env: GEMINI_API_KEY (default provider, free tier). Optional: MODEL (default gemini-3.8-flash).
     To use Claude instead: PROVIDER=anthropic ANTHROPIC_API_KEY=... (MODEL default claude-sonnet-5-5).
     Other OpenAI-compatible APIs (Groq, OpenRouter): PROVIDER=openai-compatible LLM_API_KEY=... LLM_BASE_URL=... MODEL=...
"""
import argparse, json, os, re, sys
from pathlib import Path

import time

# PROVIDER=gemini (default, free tier) | openai-compatible (Groq, OpenRouter, etc.) | anthropic
PROVIDER = os.environ.get("PROVIDER", "gemini").lower()
DEFAULTS = {
    "gemini": ("gemini-3.8-flash", "https://generativelanguage.googleapis.com/v1beta/openai/", "GEMINI_API_KEY"),
    "openai-compatible": ("", "", "LLM_API_KEY"),
    "anthropic": ("claude-sonnet-5-5", "", "ANTHROPIC_API_KEY"),
}
_model, _base, _keyvar = DEFAULTS[PROVIDER]
MODEL = os.environ.get("MODEL", _model)
BASE_URL = os.environ.get("LLM_BASE_URL", _base)
API_KEY = os.environ.get(_keyvar)
HERE = Path(__file__).parent
_client = None


def get_client():
    global _client
    if _client is None:
        if not API_KEY:
            sys.exit(f"Set {_keyvar} first (see README).")
        if PROVIDER == "anthropic":
            import anthropic
            _client = anthropic.Anthropic(api_key=API_KEY)
        else:
            from openai import OpenAI
            _client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
    return _client


# ---------- helpers ----------
def llm(system: str, user: str, max_tokens: int = 4000) -> str:
    c = get_client()
    for attempt in range(5):
        try:
            if PROVIDER == "anthropic":
                r = c.messages.create(
                    model=MODEL, max_tokens=max_tokens, temperature=0,
                    system=system, messages=[{"role": "user", "content": user}],
                )
                return "".join(b.text for b in r.content if b.type == "text")
            # OpenAI-compatible: thinking models count reasoning tokens against the limit, so leave headroom
            r = c.chat.completions.create(
                model=MODEL, max_tokens=max_tokens * 4, temperature=0,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            )
            return r.choices[0].message.content or ""
        except Exception as e:  # free tiers rate-limit; back off and retry
            msg = str(e)
            if attempt < 4 and ("429" in msg or "rate" in msg.lower() or "503" in msg or "overloaded" in msg.lower()):
                wait = 15 * (attempt + 1)
                print(f"   rate limited, waiting {wait}s...", file=sys.stderr)
                time.sleep(wait)
                continue
            raise


def llm_json(system: str, user: str, max_tokens: int = 4000):
    txt = llm(system + "\n\nReturn ONLY valid JSON, no prose, no code fences.", user, max_tokens)
    txt = re.sub(r"^```(?:json)?|```$", "", txt.strip(), flags=re.M).strip()
    return json.loads(txt)


def load_pack(pack_dir: Path):
    docs = []
    for i, p in enumerate(sorted(pack_dir.glob("*.md")), start=1):
        raw = p.read_text(encoding="utf-8")
        m = re.match(r"^---\n(.*?)\n---\n(.*)$", raw, re.S)
        meta, body = {}, raw
        if m:
            for line in m.group(1).splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip()] = v.strip()
            body = m.group(2).strip()
        docs.append({"id": f"S{i}", "file": p.name, "meta": meta, "body": body})
    return docs


def render_docs(docs, ids=None):
    out = []
    for d in docs:
        if ids is not None and d["id"] not in ids:
            continue
        m = d["meta"]
        out.append(
            f"=== [{d['id']}] ===\nsource: {m.get('source')}\nurl: {m.get('url')}\n"
            f"published: {m.get('published')}\ntype: {m.get('type')}\n\n{d['body']}\n"
        )
    return "\n".join(out)


def system_prompt(ticker, today):
    s = (HERE / "system_prompt.md").read_text(encoding="utf-8")
    return s.replace("{TODAY}", today).replace("{TICKER}", ticker)


# ---------- stages ----------
def triage(docs, ticker, today):
    sys_p = (
        f"You triage scraped documents for a research brief on NSE ticker {ticker}. Today is {today}.\n"
        "The listed company is Sarvottam Cables Ltd only if the pack shows it (power cables manufacturer, Mumbai HQ). "
        "For EACH document decide:\n"
        "- same_entity: true/false, with the evidence (name, business, location, people)\n"
        "- authority: 1 = exchange filing, 2 = company release/transcript, 3 = news\n"
        "- freshness: 'current', 'dated' (older than ~6 months or superseded by a newer doc), or 'stale'\n"
        "- verdict: 'include', 'downweight' (use only as dated history), or 'exclude'\n"
        "- reason: one sentence.\n"
        'Output JSON: {"docs":[{"id":"S1","same_entity":true,"authority":1,"freshness":"current","verdict":"include","reason":"..."}]}'
    )
    return llm_json(sys_p, render_docs(docs))["docs"]


def extract_claims(docs, tri, ticker, today):
    keep = {t["id"] for t in tri if t["verdict"] != "exclude"}
    sys_p = (
        "Extract atomic factual claims from the documents. One fact per claim. Copy numbers exactly as written.\n"
        "Mark who is speaking: 'fact' (reported figure/filing), 'management_claim' (expectation, opinion, forecast), or 'third_party'.\n"
        "Also list every stated growth percentage as a calc so code can re-verify it.\n"
        'JSON: {"claims":[{"id":"C1","src":"S6","text":"...","kind":"fact|management_claim|third_party"}],'
        '"calcs":[{"label":"PAT YoY","src":"S6","current":82,"previous":77,"stated_pct":5.9}]}'
    )
    return llm_json(sys_p, render_docs(docs, keep), max_tokens=6000)


def recompute(calcs):
    """Deterministic arithmetic check done in code, not by the LLM."""
    res = []
    for c in calcs:
        try:
            actual = round((c["current"] / c["previous"] - 1) * 100, 1)
            stated = c.get("stated_pct")
            ok = stated is None or abs(actual - float(stated)) < 0.15
            res.append({**c, "recomputed_pct": actual, "matches": ok})
        except (KeyError, TypeError, ZeroDivisionError):
            continue
    return res


def conflicts(claims, tri, today):
    sys_p = (
        f"You audit extracted claims. Today is {today}. Find: (1) numeric/factual conflicts between sources, "
        "(2) management claims that are unverified or self-serving, (3) facts missing from the pack that a retail investor "
        "would need (e.g. current share price, appeal outcome), (4) stale data. For conflicts, say which source to trust and why "
        "(authority ranking: exchange filing > company release/transcript > news). Compare any rupee risk to a base in the pack "
        'and show the arithmetic. JSON: {"issues":[{"type":"conflict|unverified|missing|stale","detail":"...","sources":["S6","S8"],"resolution":"..."}]}'
    )
    payload = json.dumps({"claims": claims["claims"], "triage": tri}, ensure_ascii=False)
    return llm_json(sys_p, payload, max_tokens=5000)["issues"]


def draft(docs, tri, claims, calc_results, issues, ticker, today):
    keep = {t["id"] for t in tri if t["verdict"] != "exclude"}
    user = (
        "Write the research brief using ONLY the material below.\n\n"
        f"## Triage decisions\n{json.dumps(tri, ensure_ascii=False, indent=1)}\n\n"
        f"## Extracted claims\n{json.dumps(claims['claims'], ensure_ascii=False, indent=1)}\n\n"
        f"## Arithmetic re-check (computed in code)\n{json.dumps(calc_results, ensure_ascii=False, indent=1)}\n\n"
        f"## Issues found\n{json.dumps(issues, ensure_ascii=False, indent=1)}\n\n"
        f"## Source documents for reference\n{render_docs(docs, keep)}"
    )
    return llm(system_prompt(ticker, today), user, max_tokens=3000)


def verify(brief, docs, tri, calc_results, ticker, today):
    sys_p = (
        "You are a strict fact-checker. You get a draft research brief and the source documents. For EVERY number and "
        "factual claim in the draft: (a) is it in the cited source? (b) does the cited ID match? (c) is it stated as fact when "
        "the source only has management's expectation? (d) is a stale figure presented as current? (e) is anything from outside "
        "the sources? (f) does any excluded source leak in? (g) is there any buy/sell advice? "
        "Then output the CORRECTED brief in full (same Markdown structure, about one page), fixing or deleting failing "
        "statements. Output only the brief, no commentary."
    )
    user = (
        f"## Draft\n{brief}\n\n## Triage\n{json.dumps(tri, ensure_ascii=False)}\n\n"
        f"## Code-verified arithmetic\n{json.dumps(calc_results, ensure_ascii=False)}\n\n"
        f"## Sources\n{render_docs(docs)}"
    )
    return llm(sys_p, user, max_tokens=3000)


# ---------- modes ----------
def run(args):
    docs = load_pack(Path(args.pack))
    logs = Path(args.logdir)
    logs.mkdir(parents=True, exist_ok=True)
    tag = args.mode

    def save(name, obj):
        p = logs / f"{tag}_{name}.json"
        p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.mode == "naive":
        brief = llm(
            "You are a stock research assistant.",
            f"Write a one-page research brief (Snapshot, Bull case, Bear case, Open questions, Sources) for NSE:{args.ticker} "
            f"from these documents.\n\n{render_docs(docs)}",
            max_tokens=2500,
        )
        return brief

    print("[1/6] triage...", file=sys.stderr)
    tri = triage(docs, args.ticker, args.today)
    save("triage", tri)

    if args.mode == "triage":
        keep = {t["id"] for t in tri if t["verdict"] != "exclude"}
        user = f"Triage decisions:\n{json.dumps(tri, indent=1)}\n\nDocuments:\n{render_docs(docs, keep)}"
        return llm(system_prompt(args.ticker, args.today), user, max_tokens=3000)

    print("[2/6] claim extraction...", file=sys.stderr)
    claims = extract_claims(docs, tri, args.ticker, args.today)
    save("claims", claims)

    print("[3/6] recomputing arithmetic in code...", file=sys.stderr)
    calc = recompute(claims.get("calcs", []))
    save("calcs", calc)
    for c in calc:
        if not c["matches"]:
            print(f"   MISMATCH {c['label']}: stated {c.get('stated_pct')}% vs recomputed {c['recomputed_pct']}%", file=sys.stderr)

    print("[4/6] conflict + gap check...", file=sys.stderr)
    issues = conflicts(claims, tri, args.today)
    save("issues", issues)

    print("[5/6] drafting...", file=sys.stderr)
    d = draft(docs, tri, claims, calc, issues, args.ticker, args.today)
    save("draft", {"draft": d})

    print("[6/6] verifying...", file=sys.stderr)
    return verify(d, docs, tri, calc, args.ticker, args.today)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticker", default="SRVCABLE")
    ap.add_argument("--pack", default="research_pack")
    ap.add_argument("--today", default="2026-09-23")
    ap.add_argument("--mode", choices=["naive", "triage", "staged"], default="staged")
    ap.add_argument("--logdir", default="logs")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    brief = run(a)
    out = Path(a.out or f"output/{a.ticker.lower()}_brief_{a.mode}.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(brief, encoding="utf-8")
    print(brief)
    print(f"\nSaved to {out}", file=sys.stderr)
