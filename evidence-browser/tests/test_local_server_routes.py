from pathlib import Path


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
