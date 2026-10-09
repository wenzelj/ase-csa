"""System explorer for the Evidence Workspace: hosts, captured links, per-host facts and evidence, what the CSA
says about each host, and evidence-backed operational journeys.

Everything is read from the project's own files; nothing is inferred here:
- host register and captured links come from network.build (evidence matrix + hosts/hosts.csv);
- per-host facts from hosts/host_facts.csv, per-host evidence from hosts/evidence_hosts.csv,
  the host card from hosts/cards/<host>.md;
- CSA mentions are paragraphs and table rows of the working DOCX that name the host;
- journeys come from <work_dir>/explorer/journeys.json, written per project. Each journey is validated:
  every cited evidence ID must exist in the matrix and every animated transition must match a captured link.
"""
from __future__ import annotations

import csv
import json
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from . import network

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_PLACEHOLDER = re.compile(r"^\[[^\]]*\]$")
_cache: dict[tuple, list[dict]] = {}


def _csv(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _text(el: ET.Element) -> str:
    return "".join(t.text or "" for t in el.iter(W + "t")).strip()      # w:delText (deleted runs) is excluded


def document_blocks(path: Path) -> list[dict]:
    """Paragraphs and table rows of a DOCX with the heading they sit under (cached by path and mtime)."""
    key = (str(path), path.stat().st_mtime)
    if key in _cache:
        return _cache[key]
    with zipfile.ZipFile(path) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))
    body = root.find(W + "body")
    blocks: list[dict] = []
    h1 = h2 = ""
    for el in list(body) if body is not None else []:
        if el.tag == W + "p":
            style = el.find(f"{W}pPr/{W}pStyle")
            sid = style.get(W + "val", "") if style is not None else ""
            text = _text(el)
            if not text:
                continue
            m = re.match(r"Heading(\d)", sid)
            if m:
                if m.group(1) == "1":
                    h1, h2 = text, ""
                else:
                    h2 = text if m.group(1) == "2" else h2
                continue
            blocks.append({"section": " › ".join(x for x in (h1, h2) if x), "kind": "paragraph", "text": text})
        elif el.tag == W + "tbl":
            for tr in el.iter(W + "tr"):
                cells: list[str] = []
                for tc in tr.findall(W + "tc"):
                    value = _text(tc)
                    if not cells or cells[-1] != value:
                        cells.append(value)
                if any(cells) and not all(_PLACEHOLDER.match(c or "[]") for c in cells):
                    blocks.append({"section": " › ".join(x for x in (h1, h2) if x), "kind": "table row", "text": " | ".join(cells)})
    _cache.clear()
    _cache[key] = blocks
    return blocks


def mentions(blocks: list[dict], host: str, limit: int = 40) -> list[dict]:
    pattern = re.compile(rf"\b{re.escape(host)}\b", re.I)
    return [b for b in blocks if pattern.search(b["text"])][:limit]


def _card(work: Path, host: str) -> str:
    path = work / "hosts" / "cards" / f"{host}.md"
    if not path.is_file() or not re.fullmatch(r"[A-Za-z0-9_.-]+", host):
        return ""
    return path.read_text(encoding="utf-8", errors="replace")[:20000]


def _evidence_view(row: dict) -> dict:
    keep = ("evidence_id", "csa_area", "status", "claim", "source_title", "source_version", "page_or_location",
            "evidence_excerpt", "inference_reason", "confidence", "gap_or_action", "review_state")
    return {k: row.get(k, "") for k in keep}


