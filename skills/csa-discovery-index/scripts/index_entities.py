"""Entities for the CSA discovery index: the hosts, addresses, names, ports, services, processes, accounts and shares
that a line of text names, found once at index time so no other module has to re-parse the same text.

``extract_line(line)`` returns [(kind, value, norm)]. ``norm`` is the join key: addresses without leading zeros, names
and services in lower case, host names in upper case without a domain, ports as ``tcp/1433``, accounts in upper case.
Patterns are narrow on purpose: a version string, a file name or a file path is not an entity.
Standard library only."""
import json
import re
from pathlib import Path

KINDS = ("address", "fqdn", "host", "port", "service", "process", "account", "share")

_ADDR = re.compile(r"(?<![\w.])(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})(?![\w]|\.\d)")
_VERSION_BEFORE = re.compile(r"(?i)(version|ver|build|v|release)\W{0,3}$")
_SKIP_ADDR = ("0.", "127.", "255.")
_FQDN = re.compile(r"(?<![\w.@\\/-])((?=[A-Za-z0-9-]*[A-Za-z])[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,})(?![\w-])")
# A name only counts when its last label is a domain ending: dotted identifiers (Microsoft.PowerShell.Core,
# Foo.Service) and file names are not host names. Private suffixes seen in OT estates are listed too.
_TLDS = {"com", "net", "org", "edu", "gov", "mil", "int", "info", "biz", "io", "au", "nz", "uk", "us", "ca", "de", "local",
         "internal", "lan", "corp", "intra", "intranet", "home", "localdomain", "test", "ad"}
_HOST_LABEL = re.compile(r"^\s*(?:Host|HostName|Computer ?Name|PSComputerName)\s*:\s*([A-Za-z0-9][A-Za-z0-9_-]{0,62})\s*$", re.I)
_PROTO_LINE = re.compile(r"^\s*(TCP|UDP)6?\s+(\S+?):(\d{1,5})\s", re.I)
_ADDR_PORT = re.compile(r"(?<![\w.])\d{1,3}(?:\.\d{1,3}){3}:(\d{1,5})(?![\w])")
_PORT_LABEL = re.compile(r"^\s*(Local|Remote)?Port\s*:\s*(\d{1,5})\s*$", re.I)
_PROTO_PORT = re.compile(r"\b(TCP|UDP)\b\W{0,3}(\d{1,5})\b", re.I)
_SERVICE = re.compile(r"^\s*(?:SERVICE_NAME|Service ?Name)\s*:\s*(\S+)\s*$", re.I)
_PROCESS_LABEL = re.compile(r"^\s*(?:ProcessName|Image ?Name)\s*:\s*(\S+?)\s*$", re.I)
_TASKLIST = re.compile(r"^\s*([A-Za-z0-9_.$-]+\.exe)\s+\d+\s", re.I)
_ACCOUNT = re.compile(r"(?<![\w\\:/])((?:NT AUTHORITY|NT SERVICE|[A-Z][A-Z0-9-]{1,14})\\[A-Za-z0-9_.$-]{1,40})(?![\w\\])")
_UNC = re.compile(r"\\\\([A-Za-z0-9_.-]+)\\([A-Za-z0-9_.$-]+)")
_SHARE_LABEL = re.compile(r"^\s*Share ?Name\s*:\s*(\S+)\s*$", re.I)


def _addr_norm(a: str) -> str | None:
    parts = a.split(".")
    if any(int(p) > 255 for p in parts) or a.startswith(_SKIP_ADDR):
        return None
    return ".".join(str(int(p)) for p in parts)


