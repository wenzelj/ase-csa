from __future__ import annotations

import json
import mimetypes
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from fastapi import HTTPException
from fastapi.responses import FileResponse

from backend import app as api


def scalar(query: dict[str, list[str]], name: str, default: str = "") -> str:
    return query.get(name, [default])[0]


def boolean(query: dict[str, list[str]], name: str) -> bool:
    return scalar(query, name).lower() in ("1", "true", "yes", "on")


class Handler(BaseHTTPRequestHandler):
    server_version = "CSAEvidence/0.1"

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"{self.address_string()} - {fmt % args}")

    def send_json(self, value: object, status: int = 200) -> None:
        body = json.dumps(value, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path: Path, media_type: str | None = None) -> None:
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", media_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Disposition", f'inline; filename="{path.name}"')
        self.end_headers()
        self.wfile.write(body)

    def dispatch_result(self, result: object) -> None:
        if isinstance(result, FileResponse):
            self.send_file(Path(result.path), result.media_type)
        else:
            self.send_json(result)

    def fail(self, error: Exception) -> None:
        if isinstance(error, HTTPException):
            self.send_json({"detail": error.detail}, error.status_code)
        else:
            self.send_json({"detail": f"{type(error).__name__}: {error}"}, 500)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path, query = unquote(parsed.path), parse_qs(parsed.query)
        try:
            if path == "/api/systems":
                return self.dispatch_result(api.get_systems())
            match = re.fullmatch(r"/api/systems/([^/]+)/summary", path)
            if match:
                return self.dispatch_result(api.get_summary(match.group(1)))
            match = re.fullmatch(r"/api/systems/([^/]+)/portrait", path)
            if match:
                return self.dispatch_result(api.application_portrait(match.group(1)))
            match = re.fullmatch(r"/api/systems/([^/]+)/commands", path)
            if match:
                return self.dispatch_result(api.command_catalogue(match.group(1)))
            match = re.fullmatch(r"/api/systems/([^/]+)/pipeline", path)
            if match:
                project = api.system_project(match.group(1))
                return self.dispatch_result(api.pipeline.snapshot(api.agents_dir(), project).model_dump())
            match = re.fullmatch(r"/api/systems/([^/]+)/word-review", path)
            if match:
                project = api.system_project(match.group(1))
                return self.dispatch_result(api.word_review.build_review(api.agents_dir(), project))
            match = re.fullmatch(r"/api/systems/([^/]+)/document", path)
            if match:
                return self.dispatch_result(api.get_document(match.group(1)))
            match = re.fullmatch(r"/api/systems/([^/]+)/document/preview", path)
            if match:
                return self.dispatch_result(api.get_document_preview(
                    match.group(1), scalar(query, "mode", "descriptor")))
            match = re.fullmatch(r"/api/systems/([^/]+)/document/comments", path)
            if match:
                return self.dispatch_result(api.get_document_comments(match.group(1)))
            match = re.fullmatch(r"/api/systems/([^/]+)/jobs", path)
            if match:
                return self.dispatch_result(api.list_jobs(match.group(1)))
            match = re.fullmatch(r"/api/systems/([^/]+)/jobs/([^/]+)", path)
            if match:
                return self.dispatch_result(api.get_job(match.group(1), match.group(2)))
            match = re.fullmatch(r"/api/systems/([^/]+)/evidence", path)
            if match:
                return self.dispatch_result(api.evidence(
                    match.group(1), scalar(query, "q"), scalar(query, "status"), scalar(query, "area"),
                    int(scalar(query, "offset", "0")), int(scalar(query, "limit", "100"))))
            match = re.fullmatch(r"/api/systems/([^/]+)/files", path)
            if match:
                return self.dispatch_result(api.files(
                    match.group(1), scalar(query, "q"), scalar(query, "host"), scalar(query, "ext"), scalar(query, "status"),
                    scalar(query, "source_class"), boolean(query, "all_captures"), boolean(query, "include_archive"),
                    int(scalar(query, "offset", "0")), int(scalar(query, "limit", "150"))))
            match = re.fullmatch(r"/api/systems/([^/]+)/files/(\d+)/preview", path)
            if match:
                return self.dispatch_result(api.preview(match.group(1), int(match.group(2)),
                                                        scalar(query, "anchor") or None, scalar(query, "mode", "preview")))
            match = re.fullmatch(r"/api/systems/([^/]+)/evidence/([^/]+)/sources", path)
            if match:
                return self.dispatch_result(api.evidence_sources(match.group(1), match.group(2)))
            match = re.fullmatch(r"/api/systems/([^/]+)/tables", path)
            if match:
                return self.dispatch_result(api.tables(match.group(1), scalar(query, "table"), scalar(query, "host"),
                                                       scalar(query, "where"), int(scalar(query, "limit", "100"))))
            return self.static(path)
        except Exception as error:
            self.fail(error)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
            match = re.fullmatch(r"/api/systems/([^/]+)/search", parsed.path)
            if match:
                return self.dispatch_result(api.search(match.group(1), api.SearchRequest.model_validate(payload)))
            match = re.fullmatch(r"/api/systems/([^/]+)/commands/([^/]+)", parsed.path)
            if match:
                return self.dispatch_result(api.run_command(
                    match.group(1), match.group(2), api.CommandRequest.model_validate(payload)))
            match = re.fullmatch(r"/api/systems/([^/]+)/jobs", parsed.path)
            if match:
                return self.dispatch_result(api.create_job(
                    match.group(1), api.JobCreateRequest.model_validate(payload)))
            match = re.fullmatch(r"/api/systems/([^/]+)/evidence-drafts/validate", parsed.path)
            if match:
                return self.dispatch_result(api.validate_evidence(match.group(1), api.EvidenceDraft.model_validate(payload)))
            match = re.fullmatch(r"/api/systems/([^/]+)/evidence-drafts/commit", path)
            if match:
                return self.dispatch_result(api.commit_evidence(match.group(1), api.CommitRequest.model_validate(payload)))
            match = re.fullmatch(r"/api/systems/([^/]+)/word-review/open", parsed.path)
            if match:
                return self.dispatch_result(api.word_review.open_authoritative(api.system_project(match.group(1))))
            match = re.fullmatch(r"/api/systems/([^/]+)/word-review/operator-note", parsed.path)
            if match:
                return self.dispatch_result(api.record_operator_note(match.group(1), payload))
            match = re.fullmatch(r"/api/systems/([^/]+)/word-review/refresh", parsed.path)
            if match:
                return self.dispatch_result(api.word_review.refresh_gate(api.agents_dir(), api.system_project(match.group(1))))
            self.send_json({"detail": "Route not found"}, 404)
        except Exception as error:
            self.fail(error)

    def do_DELETE(self) -> None:
        try:
            path = unquote(urlparse(self.path).path)
            match = re.fullmatch(r"/api/systems/([^/]+)/jobs/([^/]+)", path)
            if match:
                return self.dispatch_result(api.cancel_job(match.group(1), match.group(2)))
            self.send_json({"detail": "Route not found"}, 404)
        except Exception as error:
            self.fail(error)

    def static(self, request_path: str) -> None:
        root = api.DIST.resolve()
        relative = request_path.lstrip("/") or "index.html"
        path = (root / relative).resolve()
        if root not in path.parents and path != root:
            return self.send_json({"detail": "Invalid asset path"}, 403)
        if not path.is_file():
            path = root / "index.html"
        if not path.is_file():
            return self.send_json({"detail": "Frontend bundle is not built"}, 503)
        self.send_file(path)


def serve(host: str, port: int) -> None:
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"CSA Evidence Workspace: http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
