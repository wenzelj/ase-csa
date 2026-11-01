"""Reusable CSA DOCX change-application framework."""
import sys as _sys

if _sys.version_info < (3, 11):      # the framework uses dataclass(slots=True) and other 3.10+/3.11 features
    raise SystemExit(
        f"csa_docx needs Python 3.11 or later; this is Python {_sys.version_info[0]}.{_sys.version_info[1]} "
        f"({_sys.executable}). Run it with the framework interpreter: set CSA_PYTHON, or use `.agents/bin/csa`, "
        "which picks one.")

__all__ = [
    "change_parser",
    "docx_package",
    "models",
    "ooxml",
    "report_writer",
    "run_state",
    "tables",
    "validator",
]
