#!/usr/bin/env python3
"""Ask the kit anything - offline.

BM25 search over every Markdown/YAML/SQL/script file in the kit (pure Python, no network) and
prints the best-matching passages with file:line so you can open them. Optional ``--llm`` sends
ONLY those passages plus your question to the corporate Portkey -> Bedrock gateway (same env vars
as the API: PORTKEY_API_KEY, PORTKEY_BASE_URL, PORTKEY_PROVIDER or PORTKEY_CONFIG, LLM_MODEL)
and asks for an answer that cites the passages. Never send corporate data to unapproved services.

    python3 tools/kb/ask.py "how do I rotate the dynatrace oauth client secret"
    python3 tools/kb/ask.py --top 8 "grail query returns RESULT_GONE"
    python3 tools/kb/ask.py --llm "why does the runtime return 401 before reaching FastAPI"
    python3 tools/kb/ask.py --list-topics
"""
from __future__ import annotations

import argparse
import math
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXTENSIONS = {".md", ".yaml", ".yml", ".sql", ".sh", ".py", ".ts", ".tsx", ".conf", ".json", ".service", ".timer", ".example"}
SKIP = {"node_modules", ".git", ".venv", "dist", "__pycache__", "reports", "inventory"}
TOKEN = re.compile(r"[a-z0-9][a-z0-9_.:-]*")
STOP = set("the a an and or of to in on for is are be with this that it as by at from how what why do does i my we can "
           "use using when where which who not no if then than into via your you our".split())
SYNONYMS = {"om": "openmetadata", "dt": "dynatrace", "es": "elasticsearch", "os": "opensearch", "pg": "postgresql",
            "postgres": "postgresql", "ck": "copilotkit", "llm": "bedrock", "creds": "credentials", "pw": "password",
            "rls": "row-level", "sso": "oidc", "auth": "authentication", "k8s": "kubernetes"}


@dataclass
class Chunk:
    path: Path
    line: int
    heading: str
    text: str
    tokens: Counter


def tokenize(text: str) -> list[str]:
    words = [SYNONYMS.get(w, w) for w in TOKEN.findall(text.lower())]
    return [w.strip(".:-") for w in words if w not in STOP and len(w) > 1]


def chunks(root: Path) -> list[Chunk]:
    out: list[Chunk] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or any(p in SKIP for p in path.relative_to(root).parts):
            continue
        if path.suffix not in EXTENSIONS and not path.name.endswith(".env.example"):
            continue
        if path.stat().st_size > 400_000:
            continue
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        heading, start, buf = path.name, 1, []
        for i, line in enumerate(lines, 1):
            is_heading = line.startswith("#") and path.suffix == ".md"
            if (is_heading and buf) or len(buf) >= 40:
                text = "\n".join(buf).strip()
                if text:
                    out.append(Chunk(path, start, heading, text, Counter(tokenize(heading + " " + text))))
                buf, start = [], i
            if is_heading:
                heading = line.lstrip("#").strip()
            buf.append(line)
        text = "\n".join(buf).strip()
        if text:
            out.append(Chunk(path, start, heading, text, Counter(tokenize(heading + " " + text))))
    return out


def bm25(query: list[str], corpus: list[Chunk], k1: float = 1.4, b: float = 0.75) -> list[tuple[float, Chunk]]:
    n = len(corpus)
    avg = sum(sum(c.tokens.values()) for c in corpus) / max(n, 1)
    df = Counter(t for c in corpus for t in set(c.tokens))
    scored = []
    for c in corpus:
        length = sum(c.tokens.values())
        score = 0.0
        for term in set(query):
            tf = c.tokens.get(term, 0)
            if not tf:
                continue
            idf = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
            score += idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * length / avg))
        if any(term in c.heading.lower() for term in query):
            score *= 1.3
        if c.path.suffix == ".md":
            score *= 1.15  # prefer explanations over raw code
        if score > 0:
            scored.append((score, c))
    return sorted(scored, key=lambda x: -x[0])


def answer_with_llm(question: str, hits: list[tuple[float, Chunk]]) -> str:
    try:
        from portkey_ai import Portkey
    except ImportError:
        return "(--llm needs `pip install portkey-ai` and PORTKEY_* settings)"
    kwargs = {"api_key": os.environ.get("PORTKEY_API_KEY")}
    for env, key in (("PORTKEY_BASE_URL", "base_url"), ("PORTKEY_PROVIDER", "provider"), ("PORTKEY_CONFIG", "config")):
        if os.environ.get(env):
            kwargs[key] = os.environ[env]
    if not kwargs["api_key"]:
        return "(set PORTKEY_API_KEY etc. to use --llm)"
    context = "\n\n".join(f"[S{i}] {c.path.relative_to(ROOT)}:{c.line} ({c.heading})\n{c.text[:2500]}"
                          for i, (_, c) in enumerate(hits, 1))
    client = Portkey(**kwargs)
    response = client.chat.completions.create(
        model=os.environ.get("LLM_MODEL") or None, max_tokens=900, temperature=0,
        messages=[{"role": "system", "content": "Answer ONLY from the provided sources about the Opsi revamp kit. "
                   "Cite sources as [S1]. If the sources do not answer it, say so and name the closest file."},
                  {"role": "user", "content": f"Question: {question}\n\nSources:\n{context}"}])
    return response.choices[0].message.content


def main() -> int:
    ap = argparse.ArgumentParser(description="Search the Opsi revamp kit offline")
    ap.add_argument("question", nargs="*")
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--llm", action="store_true", help="also ask the corporate Portkey->Bedrock gateway")
    ap.add_argument("--list-topics", action="store_true")
    args = ap.parse_args()
    corpus = chunks(ROOT)
    if args.list_topics:
        for c in corpus:
            if c.path.suffix == ".md" and c.line > 1:
                print(f"{c.path.relative_to(ROOT)}:{c.line}  {c.heading}")
        return 0
    if not args.question:
        ap.print_help()
        return 2
    question = " ".join(args.question)
    hits = bm25(tokenize(question), corpus)[: args.top]
    if not hits:
        print("No match. Try other words, or: python3 tools/kb/ask.py --list-topics | grep -i <word>")
        return 1
    for rank, (score, c) in enumerate(hits, 1):
        print(f"\n[{rank}] {c.path.relative_to(ROOT)}:{c.line}  -  {c.heading}  (score {score:.1f})")
        print("    " + "\n    ".join(c.text.splitlines()[:14]))
    if args.llm:
        print("\n=== answer (LLM, cites [S#] = result numbers above) ===\n" + answer_with_llm(question, hits))
    return 0


if __name__ == "__main__":
    sys.exit(main())
