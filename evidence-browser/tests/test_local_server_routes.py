from pathlib import Path


def test_new_application_routes_work_in_loopback_server(tmp_path, monkeypatch) -> None:
    import http.client
    import json
    import threading
    from http.server import ThreadingHTTPServer
    from urllib.parse import quote

    from backend.local_server import Handler

    agents = tmp_path / ".agents"
    (agents / "csa-context").mkdir(parents=True)
    (agents / "csa-context" / "PROJECTS.yaml").write_text("projects:\n", encoding="utf-8")
    monkeypatch.setenv("CSA_AGENTS_DIR", str(agents))
    monkeypatch.delenv("CSA_PROJECTS_FILE", raising=False)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def call(method, path, payload=None, binary=False):
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
        body = payload if binary else json.dumps(payload or {}).encode()
        connection.request(method, path, body=body,
                           headers={"Content-Type": "application/octet-stream" if binary else "application/json"})
        response = connection.getresponse()
        data = json.loads(response.read())
        status = response.status
        connection.close()
        return status, data

    try:
        assert call("GET", "/api/new-application/defaults")[1]["knowledge_name"] == "00 Knowlege"
        manifest = [
            {"path": "Discovery", "kind": "dir"},
            {"path": "00 Knowlege", "kind": "dir"},
            {"path": "Discovery/a.txt", "kind": "file", "size": 1},
        ]
        sid = call("POST", "/api/new-application/uploads", {"manifest": manifest})[1]["session_id"]
        path = f"/api/new-application/uploads/{sid}/files/{quote('Discovery/a.txt', safe='/')}?index=0"
        assert call("PUT", path, b"a", binary=True)[1]["status"] == "OK"
        assert call("PUT", path, b"a", binary=True)[1]["already_received"] is True
        assert call("POST", f"/api/new-application/uploads/{sid}/finalise")[1]["status"] == "READY"
        config = {"key": "loopback-app", "label": "Loopback App", "destination": "loopback-app"}
        assert call("POST", "/api/new-application/preview", config)[1]["status"] == "READY"
        assert call("POST", "/api/new-application/commit", {
            "session_id": sid, "config": config, "confirmed": True})[1]["status"] == "READY"
        assert (tmp_path / "loopback-app" / "Discovery" / "a.txt").read_bytes() == b"a"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_dependency_free_server_keeps_section_workflow_route_parity() -> None:
    source = (Path(__file__).resolve().parents[1] / "backend" / "local_server.py").read_text(encoding="utf-8")
    for handler in (
        "api.get_section(", "api.get_section_proposal(", "api.save_section_proposal(",
        "api.validate_section_proposal(", "api.apply_preflight(", "api.apply_section(",
        "api.get_apply_job(",
    ):
        assert handler in source
    assert 'if path.startswith("/api/")' in source
    assert 'self.send_json({"detail": "Route not found"}, 404)' in source


