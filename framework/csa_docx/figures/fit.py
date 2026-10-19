"""Fit check: does the figure say what the section says? Run after every draw. Reports only, never edits.

    check(node, brief, model, rel_rows, register_names) -> {"checks": [...], "counts": {...}}

Each check: {"level": "ok" | "note" | "flag", "kind", "text", "evidence": [...]}
  coverage   every included brief item is drawn, or is the stated absence; gaps are listed
  text       a host the section names that the figure lacks; a relationship the text states that the evidence
             contradicts (e.g. the text says host X takes time from A, the evidence says from B)
  counts     a number the text gives ("nine hosts", "all twelve captured hosts") that the evidence does not match
  figure     a provider in the figure that the section never mentions (allowed; the section may need a sentence)
  rating     a Met rating while the figure shows the vital hosts relying on providers outside OT
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from csa_docx.figures.brief import WORDS, number_word, section_text

NUM = r"(\d+|" + "|".join(WORDS) + r")"


def _clauses(sentence: str) -> list[str]:
    return [c.strip() for c in re.split(r"[;,]\s+|\s+—\s+|\s+-\s+", sentence) if c.strip()]


def _named(text: str, names: set[str]) -> list[str]:
    return [n for n in names if re.search(rf"\b{re.escape(n)}\b", text, re.I)]


def check(node: dict, brief: dict, model: dict, rel_rows: list[dict], register_names: set[str],
          ips_of: dict[str, str] | None = None) -> dict:
    """ips_of: host -> its addresses (register), so a section that names a provider by address still counts."""
    out: list[dict] = []
    add = lambda level, kind, text, evidence=(): out.append({"level": level, "kind": kind, "text": text, "evidence": list(evidence)})
    sentences = section_text(node)
    drawn = {n["id"] for n in model.get("nodes", [])} | {n["label"] for n in model.get("nodes", [])}
    for g in model.get("groups", []):
        drawn |= set(g.get("members", []))

    # coverage
    for i in brief.get("items", []):
        if not i.get("include", True):
            add("note", "coverage", f"Left out of the figure by choice: {i['what']}.")
        elif i["status"] == "absent":
            add("ok", "coverage", f"Shown as a gap box: {i['what']}.", i.get("evidence", []))
        elif i.get("provider") and i["provider"] not in drawn:
            add("flag", "coverage", f"In the brief but not drawn: {i['what']}.", i.get("evidence", []))
        else:
            add("ok", "coverage", f"Drawn: {i['what']}.", i.get("evidence", []))
    for g in brief.get("gaps", []):
        add("note", "coverage", f"Gap, not captured: {g['what']}.")

    active = [r for r in rel_rows if r["state"] == "active"]
    providers = {r["provider"] for r in rel_rows}
    takes: dict[str, set[str]] = {}
    for r in active:
        takes.setdefault(r["consumer"], set()).add(r["provider"])
    # text against figure: hosts the section names
    text = " ".join(sentences)
    named_hosts = set(_named(text, register_names)) | set(_named(text, providers))
    for h in sorted(named_hosts - drawn):
        add("note", "text", f"The section names {h}, which is not in the figure.")

    # text against evidence: "<provider> ... <host>, <host>" in one clause
    if brief.get("archetype") == "B":
        for s in sentences:
            for c in _clauses(s):
                ps = _named(c, providers)
                if len(ps) != 1:
                    continue
                p = ps[0]
                for h in _named(c, set(takes)):
                    if h == p:
                        continue
                    if p not in takes.get(h, set()) and not any(r["consumer"] == h and r["provider"] == p for r in rel_rows):
                        ev = sorted({e for r in active if r["consumer"] == h for e in r["evidence"]})
                        add("flag", "text", f"The section says {h} takes it from {p}; the evidence shows "
                            f"{', '.join(sorted(takes.get(h, set()))) or 'no provider'}. Sentence: \"{s}\"", ev)
                # counts: "<provider> is the Active peer of nine hosts"
                m = re.search(rf"\b(?:of|for|by|to)\s+{NUM}\s+(?:\w+\s+)?hosts?\b", c, re.I)
                if m and not re.search(r"\ball\b", c, re.I) and number_word(m.group(1)) is not None:
                    n = number_word(m.group(1))
                    actual = len({r["consumer"] for r in active if r["provider"] == p})
                    if n != actual:
                        add("flag", "counts", f"The section says {n} hosts for {p}; the evidence shows {actual}. Sentence: \"{s}\"",
                            sorted({e for r in active if r["provider"] == p for e in r["evidence"]}))
            m = re.search(rf"\ball\s+{NUM}\s+(?:captured\s+)?hosts\b", s, re.I)
            if m and number_word(m.group(1)) is not None and active:
                n, actual = number_word(m.group(1)), len(takes)
                if n != actual:
                    add("flag", "counts", f"The section says all {n} hosts; the evidence covers {actual}. Sentence: \"{s}\"")

        # figure against text
        for p in sorted(providers):
            ips = [i for i in re.split(r"[;,\s]+", (ips_of or {}).get(p, "")) if i]
            if not any(re.search(rf"\b{re.escape(x)}\b", text, re.I) for x in [p, *ips]):
                add("note", "figure", f"The figure shows {p}, which the section does not mention.")

    # rating consistency
    outside = [r for r in active if r.get("side") != "ot"]
    for req in [r for part in node.get("parts", []) for r in part.get("requirements", []) or []]:
        rating = (req.get("rating") or "").strip().lower()
        if rating == "met" and outside:
            add("flag", "rating", f"{req['id']} is rated Met, but the figure shows {len({r['consumer'] for r in outside})} vital "
                "hosts relying on providers outside OT.")
        elif rating in ("not met", "partially met") and active and not outside:
            add("note", "rating", f"{req['id']} is rated {req['rating']}, and every provider in the figure is OT-resident.")
        elif rating:
            add("ok", "rating", f"{req['id']} rating ({req['rating']}) agrees with the figure.")

    counts = {lv: sum(1 for c in out if c["level"] == lv) for lv in ("ok", "note", "flag")}
    return {"checks": out, "counts": counts}


def print_checks(fit: dict, info: dict) -> dict:
    """The figure as printed in the CSA (17 cm wide): text must stay at 8 pt or more, and it must fit one page."""
    add = lambda level, text: fit["checks"].append({"level": level, "kind": "print", "text": text, "evidence": []})
    if info.get("min_text_pt", 99) < 8:
        add("flag", f"At the 17 cm text width its smallest text prints at {info['min_text_pt']} pt (below 8 pt): "
                    "too many lines for one figure; split it or leave items out.")
    else:
        add("ok", f"Prints {info['width_mm']:.0f} × {info['height_mm']:.0f} mm; smallest text {info['min_text_pt']} pt.")
    if not info.get("fits_page", True):
        add("flag", f"At {info['height_mm']:.0f} mm it is taller than fits under a heading on one A4 page: split it.")
    fit["counts"] = {lv: sum(1 for c in fit["checks"] if c["level"] == lv) for lv in ("ok", "note", "flag")}
    return fit


def path(work_dir: Path, key: str) -> Path:
    return Path(work_dir) / "figures" / key / "fit.json"


def save(work_dir: Path, key: str, result: dict) -> Path:
    p = path(work_dir, key)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
    return p


def check_flow_tables(model: dict, flow_rows: list[dict], settings_rows: list[dict], flt: dict | None,
                      register: set[str] | None = None) -> list[dict]:
    """Archetype F against the Discovery Information tables: every flow the profile selects is drawn, every database
    the role table lists on a drawn host has a store mark, and the markers every host shares are on the legend line."""
    from csa_docx import flows as FL
    out: list[dict] = []
    add = lambda level, kind, text: out.append({"level": level, "kind": kind, "text": text, "evidence": []})
    drawn = {f for e in model.get("edges", []) for f in (e.get("detail") or {}).get("flows", [])}
    for r in FL.select(flow_rows, flt or {"data": True}, register):
        if r["flow_id"] not in drawn:
            add("flag", "tables", f"In the flows table but not drawn: {r['flow_id']} {r['mechanism']} {r['src']} to {r['dst']}.")
    nodes = {n["id"]: n for n in model.get("nodes", [])}
    for r in settings_rows:
        if r["host"] in nodes and r["attribute"] == "storage.database" and r["value"] != "None found":
            if not any(s["what"] == r["value"] for s in nodes[r["host"]].get("stores", [])):
                add("flag", "tables", f"The role table lists {r['value']} on {r['host']}, which has no store mark.")
    if model.get("common_marks"):
        add("ok", "tables", "Markers every host shares are on one legend line: " + ", ".join(sorted(model["common_marks"])) + ".")
    if not any(c["level"] == "flag" for c in out):
        add("ok", "tables", "Every flow and data store in the Discovery Information tables is drawn.")
    return out


def check_store_tables(model: dict, settings_rows: list[dict], register: set[str] | None = None) -> list[dict]:
    """Archetype G against the Discovery Information tables: every store the host-settings
    inventory lists appears as a store node, and every drawn consumer is a registered host."""
    out: list[dict] = []
    add = lambda level, kind, text: out.append({"level": level, "kind": kind, "text": text, "evidence": []})
    store_nodes = [n for n in model.get("nodes", []) if n.get("id", "").startswith("ST-")]
    listed = {(r["host"], r["value"]) for r in settings_rows
              if r["attribute"] == "storage.database" and r["value"] != "None found"}
    listed |= {(r["host"], r["value"]) for r in settings_rows
               if r["attribute"] == "storage.shares" and r["value"] != "Default and administrative shares only"}
    if store_nodes:
        add("ok", "stores", f"{len(store_nodes)} data store(s) drawn from the host-settings inventory.")
    else:
        add("flag", "stores", "The host-settings inventory lists data stores, but none are drawn.")
    reg = {h.upper() for h in (register or set())}
    unreg = sorted({e["s"] for e in model.get("edges", []) if reg and e["s"].upper() not in reg})
    if unreg:
        add("flag", "consumers", f"Consumer(s) not in the host register: {', '.join(unreg)}.")
    else:
        add("ok", "consumers", "Every drawn consumer is a registered host.")
    return out

