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
import sqlite3
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


def connected_devices(work: Path, net: dict[str, Any]) -> list[dict[str, Any]]:
    """Confirmed connected devices seen as peers, each with its raw address, the connections the captures
    recorded to or from it, and the DNS/time servers hosts are *configured* to use that it owns. The two
    are kept apart: an observed connection is not a configured service, and neither is a dependency."""
    services = _csv(work / "hosts" / "host_services.csv")
    out = []
    for n in net["nodes"]:
        d = n.get("device")
        if not d:
            continue
        address = n["id"]
        out.append({
            **d, "address": address,
            "observed_connections": [{"src": e["s"], "dst": e["t"], "port": e["port"], "processes": e["procs"],
                                      "evidence_ids": e["ids"], "established": e["est"]}
                                     for e in net["edges"] if address in (e["s"], e["t"])],
            "configured_services": [{"client_host": s.get("client_host", ""), "service": s.get("service", ""),
                                     "preference": s.get("preference", ""), "source": s.get("source", "")}
                                    for s in services if (s.get("server_ip") or "").strip() == address],
        })
    return out


def _network_build(work: Path, agents: Path, view: str, application_key: str | None, project: dict[str, str]) -> dict[str, Any]:
    """Keep older test doubles and V1 extensions callable while using scoped arguments in production."""
    try:
        return network.build(work, agents, view=view, application_key=application_key or project.get("key"))
    except TypeError as exc:
        if "unexpected keyword argument" not in str(exc):
            raise
        return network.build(work, agents)


def build(project: dict[str, str], agents: Path, document: Path | None,
          view: str = "global", application_key: str | None = None) -> dict[str, Any]:
    work = Path(project["work_dir"]).expanduser()
    net = _network_build(work, agents, view, application_key, project)
    v2 = work.name == "csa-work-v2"
    if v2:
        with sqlite3.connect(f"file:{work / 'csa.sqlite'}?mode=ro", uri=True) as con:
            con.row_factory = sqlite3.Row
            host_details = {row["name"]: dict(row) for row in con.execute(
                "SELECT name, role, site, os, status FROM host")}
            matrix = {row["id"]: {"evidence_id": row["id"], "csa_area": row["area"],
                                  "status": row["status"], "claim": row["claim"],
                                  "source_title": row["source_title"], "page_or_location": row["page_or_location"],
                                  "evidence_excerpt": row["excerpt"], "confidence": row["confidence"],
                                  "gap_or_action": row["gap_or_action"], "review_state": row["review_state"]}
                      for row in con.execute("SELECT * FROM evidence")}
            scope = {row["host_name"]: row["membership"] for row in con.execute(
                "SELECT host_name, membership FROM application_scope WHERE active=1 AND review_state != 'rejected'")}
        register = {node["id"]: {"host": node["id"], "role": node["role"], "site": node["site"],
                                  "ips": node["ips"], "os": host_details.get(node["id"], {}).get("os", ""),
                                  "status": host_details.get(node["id"], {}).get("status", ""), "in_scope": "yes"}
                    for node in net["nodes"] if node.get("listed")}
    else:
        register = {r["host"]: r for r in _csv(work / "hosts" / "hosts.csv")}
        matrix = {r["evidence_id"]: r for r in _csv(work / "evidence-matrix.csv")}

    facts: dict[str, list[dict]] = {}
    for r in ([] if v2 else _csv(work / "hosts" / "host_facts.csv")):
        facts.setdefault(r["host"], []).append({"attribute": r.get("attribute", ""), "value": r.get("value", ""),
                                                "source": r.get("source", ""), "line": r.get("line", "")})
    ev_by_host: dict[str, list[str]] = {}
    for r in ([] if v2 else _csv(work / "hosts" / "evidence_hosts.csv")):
        if (r.get("review_state") or "").lower() == "rejected":      # rejected rows are not a host's evidence
            continue
        for h in (r.get("hosts") or "").split(";"):
            if h.strip():
                ev_by_host.setdefault(h.strip(), []).append(r["evidence_id"])
    if v2:
        for edge in net["edges"]:
            for host in (edge["s"], edge["t"]):
                ev_by_host.setdefault(host, []).extend(edge["ids"])
        for host in register:
            for row in matrix.values():
                text = f"{row.get('claim', '')} {row.get('source_title', '')}"
                if re.search(rf"\b{re.escape(host)}\b", text, re.I):
                    ev_by_host.setdefault(host, []).append(row["evidence_id"])

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
        if v2:
            detail = host_details.get(h, {})
            facts[h] = [{"attribute": key, "value": str(detail.get(key) or ""), "source": "csa.sqlite host", "line": ""}
                        for key in ("role", "site", "os", "status") if detail.get(key)]
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

    if v2:
        devices = []
        for node in net["nodes"]:
            if scope.get(node["id"]) != "peer":
                continue
            links = [edge for edge in net["edges"] if node["id"] in (edge["s"], edge["t"])]
            devices.append({"id": node["id"], "name": node["id"], "kind": "connected_device", "active": True,
                            "type": "host", "role": node.get("role", ""), "site": node.get("site", ""),
                            "aliases": [x for x in [node.get("ips", ""), node["id"]] if x],
                            "connected_application_hosts": sorted({endpoint for edge in links for endpoint in (edge["s"], edge["t"])
                                                                      if endpoint != node["id"] and scope.get(endpoint) == "owned"}),
                            "ports": sorted({str(edge.get("port", "")) for edge in links if edge.get("port")}),
                            "evidence": sorted({evidence_id for edge in links for evidence_id in edge.get("ids", [])})})
    else:
        devices = connected_devices(work, net)
    return {"application": spec.get("application") or project.get("label", ""), "hosts": hosts, "edges": net["edges"],
            "devices": devices,
            "components": spec.get("components", []), "dependencies": spec.get("dependencies", []),
            "journeys": spec.get("journeys", []), "issues": issues, "evidence": evidence, "document": doc_state,
            "sources": {"links": net["source"], "journeys": str(spec_path.name) if spec else "",
                        "facts": "csa.sqlite host" if v2 else "hosts/host_facts.csv",
                        "evidence": "csa.sqlite evidence" if v2 else "evidence-matrix.csv, hosts/evidence_hosts.csv"},
            "view": net.get("view", view), "application_key": net.get("application_key", application_key or project.get("key"))}


def diagrams(project: dict[str, str], agents: Path, view: str = "global",
             application_key: str | None = None) -> dict[str, Any]:
    """The project's technical diagrams (system overview + one numbered data flow per journey) as SVG plus their
    models, from csa_docx.techdiagram: the same drawings `csa system-diagram` writes for the CSA figures."""
    work = Path(project["work_dir"]).expanduser()
    net = _network_build(work, agents, view, application_key, project)
    if not net["nodes"]:
        return {"application": project.get("label", ""), "diagrams": []}
    from csa_docx.techdiagram import diagrams as build_diagrams
    spec_path = work / "explorer" / "journeys.json"
    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8")) if spec_path.is_file() else {}
    except json.JSONDecodeError:
        spec = {}
    app = spec.get("application") or project.get("label", "")
    return {"application": app, "diagrams": build_diagrams(net, spec, project.get("key", ""), app),
            "view": net.get("view", view), "application_key": net.get("application_key", application_key or project.get("key"))}