def test_intake_errors_route_returns_runs_and_warnings(tmp_path, monkeypatch) -> None:
    import json

    import pytest
    from fastapi import HTTPException

    from backend import app as workspace
    from backend.models import IntakeErrorsResponse

    work = tmp_path / "csa-work"
    jobs = (
        ("a", "gap_check", "failed", 1, "csa: failed to read the gap file\n"),
        ("b", "ingest", "succeeded", 0, ""),
    )
    for job_id, operation, state, code, err in jobs:
        folder = work / "ui-jobs" / job_id
        folder.mkdir(parents=True)
        meta = dict(
            id=job_id, project_key="tetra-reveloc", operation=operation, state=state,
            created_at="2026-01-01T00:00:0" + ("1" if job_id == "a" else "2") + "+00:00",
            started_at="2026-01-01T00:00:00+00:00", finished_at="2026-01-01T00:00:05+00:00",
            exit_code=code,
        )
        (folder / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
        (folder / "stdout.log").write_text("", encoding="utf-8")
        (folder / "stderr.log").write_text(err, encoding="utf-8")
    reg = tmp_path / "PROJECTS.yaml"
    reg.write_text(
        "projects:\n  - key: tetra-reveloc\n    label: T\n"
        "    project_root: " + str(tmp_path) + "\n    work_dir: " + str(work) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CSA_PROJECTS_FILE", str(reg))
    parsed = IntakeErrorsResponse.model_validate(workspace.get_intake_errors("tetra"))
    by = {r.id: r for r in parsed.runs}
    assert set(by) == {"a", "b"}
    assert by["a"].has_problems is True and by["a"].problems[0].stream == "stderr"
    assert by["b"].has_problems is False
    assert parsed.warnings == [] and parsed.generated_at
    with pytest.raises(HTTPException) as exc:
        workspace.get_intake_errors("nope")
    assert exc.value.status_code == 404


def test_assets_routes_match_between_both_servers(tmp_path, monkeypatch) -> None:
    import http.client
    import json
    import threading
    from http.server import ThreadingHTTPServer

    from backend import app as api
    from backend.local_server import Handler
    from tests.test_assets import _register_two

    _register_two(tmp_path, monkeypatch)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def get(path):
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
        connection.request("GET", path)
        response = connection.getresponse()
        data = json.loads(response.read())
        status = response.status
        connection.close()
        return status, data

    try:
        status, listing = get("/api/systems/alpha-app/assets?kind=devices&type=printer&state=confirmed")
        assert status == 200
        assert listing == json.loads(json.dumps(api.system_assets("alpha-app", "", "devices", "printer", "confirmed", 1, 50)))
        status, detail = get("/api/systems/alpha-app/assets/CD-000001")
        assert status == 200 and detail == json.loads(json.dumps(api.system_asset_detail("alpha-app", "CD-000001", "")))
        status, withheld = get("/api/systems/alpha-app/assets?kind=devices&include_retired=true")
        assert status == 200 and withheld == json.loads(json.dumps(
            api.system_assets("alpha-app", "", "devices", "", "", 1, 50, True))) and withheld["retired_devices"] == 0
        assert get("/api/systems/beta-app/assets/CD-000001")[0] == 404
        assert get("/api/systems/unknown/assets")[0] == 404
        assert get("/api/systems/alpha-app/assets?kind=bogus")[0] == 422
        assert get("/api/systems/alpha-app/network")[0] == 200
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_device_edit_routes_work_in_the_dependency_free_server(tmp_path, monkeypatch) -> None:
    import http.client
    import json
    import threading
    from http.server import ThreadingHTTPServer

    from backend.local_server import Handler
    from tests.test_assets import _register_two

    _register_two(tmp_path, monkeypatch)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def call(method, path, payload=None):
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
        connection.request(method, path, body=json.dumps(payload or {}).encode() if method != "DELETE" else None,
                           headers={"Content-Type": "application/json"})
        response = connection.getresponse()
        data = json.loads(response.read())
        status = response.status
        connection.close()
        return status, data

    base = "/api/systems/alpha-app/devices"
    try:
        status, made = call("POST", base, {"name": "UPS", "addresses": ["10.124.32.230"]})
        assert status == 200 and made["device"]["device_id"] == "CD-000003"
        status, err = call("POST", base, {"name": "Clash", "addresses": ["10.124.32.10"]})
        assert status == 409 and err["detail"]["code"] == "host_owned"
        status, err = call("PATCH", f"{base}/CD-000003", {"changes": {"role": "power"}})
        assert status == 422 and err["detail"]["code"] == "revision_required"
        status, patched = call("PATCH", f"{base}/CD-000003", {"expected_revision": "1", "changes": {"role": "power"}})
        assert status == 200 and patched["device"]["revision"] == "2"
        status, err = call("PATCH", f"{base}/CD-000003", {"expected_revision": "1", "changes": {"role": "late"}})
        assert status == 409 and err["detail"]["code"] == "conflict"
        status, preview = call("POST", f"{base}/reconcile-preview", {"device_id": "CD-000003", "add": ["10.124.32.231"]})
        assert status == 200 and preview["changes"][0]["status"] == "ready" and preview["writes"] == []
        status, added = call("POST", f"{base}/CD-000003/aliases", {"address": "10.124.32.231", "expected_revision": "2"})
        assert status == 200 and len(added["device"]["aliases"]) == 2
        status, removed = call("DELETE", f"{base}/CD-000003/aliases/10.124.32.231?expected_revision=2")
        assert status == 200
        status, retired = call("POST", f"{base}/CD-000003/retire", {"expected_revision": "2"})
        assert status == 200 and retired["device"]["active"] == "false"
        status, restored = call("POST", f"{base}/CD-000003/restore", {"expected_revision": "3"})
        assert status == 200 and restored["device"]["active"] == "true"
        assert call("PATCH", "/api/systems/beta-app/devices/CD-000003", {"expected_revision": "1", "changes": {"role": "x"}})[0] == 404
        assert call("PATCH", "/api/systems/nope/devices/CD-000003", {"expected_revision": "1", "changes": {"role": "x"}})[0] == 404
        assert call("GET", "/api/systems/alpha-app/assets?kind=devices")[1]["counts"]["devices"] == 3
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_host_conversion_routes_work_in_the_dependency_free_server(tmp_path, monkeypatch) -> None:
    import http.client
    import json
    import threading
    from http.server import ThreadingHTTPServer

    from backend.local_server import Handler
    from tests.test_assets import _register_two

    _register_two(tmp_path, monkeypatch)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def post(path, payload):
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
        connection.request("POST", path, body=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
        response = connection.getresponse()
        data = json.loads(response.read())
        status = response.status
        connection.close()
        return status, data

    base = "/api/systems/alpha-app/devices"
    try:
        status, made = post(base, {"name": "UPS monitor", "addresses": ["10.124.32.230"]})
        dev = made["device"]["device_id"]
        body = {"host_name": "POWERMON1", "source": "Asset register v3", "operator": "WM"}
        status, plan = post(f"{base}/{dev}/host-conversion/preview", body)
        assert status == 200 and plan["status"] == "READY"
        status, err = post(f"{base}/{dev}/host-conversion", {**body, "expected_revision": "1", "preview_id": plan["preview_id"]})
        assert status == 422 and err["detail"]["code"] == "confirmation_required"
        status, err = post(f"{base}/{dev}/host-conversion", {**body, "expected_revision": "1", "preview_id": "stale", "confirm": True})
        assert status == 409 and err["detail"]["code"] == "stale_preview"
        status, done = post(f"{base}/{dev}/host-conversion", {**body, "expected_revision": "1", "preview_id": plan["preview_id"], "confirm": True})
        assert status == 200 and done["decision"]["decision_id"] == "HS-000001" and done["rebuild_required"] is True
        status, undone = post(f"{base}/{dev}/host-conversion/reverse", {"operator": "WM", "reason": "wrong"})
        assert status == 200 and undone["decision"]["active"] == "false"
        assert post("/api/systems/beta-app/devices/CD-000001/host-conversion/reverse", {"operator": "WM", "reason": "x"})[0] == 404
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
