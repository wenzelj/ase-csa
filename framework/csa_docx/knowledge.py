"""Knowledge: external background documents, kept apart from the discovery evidence.

Discovery evidence says what the assessed system is and does. Knowledge explains how its parts behave: how a
SQL Server availability group listener resolves, how Windows Time follows the domain hierarchy, what a vendor
product does. The framework uses knowledge to explain evidence, never as evidence of the current state.

Two folders, both outside the discovery data:

- shared:  ``<CurrentStateAssessments>/Knowledge/``      general how-it-works material for every CSA
- project: ``<project root>/00 Knowledge/``              third-party material for one system, plus its
                                                          reviewed system model (``system-model.json``)

Each folder has a ``sources.json`` registering its documents: ``{"documents": [{"file", "title", "publisher",
"url", "licence", "version", "retrieved", "type"}], "system_terms": [...]}``. ``type`` is ``vendor``,
``standard``, ``derived`` (a summary written from other sources, such as a system reference document) or
``internal``. A file with no record is still indexed, as ``unregistered``.

The index is ``csa-work/knowledge-index.sqlite``, separate from ``discovery-index.sqlite`` and from the
evidence matrix. It is rebuilt automatically when a file in either folder changes. Passages carry ``K-`` IDs
(``K-`` and six hex digits from the document, heading and text), never ``E-`` IDs.

On a section card the passages appear under "Background knowledge (not evidence)":

- A passage may explain an evidenced observation in a narrative block (Drawbridge Impact), cited on its own
  fact with basis ``background``. ``answer_sheet.validate`` refuses any other use (BACKGROUND_* codes).
- A passage from a ``derived`` document (a summary written from other sources, such as a system reference
  document) is never citable, and neither is any passage that names the system (a host name or one of
  ``system_terms``). It is shown as "Look for" with no ID, at most MAX_DERIVED per card: the agent finds the
  primary evidence or writes Unknown. A general fact a derived document repeats belongs in the knowledge
  folder as its original (vendor or standard) source.
- The system model's functions, open questions and checks are guidance only, with no IDs.

    python3 -m csa_docx.knowledge build  --workspace <project root>
    python3 -m csa_docx.knowledge search --workspace <project root> "listener DNS"
    python3 -m csa_docx.knowledge card   --workspace <project root> <card key>
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sqlite3
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[3]                 # CurrentStateAssessments
SHARED = BASE / "Knowledge"
PROJECT_DIR = "00 Knowledge"
INDEX = "knowledge-index.sqlite"
MODEL = "system-model.json"
KID = re.compile(r"\bK-[0-9A-F]{6}\b")
EXTS = {".md", ".txt", ".docx", ".pdf"}
WORDS_PER_PASSAGE = 170
MAX_PASSAGES = 6
MAX_DERIVED = 2
EXCERPT = 650
_HOST = re.compile(r"\b(?=[A-Z0-9]*\d)[A-Z][A-Z0-9]{6,}\b")
_STOP = set("""a an the and or of to in on for with by from at as is are be been was were it its this that these those
which what where when who how does do did has have had not no can could should would will may might must shall each
every any all some one two three their there they them than then also into only other about after before while being
whether system systems section question answer during event events keep keeps working work works stop stops
function functions depend depends operations mean means tested documented fallback said says say state current
against requirement rate rating one row per aspect aspects observed which""".split())


# ---------------------------------------------------------------- folders and sources

def folders(workspace: Path | None) -> list[tuple[str, Path]]:
    out = [("shared", SHARED)]
    if workspace:
        out.append(("project", Path(workspace) / PROJECT_DIR))
    return [(scope, d) for scope, d in out if d.is_dir()]


def _sources(folder: Path) -> dict:
    p = folder / "sources.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


def _files(folder: Path) -> list[Path]:
    return sorted(f for f in folder.rglob("*") if f.is_file() and f.suffix.lower() in EXTS
                  and not f.name.startswith(("~$", ".")) and f.name.lower() != "readme.md")


def _signature(workspace: Path | None) -> str:
    h = hashlib.sha1()
    for scope, d in folders(workspace):
        for f in _files(d) + [d / "sources.json"]:
            if f.is_file():
                st = f.stat()
                h.update(f"{scope}|{f.relative_to(d)}|{st.st_size}|{int(st.st_mtime)}".encode())
    h.update(Path(__file__).read_bytes())                  # a change in chunking rebuilds the index
    return h.hexdigest()


# ---------------------------------------------------------------- text extraction and passages

def _discovery_module():
    path = BASE / ".agents" / "skills" / "csa-discovery-index" / "scripts" / "discovery_index.py"
    spec = importlib.util.spec_from_file_location("csa_discovery_index", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _text(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in (".md", ".txt"):
        return path.read_text(encoding="utf-8-sig", errors="replace")
    di = _discovery_module()
    return (di.docx_text(path) if ext == ".docx" else di.pdf_text(path)) or ""


def _front_matter(text: str) -> tuple[dict, str]:
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        return {}, text
    meta = {}
    for line in m.group(1).splitlines():
        k, _, v = line.partition(":")
        if v.strip() and not line.startswith(" "):
            meta[k.strip()] = v.strip().strip('"')
    return meta, text[m.end():]


def _clean_md(text: str) -> str:
    text = re.sub(r"```.*?```", " ", text, flags=re.S)                       # code samples
    text = re.sub(r"^\s*\[!INCLUDE.*\]\s*$", "", text, flags=re.M | re.I)
    text = re.sub(r"<a id=[^>]*></a>|<[^>]+>", " ", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)                         # images
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)                     # links -> text
    text = re.sub(r"^\s*>\s*\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*$", "", text, flags=re.M)
    return text


_DOCX_HEADING = re.compile(r"^\d+(\.\d+)*\.?\s+[A-Z][^.]{2,70}$")


def passages(path: Path) -> tuple[dict, list[tuple[str, str]]]:
    """(front matter, [(heading path, passage text)]). Passages follow headings, then split near
    WORDS_PER_PASSAGE words on paragraph boundaries."""
    raw = _text(path)
    meta, body = _front_matter(raw) if path.suffix.lower() == ".md" else ({}, raw)
    md = path.suffix.lower() == ".md"
    if md:
        body = _clean_md(body)
    heads: list[str] = []
    out: list[tuple[str, str]] = []
    buf: list[str] = []

    def flush():
        words = " ".join(" ".join(buf).split())
        buf.clear()
        if len(words.split()) < 12:
            return
        out.append((" > ".join(heads) or meta.get("title", path.stem), words))

    paras = re.split(r"\n\s*\n" if md else r"\n", body)
    if md:                                       # a heading line directly above its text is its own paragraph
        split = []
        for para in paras:
            for chunk in re.split(r"\n(?=#{1,4}\s)", para):
                head, nl, rest = chunk.partition("\n")
                split += [head, rest] if nl and re.match(r"^#{1,4}\s", head) else [chunk]
        paras = split
    for para in paras:
        p = para.strip()
        if not p:
            continue
        hm = re.match(r"^(#{1,4})\s+(.+)$", p) if md else None
        if hm or (not md and _DOCX_HEADING.match(p)):
            flush()
            level = len(hm.group(1)) if hm else p.split()[0].count(".") + 1
            title = (hm.group(2) if hm else p).strip()
            heads[:] = heads[: max(level - 1, 0)] + [title]
            continue
        if sum(len(x.split()) for x in buf) + len(p.split()) > WORDS_PER_PASSAGE and buf:
            flush()
        buf.append(p.lstrip("-*0123456789. ") if md and re.match(r"^[-*]\s", p) else p)
    flush()
    return meta, out


def kid(rel: str, heading: str, text: str) -> str:
    return "K-" + hashlib.sha1(f"{rel}|{heading}|{text}".encode()).hexdigest()[:6].upper()


# ---------------------------------------------------------------- index

SCHEMA = """
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE docs(doc INTEGER PRIMARY KEY, scope TEXT, rel TEXT, title TEXT, publisher TEXT, url TEXT, licence TEXT,
                  version TEXT, retrieved TEXT, type TEXT);