def extract_line(line: str) -> list[tuple[str, str, str]]:
    out: list[tuple[str, str, str]] = []
    for m in _ADDR.finditer(line):
        if _VERSION_BEFORE.search(line[:m.start()]):
            continue
        n = _addr_norm(m.group(1))
        if n:
            out.append(("address", m.group(1), n))
    for m in _FQDN.finditer(line):
        v = m.group(1)
        if v.rsplit(".", 1)[1].lower() not in _TLDS or re.fullmatch(r"[\d.]+", v):
            continue
        out.append(("fqdn", v, v.lower()))
    m = _HOST_LABEL.match(line)
    if m:
        out.append(("host", m.group(1), m.group(1).upper().split(".")[0]))
    proto = _PROTO_LINE.match(line)
    if proto:
        out.append(("port", f"{proto.group(1)} {proto.group(3)}", f"{proto.group(1).lower()}/{int(proto.group(3))}"))
    else:
        for m in _PROTO_PORT.finditer(line):
            out.append(("port", m.group(0), f"{m.group(1).lower()}/{int(m.group(2))}"))
    m = _PORT_LABEL.match(line)
    if m:
        out.append(("port", m.group(2), f"any/{int(m.group(2))}"))
    m = _SERVICE.match(line)
    if m:
        out.append(("service", m.group(1), m.group(1).lower()))
    m = _PROCESS_LABEL.match(line) or _TASKLIST.match(line)
    if m:
        out.append(("process", m.group(1), m.group(1).lower()))
    for m in _ACCOUNT.finditer(line):
        out.append(("account", m.group(1), m.group(1).upper()))
    for m in _UNC.finditer(line):
        out.append(("share", m.group(0), m.group(0).lower()))
    m = _SHARE_LABEL.match(line)
    if m:
        out.append(("share", m.group(1), m.group(1).lower()))
    return out


def extract_text(lines: list[str], limit: int = 5000):
    """Yield (line_no, kind, value, norm) for every entity in ``lines`` (line numbers start at 1); one row per
    (line, kind, norm); stops after ``limit`` rows so one huge log cannot dominate the index."""
    n = 0
    for i, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        seen = set()
        for kind, value, norm in extract_line(line):
            if (kind, norm) in seen:
                continue
            seen.add((kind, norm))
            yield i, kind, value[:200], norm[:200]
            n += 1
            if n >= limit:
                return


# --------------------------------------------------------------------------- structured rows
RULES_FILE = Path(__file__).resolve().parents[3] / "references" / "index-entity-columns.json"
_rules_cache: list | None = None


def load_rules() -> list[dict]:
    """The column map: [{"table": compiled regex, "columns": {lower-case column: spec}}]. Empty when the file is missing."""
    global _rules_cache
    if _rules_cache is None:
        try:
            raw = json.loads(RULES_FILE.read_text(encoding="utf-8")).get("rules", [])
        except (OSError, ValueError):
            raw = []
        _rules_cache = [{"table": re.compile(r["table"], re.I), "columns": {c.lower(): v for c, v in r["columns"].items()}}
                        for r in raw]
    return _rules_cache


def normalise(kind: str, value: str) -> str | None:
    """The join key of one value, or None when it is not an entity of that kind."""
    v = (value or "").strip().strip("\"'")
    if not v or v.lower() in ("any", "*", "-", "n/a", "none", "null", "localsubnet", "localhost"):
        return None
    if kind == "address":
        m = _ADDR.fullmatch(v)
        return _addr_norm(m.group(1)) if m else None
    if kind == "port":
        return f"{int(v)}" if v.isdigit() and 0 < int(v) < 65536 else None
    if kind == "fqdn":
        return v.lower() if _FQDN.fullmatch(v) and v.rsplit(".", 1)[1].lower() in _TLDS else None
    if kind == "host":
        return v.upper().split(".")[0] if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,62}", v) else None
    if kind == "account":
        return v.upper()
    if kind in ("service", "process", "share"):
        return v.lower()
    return None


def from_row(table: str, data: dict):
    """Yield (kind, value, norm) for the entities one table row names, as the column map says."""
    cols = None
    for r in load_rules():
        if r["table"].fullmatch(table.lower()):
            cols = r["columns"]
            break
    if not cols:
        return
    for col, val in data.items():
        spec = cols.get(col.lower())
        if spec is None or val in ("", None):
            continue
        spec = {"kind": spec} if isinstance(spec, str) else spec
        kind = spec["kind"]
        cells = re.split(r"[;, ]+", str(val)) if spec.get("split") else [str(val)]
        for cell in cells:
            k = kind
            if k == "name":                      # a host name or a full name, whichever the value is
                k = "fqdn" if normalise("fqdn", cell) else "host"
            n = normalise(k, cell)
            if n is None:
                continue
            if k == "port":
                n = f"{spec.get('proto', 'any')}/{n}"
            yield k, cell.strip(), n
