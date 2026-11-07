"""Tool-free local answer generation. The framework owns files and validation."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shlex
import sys
import urllib.request


def _merge(left: dict, right: dict) -> dict:
    out = dict(left)
    for key, value in right.items():
        out[key] = _merge(out.get(key, {}), value) if isinstance(value, dict) else value
    return out


def resolve(template: str, home: Path | None = None) -> dict:
    """Reuse the selected Codex Ollama model/provider without changing its settings."""
    import tomllib
    args = shlex.split(template)
    if not args or Path(args[0]).name != "codex" or "exec" not in args:
        return {"status": "UNSUPPORTED"}
    home = home or Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))

    def read(path):
        return tomllib.loads(path.read_text()) if path.is_file() else {}

    cfg = read(home / "config.toml")
    profile = next((args[i + 1] for i, x in enumerate(args[:-1]) if x in ("--profile", "-p")), None)
    if profile:
        file = home / f"{profile}.config.toml"
        layer = read(file) if file.is_file() else cfg.get("profiles", {}).get(profile)
        if layer is None:
            raise ValueError(f"Codex profile {profile!r} was not found")
        cfg = _merge(cfg, layer)
    for i, arg in enumerate(args[:-1]):
        if arg in ("-c", "--config"):
            cfg = _merge(cfg, tomllib.loads(args[i + 1]))
        elif arg in ("-m", "--model"):
            cfg["model"] = args[i + 1]
    name = cfg.get("model_provider", "")
    provider = cfg.get("model_providers", {}).get(name, {})
    if "ollama" not in (name + " " + provider.get("name", "")).lower():
        return {"status": "UNSUPPORTED"}
    if provider.get("wire_api", "responses") != "responses":
        raise ValueError("closed answers require the configured Ollama Responses endpoint")
    if not cfg.get("model") or not provider.get("base_url"):
        raise ValueError("the selected local model/provider is incomplete")
    return {"status": "OK", "model": cfg["model"], "base_url": provider["base_url"],
            "env_key": provider.get("env_key"), "reasoning_effort": cfg.get("model_reasoning_effort")}


def inline_inputs(args: list[str], folder: Path) -> tuple[str, Path]:
    """Read only the explicitly supplied card, base answer and errors; no directory scan."""
    values = dict(x.split("=", 1) for x in args if "=" in x)
    root = folder.resolve()

    def path(value):
        p = (root / value).resolve()
        if not p.is_relative_to(root):
            raise ValueError("answer inputs and output must be inside the cards folder")
        return p

    blocks = []
    for key in ("CARD", "ANSWER", "ERRORS"):
        if values.get(key):
            p = path(values[key])
            blocks.append(f"\n--- {key} INPUT ---\n{p.read_text(encoding='utf-8')}\n--- END {key} INPUT ---\n")
    if not values.get("CARD") or not values.get("SHEET"):
        raise ValueError("closed answers require CARD and SHEET")
    return "\n".join(blocks), path(values["SHEET"])


def generate(job: dict) -> str:
    cfg = job["provider"]
    payload = {"model": cfg["model"], "input": job["prompt"], "tools": [],
               "tool_choice": "none", "stream": False}
    if cfg.get("reasoning_effort"):
        payload["reasoning"] = {"effort": cfg["reasoning_effort"]}
    headers = {"Content-Type": "application/json"}
    if cfg.get("env_key"):
        token = os.environ.get(cfg["env_key"])
        if not token:
            raise ValueError("the configured provider credential environment variable is missing")
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(cfg["base_url"].rstrip("/") + "/responses",
                                 data=json.dumps(payload).encode(), headers=headers)
    with urllib.request.urlopen(req, timeout=job.get("timeout_s", 1500)) as response:
        data = json.load(response)
    if data.get("error") or data.get("status") != "completed":
        raise ValueError("local model did not complete the answer")
    output = data.get("output", [])
    if any(x.get("type") not in ("message", "reasoning") for x in output):
        raise ValueError("local model returned a tool call instead of an answer; no tool was executed")
    text = "\n".join(c["text"] for item in output if item.get("type") == "message"
                     for c in item.get("content", []) if c.get("type") == "output_text")
    start = re.search(r"(?m)^##\s+(?:B|F)\d+\b", text)
    if not start:
        raise ValueError("local model returned no answer-sheet blocks")
    return re.sub(r"\n```\s*$", "", text[start.start():].rstrip()) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("command", choices=["resolve", "generate"])
    ap.add_argument("--template")
    ap.add_argument("--job", type=Path)
    a = ap.parse_args(argv)
    try:
        if a.command == "resolve":
            print(json.dumps(resolve(a.template)))
        else:
            job = json.loads(a.job.read_text())
            text = generate(job)
            output = Path(job["output"])
            temporary = output.with_suffix(output.suffix + ".tmp")
            temporary.write_text(text, encoding="utf-8")
            temporary.replace(output)
            print(f"Closed answer saved to {output.name}; framework validation follows.", flush=True)
        return 0
    except Exception as error:
        print(f"Closed answer failed: {type(error).__name__}: {error}", file=sys.stderr, flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
