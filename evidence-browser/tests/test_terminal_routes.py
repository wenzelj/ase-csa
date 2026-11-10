from __future__ import annotations

import base64
import http.client
import json
import sys
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

from fastapi.testclient import TestClient
from fastapi import HTTPException

from backend import app, commands
from backend.jobs import JobManager
from backend.local_server import Handler
from backend.models import CommandRequest


def _setup(tmp_path: Path, monkeypatch):
    root = tmp_path / "sample"
    work = root / "csa-work"
    work.mkdir(parents=True)
    project = {"key": "sample", "project_root": str(root), "work_dir": str(work)}
    operation = commands.OPERATIONS["intake"]
    script = "import sys; print('READY', flush=True); print('REPLY', sys.stdin.readline().strip(), flush=True)"
    monkeypatch.setattr(commands, "build_argv", lambda *_: (operation, [sys.executable, "-c", script]))
    manager = JobManager(tmp_path / ".agents")
    monkeypatch.setattr(app, "job_manager", manager)
    monkeypatch.setattr(app, "system_project", lambda key: project if key == "sample" else None)
    job = manager.submit(project, "intake", CommandRequest(options={"cli": "claude"}))
    return project, manager, job


def _ready(fetch):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        page = fetch()
        if b"READY" in base64.b64decode(page["data"]):
            return page
    raise AssertionError("PTY did not produce READY")


def test_fastapi_terminal_routes_accept_input_and_reject_foreign_origin(tmp_path, monkeypatch):
    project, manager, job = _setup(tmp_path, monkeypatch)
    client = TestClient(app.app, base_url="http://127.0.0.1")
    path = f"/api/systems/sample/jobs/{job.id}/terminal"
    page = _ready(lambda: client.get(path).json())
    assert client.get(path + "?after=-1").status_code == 422
    body = {"data": base64.b64encode(b"hello\n").decode(), "capability": page["capability"]}
    assert client.post(path + "/input", json=body).status_code == 403
    assert client.post(path + "/input", json=body, headers={"Origin": "http://evil.test"}).status_code == 403
    assert client.post(path + "/input", json={**body, "capability": "bad"},
                       headers={"Origin": "http://127.0.0.1"}).status_code == 403
    assert client.post(path + "/input", json=body, headers={"Origin": "http://127.0.0.1"}).status_code == 200
    assert manager.wait(project, job.id, 3).state == "succeeded"
    assert b"REPLY hello" in base64.b64decode(client.get(path).json()["data"])
    next_job = manager.submit(project, "intake", CommandRequest(options={"cli": "claude"}))
    next_path = f"/api/systems/sample/jobs/{next_job.id}/terminal"
    next_page = _ready(lambda: client.get(next_path).json())
    assert next_page["capability"] != page["capability"]
    assert client.post(next_path + "/input", json=body,
                       headers={"Origin": "http://127.0.0.1"}).status_code == 403
    assert client.post(next_path + "/input", json={**body, "capability": next_page["capability"]},
                       headers={"Origin": "http://127.0.0.1"}).status_code == 200
    assert manager.wait(project, next_job.id, 3).state == "succeeded"
    other = dict(project, key="other")
    try:
        manager.terminal_output(other, job.id, 0)
    except HTTPException as error:
        assert error.status_code == 404
    else:
        raise AssertionError("Another project read the terminal")


def test_loopback_server_terminal_route_matches_fastapi(tmp_path, monkeypatch):
    project, manager, job = _setup(tmp_path, monkeypatch)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    path = f"/api/systems/sample/jobs/{job.id}/terminal"

    def call(method, suffix="", body=None, origin=None):
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
        headers = {"Content-Type": "application/json"}
        if origin:
            headers["Origin"] = origin
        connection.request(method, path + suffix, body=json.dumps(body or {}).encode(), headers=headers)
        response = connection.getresponse()
        value = json.loads(response.read())
        code = response.status
        connection.close()
        return code, value

    try:
        page = _ready(lambda: call("GET")[1])
        body = {"data": base64.b64encode(b"local\n").decode(), "capability": page["capability"]}
        origin = f"http://127.0.0.1:{server.server_port}"
        assert call("POST", "/input", body, "http://evil.test")[0] == 403
        assert call("POST", "/resize", {"rows": 40, "cols": 100, "capability": page["capability"]}, origin)[0] == 200
        assert call("POST", "/input", body, origin)[0] == 200
        assert manager.wait(project, job.id, 3).state == "succeeded"
        assert b"REPLY local" in base64.b64decode(call("GET")[1]["data"])
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=3)
