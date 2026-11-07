import io
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from backend import app, documents, working_document


def docx_bytes() -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", "<document/>")
    return output.getvalue()


def workspace(tmp_path: Path, monkeypatch):
    agents = tmp_path / ".agents"
    context = agents / "csa-context"
    context.mkdir(parents=True)
    root = tmp_path / "My App"
    root.mkdir()
    (root / "Discovery").mkdir()
    (root / "00 Knowlege").mkdir()
    (root / "csa-work").mkdir()
    registry = context / "PROJECTS.yaml"
    registry.write_text("projects:\n  - key: my-app\n    label: My App\n"
                        f"    project_root: \"{root}\"\n    work_dir: \"{root / 'csa-work'}\"\n"
                        f"    default_source_set: \"{root / 'Discovery'}\"\n"
                        "    knowledge_dir: 00 Knowlege\n", encoding="utf-8")
    monkeypatch.setenv("CSA_AGENTS_DIR", str(agents))
    monkeypatch.delenv("CSA_PROJECTS_FILE", raising=False)
    return agents, root, registry


def test_select_existing_docx_updates_registry_and_document_resolution(tmp_path, monkeypatch):
    agents, root, registry = workspace(tmp_path, monkeypatch)
    older = root / "02 Current State Assessment" / "old.docx"
    newer = root / "02 Current State Assessment" / "current.docx"
    older.parent.mkdir()
    older.write_bytes(docx_bytes())
    newer.write_bytes(docx_bytes())
    (root / "00 Knowlege" / "reference.docx").write_bytes(docx_bytes())
    choices = working_document.options(app.system_project("my-app"))
    assert {item["relative_path"] for item in choices["candidates"]} == {
        "02 Current State Assessment/old.docx", "02 Current State Assessment/current.docx"}
    assert app.system_setup("my-app")["document_present"] is False
    result = working_document.select(app.system_project("my-app"), agents, newer.relative_to(root).as_posix())
    assert result["status"] == "READY"
    assert app.system_setup("my-app")["document_present"] is True
    assert documents.resolve(app.system_project("my-app"))["path"] == newer.resolve()
    assert registry.read_text().count("working_docx:") == 1
    assert "knowledge_dir: 00 Knowlege" in registry.read_text()
    assert working_document.select(app.system_project("my-app"), agents, older.relative_to(root).as_posix())["status"] == "READY"
    assert registry.read_text().count("working_docx:") == 1


def test_selection_rejects_escape_and_invalid_docx(tmp_path, monkeypatch):
    agents, root, registry = workspace(tmp_path, monkeypatch)
    outside = tmp_path / "outside.docx"
    outside.write_bytes(docx_bytes())
    (root / "bad.docx").write_bytes(b"not a Word file")
    assert working_document.select(app.system_project("my-app"), agents, "../outside.docx")["status"] == "BLOCKED"
    assert working_document.select(app.system_project("my-app"), agents, "bad.docx")["status"] == "BLOCKED"
    assert "working_docx:" not in registry.read_text()


def test_upload_docx_registers_without_overwriting(tmp_path, monkeypatch):
    agents, root, registry = workspace(tmp_path, monkeypatch)
    project = app.system_project("my-app")
    uploaded = working_document.upload(project, agents, "Assessment.docx", docx_bytes())
    assert uploaded["status"] == "READY"
    path = root / "02 Current State Assessment" / "Assessment.docx"
    assert path.read_bytes() == docx_bytes()
    assert working_document.upload(app.system_project("my-app"), agents, "Assessment.docx", docx_bytes())["errors"][0]["code"] == "FILE_EXISTS"
    assert working_document.upload(app.system_project("my-app"), agents, "bad.docx", b"bad")["errors"][0]["code"] == "INVALID_DOCX"
    assert registry.read_text().count("working_docx:") == 1


def test_fastapi_working_document_routes(tmp_path, monkeypatch):
    _, root, _ = workspace(tmp_path, monkeypatch)
    existing = root / "Assessment.docx"
    existing.write_bytes(docx_bytes())
    client = TestClient(app.app)
    assert client.get("/api/systems/my-app/setup").json()["document_present"] is False
    assert client.get("/api/systems/my-app/working-document").json()["candidates"][0]["relative_path"] == "Assessment.docx"
    assert client.post("/api/systems/my-app/working-document", json={"relative_path": "Assessment.docx"}).json()["status"] == "READY"
    assert client.get("/api/systems/my-app/setup").json()["document_present"] is True
    uploaded = client.put("/api/systems/my-app/working-document/upload?filename=Second.docx", content=docx_bytes())
    assert uploaded.json()["status"] == "READY"


def test_loopback_working_document_routes(tmp_path, monkeypatch):
    import http.client
    import json
    import threading
    from http.server import ThreadingHTTPServer
    from urllib.parse import quote

    from backend.local_server import Handler

    _, root, _ = workspace(tmp_path, monkeypatch)
    (root / "Assessment.docx").write_bytes(docx_bytes())
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def call(method, path, body=b"", content_type="application/json"):
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
        connection.request(method, path, body=body, headers={"Content-Type": content_type})
        response = connection.getresponse()
        result = json.loads(response.read())
        connection.close()
        return response.status, result

    try:
        assert call("GET", "/api/systems/my-app/setup")[1]["document_present"] is False
        assert call("GET", "/api/systems/my-app/working-document")[1]["candidates"][0]["relative_path"] == "Assessment.docx"
        chosen = call("POST", "/api/systems/my-app/working-document", json.dumps({"relative_path": "Assessment.docx"}).encode())[1]
        assert chosen["status"] == "READY"
        assert call("GET", "/api/systems/my-app/setup")[1]["document_present"] is True
        uploaded = call("PUT", f"/api/systems/my-app/working-document/upload?filename={quote('Second.docx')}",
                        docx_bytes(), "application/octet-stream")[1]
        assert uploaded["status"] == "READY"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
