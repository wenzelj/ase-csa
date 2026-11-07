"""Local answer calls receive inline inputs and cannot execute model tools."""
import json
from pathlib import Path
import runpy
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import SimpleNamespace

import pytest

from csa_docx import closed_answer as C


def test_resolve_reuses_profile_and_command_overrides(tmp_path):
    (tmp_path / "config.toml").write_text('model="base"\nmodel_provider="remote_ollama"\n'
        '[model_providers.remote_ollama]\nname="Ollama"\nbase_url="http://localhost:1234/v1"\nwire_api="responses"\n')
    (tmp_path / "evo.config.toml").write_text('model="selected"\nmodel_reasoning_effort="none"\n')
    original = (tmp_path / "config.toml").read_bytes()
    cfg = C.resolve('codex exec --profile evo -m override {prompt}', tmp_path)
    assert cfg["model"] == "override"
    assert cfg["base_url"] == "http://localhost:1234/v1"
    assert cfg["reasoning_effort"] == "none"
    assert (tmp_path / "config.toml").read_bytes() == original
    assert C.resolve('claude -p {prompt}', tmp_path)["status"] == "UNSUPPORTED"


def test_inline_inputs_read_only_the_named_card_and_repair_files(tmp_path):
    for name, text in [("card.md", "task card"), ("base.md", "base answer"), ("errors.md", "repair B2"),
                       ("other.md", "unrelated secrets")]:
        (tmp_path / name).write_text(text)
    args = ['CARD=card.md', 'ANSWER=base.md', 'ERRORS=errors.md', 'SHEET=patch.md', 'ONLY=B2']
    text, output = C.inline_inputs(args, tmp_path)
    assert all(x in text for x in ['task card', 'base answer', 'repair B2'])
    assert 'unrelated secrets' not in text
    assert output == tmp_path / 'patch.md'
    with pytest.raises(ValueError):
        C.inline_inputs(['CARD=../outside.md', 'SHEET=patch.md'], tmp_path)


@pytest.fixture
def endpoint():
    seen = []
    reply = {"status": "completed", "output": [{"type": "message", "content": [
        {"type": "output_text", "text": "## B2 Test\nQUESTION: Which owner can confirm the scope?\n"}]}]}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            seen.append((self.path, json.loads(self.rfile.read(int(self.headers['Content-Length'])))))
            data = json.dumps(reply).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(data)

    server = HTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    cfg = {"model": "selected-model", "base_url": f'http://127.0.0.1:{server.server_port}/v1'}
    yield cfg, seen, reply
    server.shutdown()
    server.server_close()
    worker.join()


def test_generation_sends_no_tools_and_preserves_focused_block(endpoint):
    cfg, seen, _ = endpoint
    text = C.generate({"provider": cfg, "prompt": "card only"})
    assert text.startswith('## B2')
    path, request = seen[0]
    assert path == '/v1/responses'
    assert request['model'] == 'selected-model'
    assert request['input'] == 'card only'
    assert request['tools'] == [] and request['tool_choice'] == 'none'


def test_tool_call_reply_is_rejected_and_never_executed(endpoint, tmp_path):
    cfg, _, reply = endpoint
    sentinel = tmp_path / 'should-not-exist'
    reply['output'] = [{"type": "function_call", "name": "exec_command",
                        "arguments": json.dumps({"cmd": f'touch {sentinel}'})}]
    with pytest.raises(ValueError, match='no tool was executed'):
        C.generate({"provider": cfg, "prompt": "card"})
    assert not sentinel.exists()


def test_failed_generation_preserves_existing_sheet(endpoint, tmp_path):
    cfg, _, reply = endpoint
    reply['status'] = 'incomplete'
    output = tmp_path / 'answer.md'
    output.write_text('existing answer')
    job = tmp_path / 'job.json'
    job.write_text(json.dumps({"provider": cfg, "prompt": "card", "output": str(output)}))
    assert C.main(['generate', '--job', str(job)]) != 0
    assert output.read_text() == 'existing answer'


def test_actual_launcher_uses_closed_worker_and_cleans_request(endpoint, tmp_path, monkeypatch):
    cfg, seen, _ = endpoint
    csa = runpy.run_path(str(Path(__file__).parents[3] / 'bin/csa'))
    launch = csa['launch']
    g = launch.__globals__
    project = {'work_dir': str(tmp_path / 'work'), 'key': 'test'}
    cards = tmp_path / 'work/cards'
    cards.mkdir(parents=True)
    (cards / 'card.md').write_text('the supplied card')
    (cards / 'other.answer.md').write_text('unrelated answer')
    monkeypatch.setitem(g, 'settings', lambda: {'evo_headless': 'codex exec --profile evo {prompt}',
                                               'answer_stall_minutes': 0})
    monkeypatch.setitem(g, 'framework_python', lambda: sys.executable)
    monkeypatch.setitem(g, '_fw_json', lambda *args: dict(cfg, status='OK'))
    monkeypatch.setitem(g, 'build_prompt', lambda *a, **k: 'inline rules' if k.get('inline') else 'bad prompt')
    monkeypatch.setitem(g, 'STATE_DIR', tmp_path / 'state')
    monkeypatch.setattr(g['shutil'], 'which', lambda *a: '/fake/codex')
    rc = launch(project, {'verb': 'draft', 'title': 'Draft'},
                ['4', 'CARD=card.md', 'SHEET=patch.md', 'ONLY=B2'],
                SimpleNamespace(cli='evo', headless=True, print=False))
    assert rc == 0
    assert (cards / 'patch.md').read_text().startswith('## B2')
    assert seen[0][1]['tools'] == []
    assert 'the supplied card' in seen[0][1]['input']
    assert 'unrelated answer' not in seen[0][1]['input']
    assert not list((tmp_path / 'state/tmp').glob('closed-answer-*'))


def test_inline_prompt_does_not_ask_model_to_read_files_or_validate(tmp_path, monkeypatch):
    csa = runpy.run_path(str(Path(__file__).parents[3] / 'bin/csa'))
    prompt = csa['build_prompt']
    monkeypatch.setitem(prompt.__globals__, 'resolve_visible_section', lambda *a: {})
    monkeypatch.setitem(prompt.__globals__, '_draft_rules', lambda *a: 'Return the facts and finished prose.')
    text = prompt({'key': 'test', 'label': 'Test'},
                  {'verb': 'draft', 'title': 'Draft Agent', 'file': 'agent.md', 'inputs': 'CARD*, SHEET*'},
                  ['4', 'CARD=card.md', 'SHEET=patch.md', 'ONLY=B2'], local=True, inline=True)
    assert 'ONLY=B2' in text
    assert 'no tools or filesystem access' in text
    assert 'VALIDATE=' not in text
    assert 'Load this agent definition' not in text
    assert 'use `exec_command`' not in text
