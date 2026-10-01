"""One parser for the CSA section scope map (`section-scope.md`).

Reads each requirement domain (`### 3.4 Time Synchronisation`) with its requirements, must-explain,
owns and not-here lines, its legacy headings and its signal terms. The conversion uses it to map old
headings to template subsections and to write section briefs.
"""

from __future__ import annotations

import re
from pathlib import Path

SCOPE_FILE = (Path(__file__).resolve().parents[2] / "skills" / "csa-quality-review"
              / "references" / "section-scope.md")

_DOMAIN_RE = re.compile(r"^###\s+(\d+\.\d+)\s+(.+?)\s*$")
_FIELD_RE = re.compile(r"^-\s+\*\*([^*:]+):\*\*\s*(.*)$")
_REQ_ID_RE = re.compile(r"SEP-[A-Z]+-\d+")

_FIELDS = {
    "requirements": "requirements",
    "must explain": "must_explain",
    "owns": "owns",
    "not here": "not_here",
    "legacy headings": "legacy_headings",
    "signal terms": "signal_terms",
}


def _term_re(terms: list[str]) -> re.Pattern | None:
    if not terms:
        return None
    alts = sorted((re.escape(t).replace(r"\ ", r"[\s-]+") for t in terms), key=len, reverse=True)
    return re.compile(r"(?<![\w-])(?:" + "|".join(alts) + r")(?![\w-])", re.IGNORECASE)


def _split(value: str, lower: bool = False) -> list[str]:
    items = [s.strip() for s in value.split(",")]
    return [s.lower() if lower else s for s in items if s]


def _finish(dom: dict) -> dict:
    dom["req_ids"] = list(dict.fromkeys(_REQ_ID_RE.findall(dom["requirements"])))
    dom["legacy_headings"] = _split(dom["legacy_headings"])
    dom["signal_terms"] = _split(dom["signal_terms"], lower=True)
    dom["term_re"] = _term_re(dom["signal_terms"])
    return dom


def _key(k: str) -> tuple[int, ...]:
    return tuple(int(p) for p in k.split("."))


def load(path: Path | None = None) -> dict[str, dict]:
    """Parse every `### n.n title` block up to the next `###` or `##`. Raises ValueError if none."""
    text = Path(path or SCOPE_FILE).read_text(encoding="utf-8")
    domains: dict[str, dict] = {}
    cur: dict | None = None
    for line in text.splitlines():
        if line.startswith("## ") or line.startswith("### "):
            if cur is not None:
                domains[cur["key"]] = _finish(cur)
                cur = None
            m = _DOMAIN_RE.match(line)
            if m:
                cur = {"key": m.group(1), "title": m.group(2), "requirements": "",
                       "must_explain": "", "owns": "", "not_here": "",
                       "legacy_headings": "", "signal_terms": ""}
            continue
        if cur is None:
            continue
        f = _FIELD_RE.match(line)
        if f and f.group(1).strip().lower() in _FIELDS:
            cur[_FIELDS[f.group(1).strip().lower()]] = f.group(2).strip()
    if cur is not None:
        domains[cur["key"]] = _finish(cur)
    if not domains:
        raise ValueError(f"no domains parsed from {path or SCOPE_FILE}")
    return dict(sorted(domains.items(), key=lambda kv: _key(kv[0])))


def norm(text: str) -> str:
    """Lower-case, `&` to `and`, every non-alphanumeric run to one space, stripped."""
    text = text.lower().replace("&", " and ")
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def legacy_hosts(heading: str, domains: dict | None = None) -> list[str]:
    """Domain keys (numeric order) whose legacy headings include `heading`; the first is primary."""
    domains = domains if domains is not None else load()
    want = norm(heading)
    hits = [k for k, d in domains.items()
            if any(norm(h) == want for h in d["legacy_headings"])]
    return sorted(hits, key=_key)


def score(text: str, domain: dict) -> int:
    """Number of signal-term matches of `domain` in `text`."""
    rx = domain.get("term_re")
    return len(rx.findall(text)) if rx else 0


def best_by_terms(text: str, keys: list[str], domains: dict) -> tuple[str | None, int, bool]:
    """Highest-scoring key among `keys`, its score, and whether it tied. Ties go to the earliest key."""
    if not keys:
        return None, 0, False
    scores = [score(text, domains[k]) for k in keys]
    top = max(scores)
    return keys[scores.index(top)], top, scores.count(top) > 1