CREATE TABLE passages(kid TEXT PRIMARY KEY, doc INTEGER, ord INTEGER, heading TEXT, text TEXT, names_system INTEGER);
CREATE VIRTUAL TABLE fts USING fts5(kid UNINDEXED, heading, text, tokenize='porter unicode61');
"""


def index_path(workspace: Path) -> Path:
    return Path(workspace) / "csa-work" / INDEX


def build(workspace: Path, force: bool = False) -> dict:
    """Rebuild the knowledge index when a knowledge file changed (or with force). Never touches evidence."""
    db = index_path(workspace)
    sig = _signature(workspace)
    if db.is_file() and not force:
        try:
            with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as con:
                row = con.execute("SELECT value FROM meta WHERE key='signature'").fetchone()
            if row and row[0] == sig:
                return {"status": "OK", "rebuilt": False}
        except sqlite3.Error:
            pass
    db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db)
    con.execute("PRAGMA journal_mode=MEMORY")         # no journal file: rebuilt in place, nothing is ever deleted
    for t in ("fts", "passages", "docs", "meta"):
        con.execute(f"DROP TABLE IF EXISTS {t}")
    con.executescript(SCHEMA)
    ndocs = npass = 0
    skipped = []
    for scope, folder in folders(workspace):
        src = _sources(folder)
        reg = {d["file"]: d for d in src.get("documents", [])}
        terms = [t.lower() for t in src.get("system_terms", [])]
        for f in _files(folder):
            rel = str(f.relative_to(folder))
            try:
                meta, ps = passages(f)
            except Exception as e:                        # an unreadable file is reported, never fatal
                skipped.append(f"{scope}/{rel}: {e}")
                continue
            r = reg.get(rel, {})
            cur = con.execute("INSERT INTO docs(scope, rel, title, publisher, url, licence, version, retrieved, type) "
                              "VALUES(?,?,?,?,?,?,?,?,?)",
                              (scope, rel, r.get("title") or meta.get("title") or f.stem, r.get("publisher", ""),
                               r.get("url", ""), r.get("licence", ""), r.get("version") or meta.get("ms.date", ""),
                               r.get("retrieved", ""), r.get("type", "unregistered")))
            doc = cur.lastrowid
            ndocs += 1
            for i, (head, text) in enumerate(ps):
                k = kid(f"{scope}/{rel}", head, text)
                low = text.lower()
                names = bool(_HOST.search(text)) or any(t in low for t in terms)
                con.execute("INSERT OR IGNORE INTO passages VALUES(?,?,?,?,?,?)", (k, doc, i, head, text, int(names)))
                con.execute("INSERT INTO fts(kid, heading, text) VALUES(?,?,?)", (k, head, text))
                npass += 1
    con.execute("INSERT INTO meta VALUES('signature', ?)", (sig,))
    con.commit()
    con.close()
    return {"status": "OK", "rebuilt": True, "documents": ndocs, "passages": npass, "skipped": skipped}


def _terms(text: str) -> list[str]:
    seen, out = set(), []
    for w in re.findall(r"[A-Za-z][A-Za-z0-9]+", text or ""):
        lw = w.lower()
        if len(lw) > 2 and lw not in _STOP and lw not in seen:
            seen.add(lw)
            out.append(lw)
    return out


def search(workspace: Path, query: str, limit: int = 5, must: list[str] | None = None) -> list[dict]:
    """Best passages for the query (OR of its terms, BM25). ``must``: passages containing one of these
    terms rank first."""
    build(workspace)
    terms = _terms(query)
    if not terms:
        return []
    q = " OR ".join(f'"{t}"' for t in terms)
    sql = ("SELECT p.kid, p.heading, p.text, p.names_system, d.scope, d.rel, d.title, d.publisher, d.url, d.version, "
           "d.type, bm25(fts) AS score FROM fts JOIN passages p ON p.kid = fts.kid JOIN docs d ON d.doc = p.doc "
           "WHERE fts MATCH ? ORDER BY score LIMIT ?")
    with sqlite3.connect(f"file:{index_path(workspace)}?mode=ro", uri=True) as con:
        rows = []
        mterms = [t for t in (_terms(" ".join(must or [])))]
        if mterms:
            mq = "(" + " OR ".join(f'"{t}"' for t in mterms) + ") AND (" + q + ")"
            rows = con.execute(sql, (mq, limit)).fetchall()
        if len(rows) < limit:
            have = {r[0] for r in rows}
            rows += [r for r in con.execute(sql, (q, limit * 2)).fetchall() if r[0] not in have][: limit - len(rows)]
    keys = ("kid", "heading", "text", "names_system", "scope", "rel", "title", "publisher", "url", "version", "type", "score")
    return [dict(zip(keys, r)) for r in rows]


# ---------------------------------------------------------------- system model and the card

def system_model(workspace: Path | None) -> dict:
    if not workspace:
        return {}
    p = Path(workspace) / PROJECT_DIR / MODEL
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


_ISOLATION_Q = re.compile(r"\b(drawbridge|isolat\w*)\b", re.I)


def open_questions(model: dict, key: str, questions: list[dict]) -> list[str]:
    """The system model's open questions that belong on this card: those tagged with this section's key in
    ``sections``, and those tagged ``isolation: true`` when the card asks an isolation (Drawbridge) question. A
    question with no tags is shown on no card: an open question copied onto every card becomes an off-topic
    Unknown line in every section's Discovery Required."""
    iso = any(q.get("kind") == "narrative" and _ISOLATION_Q.search(q.get("text", "")) for q in questions)
    out = []
    for q in model.get("open_questions", []):
        if isinstance(q, str):
            continue
        if key in q.get("sections", []) or (iso and q.get("isolation")):
            out.append(q["question"])
    return out