def _validate(spec: dict, matrix: dict[str, dict], edges: set[tuple], hosts: set[str]) -> list[str]:
    issues: list[str] = []

    def cite(where: str, ids: list[str]) -> None:
        for i in ids or []:
            if i not in matrix:
                issues.append(f"{where}: evidence {i} is not in the evidence matrix")

    comps = {c["id"]: c for c in spec.get("components", [])}
    for c in comps.values():
        cite(f"component {c['id']}", c.get("evidence"))
        if c.get("host") and c["host"] not in hosts:
            issues.append(f"component {c['id']}: host {c['host']} is not in the host register")
    for d in spec.get("dependencies", []):
        cite(f"dependency {d['id']}", d.get("evidence"))
    for j in spec.get("journeys", []):
        cite(f"journey {j['id']}", j.get("evidence"))
        trans = {t["id"]: t for t in j.get("transitions", [])}
        for t in trans.values():
            cite(f"transition {t['id']}", t.get("evidence"))
            for end in (t.get("from"), t.get("to")):
                if end not in comps:
                    issues.append(f"transition {t['id']}: unknown component {end}")
            e = t.get("edge")
            if t.get("status") in ("verified", "inferred"):
                if not e:
                    issues.append(f"transition {t['id']}: marked {t['status']} but has no captured link")
                elif (e["s"], e["t"], str(e["port"])) not in edges:
                    issues.append(f"transition {t['id']}: no captured link {e['s']} -> {e['t']} port {e['port']}")
        for s in j.get("steps", []):
            cite(f"step {s['id']}", s.get("evidence"))
            if s.get("component") and s["component"] not in comps:
                issues.append(f"step {s['id']}: unknown component {s['component']}")
            for tid in ([s["transition"]] if isinstance(s.get("transition"), str) else s.get("transition") or []):
                if tid not in trans:
                    issues.append(f"step {s['id']}: unknown transition {tid}")
    return issues


def build(project: dict[str, str], agents: Path, document: Path | None) -> dict[str, Any]:
    work = Path(project["work_dir"]).expanduser()
    net = network.build(work, agents)
    register = {r["host"]: r for r in _csv(work / "hosts" / "hosts.csv")}
    matrix = {r["evidence_id"]: r for r in _csv(work / "evidence-matrix.csv")}

    facts: dict[str, list[dict]] = {}
    for r in _csv(work / "hosts" / "host_facts.csv"):
        facts.setdefault(r["host"], []).append({"attribute": r.get("attribute", ""), "value": r.get("value", ""),
                                                "source": r.get("source", ""), "line": r.get("line", "")})
    ev_by_host: dict[str, list[str]] = {}
    for r in _csv(work / "hosts" / "evidence_hosts.csv"):
        for h in (r.get("hosts") or "").split(";"):
            if h.strip():
                ev_by_host.setdefault(h.strip(), []).append(r["evidence_id"])

    blocks: list[dict] = []
    doc_state = {"state": "missing", "name": ""}
    if document and document.is_file():
        try:
            blocks = document_blocks(document)
            doc_state = {"state": "ready", "name": document.name}
        except (zipfile.BadZipFile, ET.ParseError, KeyError, OSError) as exc:
            doc_state = {"state": "unreadable", "name": document.name, "reason": str(exc)}

    hosts = []
    for n in net["nodes"]:
        h = n["id"]
        r = register.get(h, {})
        hosts.append({**n, "system": r.get("system", ""), "in_scope": r.get("in_scope", ""), "fqdn": r.get("fqdn", ""),
                      "ou": r.get("ou", ""), "capture": r.get("capture", ""), "listening": r.get("listening", ""),
                      "role_source": r.get("role_source", ""), "site_source": r.get("site_source", ""),
                      "conflicts": r.get("conflicts", ""), "facts": facts.get(h, []),
                      "evidence_ids": sorted(set(ev_by_host.get(h, []))), "csa": mentions(blocks, h) if blocks else [],
                      "card": _card(work, h)})

    spec_path = work / "explorer" / "journeys.json"
    spec: dict = {}
    issues: list[str] = []
    if spec_path.is_file():
        try:
            spec = json.loads(spec_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            issues.append(f"journeys.json is not valid JSON: {exc}")
    edge_keys = {(e["s"], e["t"], str(e["port"])) for e in net["edges"]}
    if spec:
        issues += _validate(spec, matrix, edge_keys, {h["id"] for h in hosts} | set(register))

    cited: set[str] = set()

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for k, v in value.items():
                if k == "evidence" and isinstance(v, list):
                    cited.update(v)
                else:
                    walk(v)
        elif isinstance(value, list):
            for v in value:
                walk(v)
    walk(spec)
    for h in hosts:
        cited.update(h["evidence_ids"])
    evidence = {i: _evidence_view(matrix[i]) for i in sorted(cited) if i in matrix}

    return {"application": spec.get("application") or project.get("label", ""), "hosts": hosts, "edges": net["edges"],
            "components": spec.get("components", []), "dependencies": spec.get("dependencies", []),
            "journeys": spec.get("journeys", []), "issues": issues, "evidence": evidence, "document": doc_state,
            "sources": {"links": net["source"], "journeys": str(spec_path.name) if spec else "",
                        "facts": "hosts/host_facts.csv", "evidence": "evidence-matrix.csv, hosts/evidence_hosts.csv"}}
