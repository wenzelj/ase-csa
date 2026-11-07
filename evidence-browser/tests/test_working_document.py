import io
import os
import shutil
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

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


def test_legacy_source_is_separate_from_working_docx(tmp_path, monkeypatch):
    agents, root, registry = workspace(tmp_path, monkeypatch)
    old = root / "Old Assessment.docx"
    new = root / "New Assessment.docx"
    old.write_bytes(docx_bytes())
    new.write_bytes(docx_bytes())
    assert working_document.select(app.system_project("my-app"), agents, new.name)["status"] == "READY"
    result = working_document.select_legacy(app.system_project("my-app"), agents, old.name)
    assert result["status"] == "READY"
    assert result["legacy_docx"] == str(old)
    assert working_document.options(app.system_project("my-app"))["legacy_path"] == str(old)
    text = registry.read_text()
    assert text.count("legacy_docx:") == 1 and text.count("working_docx:") == 1
    same = working_document.select_legacy(app.system_project("my-app"), agents, new.name)
    assert same["errors"][0]["code"] == "SAME_AS_WORKING"
    assert working_document.select_legacy(app.system_project("my-app"), agents, "../outside.docx")["status"] == "BLOCKED"


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
    assert client.post("/api/systems/my-app/legacy-document", json={"relative_path": "Assessment.docx"}).json()["status"] == "READY"


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
        old = call("POST", "/api/systems/my-app/legacy-document",
                   json.dumps({"relative_path": "Assessment.docx"}).encode())[1]
        assert old["status"] == "READY"
        template_result = call("POST", "/api/systems/my-app/working-document/from-template",
                               json.dumps({"template_id": "missing", "output_path": "new.docx", "confirmed": True}).encode())[1]
        assert template_result["errors"][0]["code"] == "TEMPLATE_MISSING"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _shared_template() -> Path:
    return Path(os.environ.get("CSA_TEST_TEMPLATE") or
                Path(__file__).resolve().parents[3] / "CSA Template" / "archive" / "CSA_Template_v1.6.dotx")


def test_create_working_docx_from_shared_dotx_and_register(tmp_path, monkeypatch):
    source = _shared_template()
    if not source.is_file():
        pytest.skip("Shared CSA template is unavailable in this checkout")
    agents, root, registry = workspace(tmp_path, monkeypatch)
    shared = tmp_path / "CSA Template"
    shared.mkdir()
    shutil.copy2(source, shared / source.name)
    project = app.system_project("my-app")
    choices = working_document.options(project)
    template_id = next(item["id"] for item in choices["templates"] if item["source"] == "shared")
    output = choices["suggested_output"]
    result = TestClient(app.app).post("/api/systems/my-app/working-document/from-template", json={
        "template_id": template_id, "output_path": output, "system_name": "My App", "confirmed": True}).json()
    assert result["status"] == "READY", result
    assert result["template_check"] in ("PASS", "WARN")
    document = root / output
    assert document.is_file()
    assert documents.resolve(app.system_project("my-app"))["path"] == document.resolve()
    assert "working_docx:" in registry.read_text()
    refused = working_document.create_from_template(app.system_project("my-app"), agents, {
        "template_id": template_id, "output_path": output, "system_name": "My App", "confirmed": True})
    assert refused["errors"][0]["code"] == "OUTPUT_UNAVAILABLE"


def test_template_creation_rejects_invalid_template_and_unsafe_output(tmp_path, monkeypatch):
    agents, root, registry = workspace(tmp_path, monkeypatch)
    template = root / "Assessment.dotx"
    template.write_bytes(b"not a Word template")
    project = app.system_project("my-app")
    assert working_document.create_from_template(project, agents, {
        "template_id": "project:Assessment.dotx", "output_path": "../escape.docx", "confirmed": True})["status"] == "BLOCKED"
    result = working_document.create_from_template(project, agents, {
        "template_id": "project:Assessment.dotx", "output_path": "New/output.docx", "confirmed": True})
    assert result["status"] == "BLOCKED"
    assert result["errors"][0]["code"] == "TEMPLATE_CREATE_FAILED"
    assert not (root / "New" / "output.docx").exists()
    assert "working_docx:" not in registry.read_text()


def test_rms_local_template_creates_checked_working_docx_without_changing_dotx(tmp_path, monkeypatch):
    source = Path(os.environ.get("CSA_TEST_OLD_TEMPLATE") or
                  Path(__file__).resolve().parents[3] / "RMS" / "02 Current State Assessment" /
                  "01 Final Version" / "Current_State_Assessment_Template.dotx")
    if not source.is_file():
        pytest.skip("RMS local template is unavailable in this checkout")
    agents, root, registry = workspace(tmp_path, monkeypatch)
    target = root / "02 Current State Assessment" / "01 Final Version" / source.name
    target.parent.mkdir(parents=True)
    shutil.copy2(source, target)
    original = target.read_bytes()
    result = working_document.create_from_template(app.system_project("my-app"), agents, {
        "template_id": "project:02 Current State Assessment/01 Final Version/Current_State_Assessment_Template.dotx",
        "output_path": "02 Current State Assessment/02 New Template/Assessment.docx", "confirmed": True})
    assert result["status"] == "READY", result
    assert result["template_check"] in ("PASS", "WARN")
    assert target.read_bytes() == original
    assert (root / "02 Current State Assessment" / "02 New Template" / "Assessment.docx").is_file()
    assert "working_docx:" in registry.read_text()
