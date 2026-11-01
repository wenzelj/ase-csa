"""S494: the card shows the identity of every host named as a source or peer."""
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from csa_docx import section_card, topic_frames  # noqa: E402

Q1 = "Which time source does each host follow?"
Q3 = "Which time servers are in use, and which side of OT is each server on?"
FRAME = {"slots": [{"id": "S1", "question": Q1, "source": {"settings": ["time.source"]}},
                   {"id": "S3", "question": Q3, "source": {"flows": {}}}]}
FR = {"heading": "Time Synchronisation", "slots": [{"id": "S1", "question": Q1}, {"id": "S3", "question": Q3}]}


def _csv(path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def _facts(ws, rows):
    _csv(ws / "csa-work" / "hosts" / "host_facts.csv", ["host", "attribute", "value", "listed_as"], rows)


def _ws(tmp_path, sources, with_peer_facts=True):
    hosts = tmp_path / "csa-work" / "hosts"
    _csv(hosts / "hosts.csv", ["host", "role", "site", "ips", "fqdn"], [
        {"host": "ROTPRDSRV122", "role": "Domain Controller", "site": "Rockhampton", "ips": "10.1.1.1", "fqdn": ""},
        {"host": "HOSTAA101", "role": "Server", "site": "Mackay", "ips": "10.1.1.9", "fqdn": ""}])
    _csv(hosts / "host_settings.csv", ["host", "topic", "attribute", "value", "capture", "source", "excerpt"],
         [{"host": "HOSTAA101", "topic": "time", "attribute": "time.source", "value": sources,
           "capture": "", "source": "x line 1", "excerpt": ""}])
    _facts(tmp_path, [
        {"host": "ROTPRDSRV122", "attribute": "identities: Role", "value": "Domain Controller", "listed_as": "Host"},
        {"host": "ROTPRDSRV122", "attribute": "identities: Hosted In", "value": "OT (Rockhampton)", "listed_as": "Host"},
    ] if with_peer_facts else [])
    return tmp_path


def _run(monkeypatch, ws):
    monkeypatch.setattr(topic_frames, "frame_for", lambda heading: FRAME)
    return section_card.peer_identity(FR, ws)


def test_named_host_carries_role_and_zone(tmp_path, monkeypatch):
    res = _run(monkeypatch, _ws(tmp_path, "ROTPRDSRV122.internal.qr.com.au"))
    h = res["hosts"][0]
    assert (h["host"], h["role"], h["how"]) == ("ROTPRDSRV122", "Domain Controller", "confirmed by Wenzel")
    assert "OT (Rockhampton)" in h["zone"] and h["site"] == "Rockhampton"
    assert any("ROTPRDSRV122: role Domain Controller; zone OT (Rockhampton)" in x for x in res["lines"])


def test_host_without_register_entry_is_not_recorded(tmp_path, monkeypatch):
    res = _run(monkeypatch, _ws(tmp_path, "ROTPRDSRV122, IPTPRDSRV224"))
    by = {h["host"]: h for h in res["hosts"]}
    assert by["IPTPRDSRV224"]["how"] == "not recorded" and by["IPTPRDSRV224"]["zone"] == "zone not recorded"
    assert res["open"] == ["IPTPRDSRV224"] and res["answered"] == []
    assert any("Discovery Required" in x for x in res["lines"])


def test_zone_question_answered_when_every_host_known(tmp_path, monkeypatch):
    res = _run(monkeypatch, _ws(tmp_path, "ROTPRDSRV122"))
    assert res["answered"] == ["S3"] and res["open"] == []
    assert any("Do not write a QUESTION:" in x for x in res["lines"])


def test_assumption_note_shown_as_assumed(tmp_path, monkeypatch):
    ws = _ws(tmp_path, "ROTPRDSRV122")
    _facts(ws, [
        {"host": "ROTPRDSRV122", "attribute": "identities: Hosted In", "value": "OT (Mackay)", "listed_as": "Host"},
        {"host": "ROTPRDSRV122", "attribute": "identities: Note",
         "value": "assumed same as ROTPRDSRV122 (Wenzel 01/11/2026)", "listed_as": "Host"}])
    assert _run(monkeypatch, ws)["hosts"][0]["how"].startswith("assumed: assumed same as")
