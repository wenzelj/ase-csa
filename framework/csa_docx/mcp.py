"""``csa-mcp``: a small, dependency-free stdio MCP server exposing the CSA
document function factory (:mod:`csa_docx.tools`) as callable tools.

Modeled directly on the vendored ``docxengine/mcp.py`` (same JSON-RPC
framing, same tools/list + tools/call shape, errors returned as
``isError: true`` tool results rather than exceptions), but much smaller:
seven fixed tools, stdio only, no resources, no HTTP transport — this is
meant to be pointed at by a local tool-calling harness (Codex CLI, Claude
Code, or any other MCP client) so that even a small model can drive the CSA
document workflow by calling named functions instead of reading the long
natural-language agent definitions and constructing paths itself.

See ``.agents/qwen-mcp-factory-plan.md`` for the design this implements.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Callable, IO

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from csa_docx import tools

PROTOCOL_VERSION = "2025-03-26"
SERVER_NAME = "csa-mcp"
SERVER_VERSION = "0.1.0"

_PARSE_ERROR = -32700
_INVALID_REQUEST = -32600
_METHOD_NOT_FOUND = -32601
_INVALID_PARAMS = -32602
_INTERNAL_ERROR = -32603

_ENV_WORKSPACE = "CSA_MCP_WORKSPACE"


def _default_workspace() -> str:
    return os.environ.get(_ENV_WORKSPACE, str(Path.cwd()))


# ---------------------------------------------------------------------------
# Tool schemas and dispatch table. Every capability the model gets is one of
# these seven named, reviewed functions -- deliberately no "run a shell
# command" escape hatch.
# ---------------------------------------------------------------------------

_SECTION_PROP = {
    "type": "string",
    "description": "Section number, e.g. \"7\". The change file and working DOCX are "
    "resolved automatically from the section manifest -- never pass a path.",
}

_OPTIONAL_SECTION_PROP = {
    "type": "string",
    "description": "Section number, e.g. \"7\" -- optional. This operation covers the "
    "whole document, not one section, so leave it out: the working DOCX every "
    "section's change file already points at is resolved automatically. Only pass "
    "it if the workspace genuinely has more than one distinct working DOCX across "
    "its sections and the call errors asking you to disambiguate.",
}

_WORKSPACE_PROP = {
    "type": "string",
    "description": "Workspace root to resolve sections under. Defaults to the "
    f"server's configured workspace ({_ENV_WORKSPACE}) if omitted.",
}

_TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "list_sections",
        "description": (
            "List every Current State Assessment section known from the section "
            "manifest, with each one's current status (NOT_STARTED | IN_PROGRESS | "
            "PARTIAL_COMPLETE | BLOCKED | SECTION_COMPLETE). Call this first to decide "
            "what to work on next -- no path or file-naming knowledge required."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace": _WORKSPACE_PROP,
                "force_refresh": {
                    "type": "boolean",
                    "default": False,
                    "description": "Accepted for backwards compatibility only: the section "
                    "manifest is always scanned fresh from the workspace, so every "
                    "list_sections call already reflects new/renamed/removed files.",
                },
            },
        },
    },
    {
        "name": "get_section_status",
        "description": (
            "Read-only status for one section: its run-state (completed/blocked/next "
            "edit IDs) without applying anything. Returns status NOT_STARTED if the "
            "section has never been run."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"section": _SECTION_PROP, "workspace": _WORKSPACE_PROP},
            "required": ["section"],
        },
    },
    {
        "name": "prepareDocument",
        "description": (
            "The very first call of a project, step 0 -- before anything else, even "
            "before a reviews/ folder or any ChangesCSA_*.md change file exists. At this "
            "point the workspace holds nothing but the raw working DOCX. Do not pass "
            "`section` -- leave it out; there is nothing to name yet. Prepares the ENTIRE "
            "document: checks the working DOCX is editable (not open in Word, not "
            "zero-byte or corrupt, not already failing integrity checks) and builds the "
            "stable structural ID manifest (@H<path>-P<n> / @H<path>-T<n>-R<n>) covering "
            "every heading/paragraph/table-row in the whole document -- the IDs a later "
            "reviewDocument step will use to write `Where:` anchors into the "
            "ChangesCSA_*.md files it creates, and apply_next_batch will use to apply "
            "them. Safe to call again later too (e.g. after reviews/ exists, or to "
            "refresh after a structural edit) -- it's idempotent either way. Returns "
            "status READY | NOT_READY | ERROR. On NOT_READY, report the `reasons` (e.g. "
            "locked_by_word) and stop -- nothing was modified."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "section": _OPTIONAL_SECTION_PROP,
                "workspace": _WORKSPACE_PROP,
                "force_regenerate": {
                    "type": "boolean",
                    "default": False,
                    "description": "Rebuild the stable-ID manifest even when the document's "
                    "heading structure has not drifted since it was last generated. Leave "
                    "false: an unchanged document is then a reported no-op.",
                },
            },
        },
    },
    {
        "name": "lookupStableId",
        "description": (
            "Resolve a change-file `Where:` anchor from the ID manifest prepareDocument "
            "already built -- read-only, does not open the DOCX itself, so it's cheap to "
            "call once per edit while drafting a ChangesCSA_*.md file. Do not pass "
            "`section` -- leave it out, same as prepareDocument. Pass a snippet of the "
            "paragraph/row text you're about to change (matched case-insensitively as a "
            "substring) and get back the matching `@H...` ID(s) to drop straight into "
            "`Where:`. Pass an `@H...` ID itself instead to confirm it still exists. "
            "`unique_id` in the result is set only when there was exactly one match -- if "
            "it's null, narrow the query or check `matches` yourself before trusting a "
            "result. Returns status ERROR if prepareDocument has not been run yet."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "A text snippet to search for (substring, "
                    "case-insensitive by default), or an exact @H... stable ID to confirm.",
                },
                "section": _OPTIONAL_SECTION_PROP,
                "workspace": _WORKSPACE_PROP,
                "kind": {
                    "type": "string",
                    "enum": ["heading", "paragraph", "table_row"],
                    "description": "Optional: restrict matches to one element kind.",
                },
                "limit": {
                    "type": "integer",
                    "default": 10,
                    "description": "Max matches to return (result still reports the true "
                    "match_count and sets truncated: true if it exceeds this).",
                },
                "case_sensitive": {
                    "type": "boolean",
                    "default": False,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "apply_next_batch",
        "description": (
            "Apply the next bounded batch of approved edits for a CSA section to the "
            "working DOCX. Creates a timestamped backup first, applies up to `limit` "
            "pending edits as tracked changes, validates the result, and updates the "
            "run-state and change-report files. Returns status: SECTION_COMPLETE | "
            "PARTIAL_COMPLETE | BLOCKED | NOT_READY, plus which edit IDs were "
            "applied/blocked and the next edit ID if any. On BLOCKED, stop and report it "
            "-- do not retry or attempt manual repair. NOT_READY means the same step-0 "
            "checks prepareDocument runs failed (e.g. the document is open in Word) and "
            "nothing was backed up or edited -- report the `reasons` and stop."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "section": _SECTION_PROP,
                "limit": {
                    "type": "integer",
                    "default": 3,
                    "description": "Max edits to apply in this call.",
                },
                "workspace": _WORKSPACE_PROP,
            },
            "required": ["section"],
        },
    },
    {
        "name": "validate_section",
        "description": (
            "Run DOCX integrity checks (archive zip test, XML well-formedness, "
            "comment-ID consistency, table-row comment safety) for one section's "
            "working docx, without applying any edits."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"section": _SECTION_PROP, "workspace": _WORKSPACE_PROP},
            "required": ["section"],
        },
    },
    {
        "name": "refresh_manifest",
        "description": (
            "Rebuild the section manifest from the current workspace layout and return "
            "it. The manifest is always derived live from the folder structure "
            "(nothing is cached), so this is a no-op for stale paths; call it if you "
            "want the full resolved section -> change file / DOCX mapping."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"workspace": _WORKSPACE_PROP},
        },
    },
]

_DISPATCH: dict[str, Callable[..., dict]] = {
    "list_sections": tools.list_sections,
    "get_section_status": tools.get_section_status,
    "prepareDocument": tools.prepareDocument,
    "lookupStableId": tools.lookupStableId,
    "apply_next_batch": tools.apply_next_batch,
    "validate_section": tools.validate_section,
    "refresh_manifest": tools.refresh_manifest,
}


def _call_tool(name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
    if name not in _DISPATCH:
        return {"status": "ERROR", "message": f"Unknown tool: {name}"}
    kwargs = dict(arguments or {})
    kwargs.setdefault("workspace", _default_workspace())
    try:
        return _DISPATCH[name](**kwargs)
    except TypeError as exc:
        return {"status": "ERROR", "message": f"Bad arguments for {name}: {exc}"}
    except Exception as exc:  # never let a handler bug reach the model as a crash
        return {"status": "ERROR", "message": f"{type(exc).__name__}: {exc}"}


# ---------------------------------------------------------------------------
# JSON-RPC framing (stdio transport only -- this is a local, single-user
# server launched by the tool-calling harness, not a shared service).
# ---------------------------------------------------------------------------


def _error(req_id: object, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def _result(req_id: object, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _initialize(req_id: object) -> dict[str, Any]:
    return _result(
        req_id,
        {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        },
    )


def _tools_call(req_id: object, params: Any) -> dict[str, Any]:
    if not isinstance(params, dict) or not isinstance(params.get("name"), str):
        return _error(req_id, _INVALID_PARAMS, "tools/call requires params with a string 'name'.")
    arguments = params.get("arguments")
    if arguments is not None and not isinstance(arguments, dict):
        return _error(req_id, _INVALID_PARAMS, "tools/call 'arguments' must be an object.")
    payload = _call_tool(params["name"], arguments)
    is_error = payload.get("status") == "ERROR"
    return _result(
        req_id,
        {
            "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
            "isError": is_error,
        },
    )


def _handle(message: Any) -> dict[str, Any] | None:
    if not isinstance(message, dict) or not isinstance(message.get("method"), str):
        return _error(None, _INVALID_REQUEST, "Message must be a JSON-RPC request object.")
    method: str = message["method"]
    req_id = message.get("id")
    if "id" not in message:  # notification: never answered, even if unknown
        return None
    if method == "initialize":
        return _initialize(req_id)
    if method == "ping":
        return _result(req_id, {})
    if method == "tools/list":
        return _result(req_id, {"tools": _TOOL_SCHEMAS})
    if method == "tools/call":
        try:
            return _tools_call(req_id, message.get("params"))
        except Exception as exc:  # never kill the transport on a handler bug
            return _error(req_id, _INTERNAL_ERROR, f"{type(exc).__name__}: {exc}")
    if method == "resources/list":
        return _result(req_id, {"resources": []})
    return _error(req_id, _METHOD_NOT_FOUND, f"Method not found: {method}")


def serve(stdin: IO[str], stdout: IO[str]) -> int:
    """Run the JSON-RPC loop until EOF: one line in, one line out."""
    for raw in stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError as exc:
            response: dict[str, Any] | None = _error(None, _PARSE_ERROR, f"Parse error: {exc}.")
        else:
            response = _handle(message)
        if response is not None:
            stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            stdout.flush()
    return 0


def main() -> int:
    return serve(sys.stdin, sys.stdout)


if __name__ == "__main__":
    raise SystemExit(main())
