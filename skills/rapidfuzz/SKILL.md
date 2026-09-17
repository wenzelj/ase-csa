---
name: rapidfuzz
description: "Use when matching or scoring similarity between strings in Python — fuzzy lookup, deduplication, best-match selection, or a tolerant fallback when exact/prefix string matching fails. Covers rapidfuzz's scorers, process.extract, and safe fallback design (difflib)."
---

# rapidfuzz

## What it is

rapidfuzz is a fast string-matching/fuzzy-search library for Python (MIT license, `github.com/rapidfuzz/RapidFuzz`, `pip install rapidfuzz`). It's a drop-in-shaped successor to the older `fuzzywuzzy`/`python-Levenshtein` combo, implemented in C++ with Python bindings — same scoring API (`ratio`, `partial_ratio`, `token_sort_ratio`, ...), no GPL dependency, and much faster on large candidate sets.

Because it's a compiled extension, wheels are built per platform/Python-ABI (e.g. `rapidfuzz-<ver>-cp312-cp312-manylinux_x86_64.whl`, `...-cp314-cp314-macosx_11_0_arm64.whl`). When vendoring by unzipping a wheel rather than `pip install`, you must fetch the wheel matching the *target* interpreter/OS/arch — unlike a pure-Python package such as mistune, one wheel does not run everywhere. (In practice the compiled extension can still import successfully on an unrelated platform if the wheel happens to be compatible at the binary level — but don't rely on that; treat cross-platform vendoring of rapidfuzz as needing the matching wheel.)

## Core usage

```python
from rapidfuzz import fuzz, process

fuzz.ratio("Time Source", "Time Sources")        # 95.65 -> near-identical
fuzz.ratio("Time Domain", "Source Namespace")     # 29.6  -> unrelated

# Best match (and score) out of a list of candidates:
process.extractOne("Time Sources", ["Time Source", "Log Retention", "NTP Servers"])
# -> ("Time Source", 95.65, 0)
```

`fuzz.ratio` is Levenshtein-based normalized similarity (0–100). Other scorers exist for different needs: `fuzz.partial_ratio` (best matching substring — use when one string may be a fragment of the other), `fuzz.token_sort_ratio`/`token_set_ratio` (word-order- and duplicate-word-insensitive — use for reordered phrases), `fuzz.WRatio` (a weighted combination, `process`'s default). `process.extract`/`extractOne` run a scorer against a whole candidate list and return the best match(es) with score and index, which is almost always better than calling `fuzz.ratio` in a manual loop.

## Practical tips

- Fuzzy matching is a **fallback tier**, not a replacement for exact matching: try exact match first, then prefix/substring match, and only fall back to a fuzzy scorer when those find nothing. Fuzzy matching alone is prone to false positives on short strings or datasets with many similarly-shaped labels.
- When using a fuzzy fallback to pick "the" match, require both (a) a minimum absolute score (a threshold, e.g. ≥ 85) and (b) a minimum margin over the second-best candidate's score (e.g. ≥ 10 points). Threshold alone still accepts an ambiguous near-tie; margin alone still accepts a confidently-wrong low-quality match when nothing better exists.
- Always guard the import and have a stdlib fallback, since rapidfuzz is a compiled dependency that may not be installable/vendorable in every target environment:

```python
try:
    from rapidfuzz import fuzz as _fuzz
    def similarity(a: str, b: str) -> float:
        return _fuzz.ratio(a, b)
except ImportError:
    from difflib import SequenceMatcher
    def similarity(a: str, b: str) -> float:
        return SequenceMatcher(None, a, b).ratio() * 100
```

  `difflib.SequenceMatcher.ratio()` (stdlib, no install needed) returns 0–1 rather than 0–100; multiply by 100 to keep a single threshold/margin scale across both code paths. Scores from the two aren't numerically identical (different algorithms — Levenshtein-derived vs. longest-matching-block-derived) but are close enough to share the same threshold/margin constants in practice.
- Normalize case/whitespace (and, if relevant, spelling variants like British/American) on both sides *before* scoring — a fuzzy scorer will paper over small differences but still penalizes systematic ones, and normalizing first keeps the threshold meaningful.
- For matching one string against many candidates, prefer `process.extractOne(query, choices)` over a hand-written loop calling `fuzz.ratio` — it's implemented in C++ and also exposes `score_cutoff` to skip building results below a floor.

## Worked example: label lookup with an exact-then-fuzzy fallback

```python
def find_by_label(target_label: str, rows: list[dict], threshold=85, margin=10):
    # 1. exact match
    exact = [r for r in rows if r["label"] == target_label]
    if len(exact) == 1:
        return exact[0]

    # 2. prefix match
    prefix = [r for r in rows if r["label"].startswith(target_label)]
    if len(prefix) == 1:
        return prefix[0]

    # 3. fuzzy fallback, only when exact/prefix found nothing
    scored = sorted(
        ((similarity(target_label, r["label"]), r) for r in rows),
        key=lambda x: x[0],
        reverse=True,
    )
    if not scored:
        return None
    best_score, best_row = scored[0]
    second_score = scored[1][0] if len(scored) > 1 else 0
    if best_score >= threshold and (best_score - second_score) >= margin:
        return best_row
    return None  # ambiguous or no good match -> let the caller treat this as "not found"
```