def _label(p: dict) -> str:
    bits = [p["type"], p["publisher"] or p["scope"], p["version"] and f"version {p['version']}"]
    return f"{', '.join(b for b in bits if b)}: {p['title']} > {p['heading'].split(' > ')[-1]}"


def card_section(key: str, topic: str, questions: list[dict], scope_text: str, workspace: Path | None) \
        -> tuple[list[str], list[str]]:
    """(card lines, citable K- IDs) for one card. Empty when there is no knowledge and no system model."""
    model = system_model(workspace)
    dom = (model.get("domains") or {}).get(key) or {}
    have_knowledge = any(_files(d) for _, d in folders(workspace))
    if not model and not have_knowledge:
        return [], []
    lines = ["", "## Background knowledge (not evidence)", "",
             "How the system's parts behave, from knowledge documents kept apart from the discovery data. It is NOT "
             "evidence of the current state and is not in the evidence matrix:",
             "- A K- passage may explain an evidenced observation in a narrative block (Drawbridge Impact): give it its "
             "own fact citing only its K- ID with basis {background}, next to the E- fact it explains.",
             "- Never cite a K- ID in a Current State, a Rating, a table row or a findings bullet.",
             "- A \"Look for\" line has no ID and is not citable: state it only from an E- evidence row, otherwise "
             "write Unknown."]
    if model:
        lines += ["", "### System model (reviewed by the project owner: what to look for, not citable)", ""]
        lines += [f"- {f['function']}: delivered by {f['delivered_by']}, depends on {f['depends_on']}. "
                  f"IT dependencies: {f['it_dependencies']}." for f in model.get("functions", [])]
        lines += [f"- Open question for this section (write it as an Unknown line if the evidence does not answer it): "
                  f"{q}" for q in open_questions(model, key, questions)]
        lines += [f"- Look for: {c}" for c in dom.get("checks", [])]
    cite: list[str] = []
    if have_knowledge and workspace:
        must = [topic] + list(dom.get("terms", []))
        queries = [f"{topic} {scope_text} {' '.join(dom.get('checks', []))} {' '.join(dom.get('terms', []))}"]
        queries += [f"{topic} {q['text']}" for q in questions if q["kind"] == "narrative"]
        seen: dict[str, dict] = {}
        for qtext in queries:
            for p in search(workspace, qtext, limit=MAX_PASSAGES, must=must):
                seen.setdefault(p["kid"], p)
        picked = sorted(seen.values(), key=lambda p: p["score"])[:MAX_PASSAGES]
        if picked:
            lines += ["", "### Knowledge passages", ""]
        for p in picked:
            text = p["text"] if len(p["text"]) <= EXCERPT else p["text"][:EXCERPT].rsplit(" ", 1)[0] + " ..."
            if p["type"] == "derived" or p["names_system"]:
                if sum(1 for x in lines if x.startswith("- Look for (second-hand")) >= MAX_DERIVED:
                    continue
                lines.append(f"- Look for (second-hand, from {p['title']}, not citable: find the primary evidence): {text}")
            else:
                cite.append(p["kid"])
                lines.append(f"- {p['kid']} [{_label(p)}]: {text}")
    return lines, cite


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("build")
    p.add_argument("--workspace", type=Path, required=True)
    p.add_argument("--force", action="store_true")
    p = sub.add_parser("search")
    p.add_argument("--workspace", type=Path, required=True)
    p.add_argument("query")
    p.add_argument("--limit", type=int, default=5)
    p = sub.add_parser("card")
    p.add_argument("--workspace", type=Path, required=True)
    p.add_argument("key")
    p.add_argument("--topic", default="")
    a = ap.parse_args(argv)
    if a.cmd == "build":
        print(json.dumps(build(a.workspace, a.force), indent=1))
    elif a.cmd == "search":
        for r in search(a.workspace, a.query, a.limit):
            print(f"{r['kid']} {r['score']:.2f} [{_label(r)}] {r['text'][:160]}")
    else:
        lines, ids = card_section(a.key, a.topic or a.key, [], "", a.workspace)
        print("\n".join(lines) + f"\n\n(citable as background: {', '.join(ids)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
