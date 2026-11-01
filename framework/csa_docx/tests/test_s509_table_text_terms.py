"""S509: the text topic_tables writes into the document holds none of the framework terms."""
import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from csa_docx import topic_tables as tt  # noqa: E402
import test_topic_tables as base  # noqa: E402

LINT = Path(__file__).resolve().parents[3] / "skills/australian-it-ot-terminology/scripts/term_lint.py"


def _terms():
    spec = importlib.util.spec_from_file_location("term_lint_s509", LINT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.load_framework_terms()


def _texts(t):
    out = [tt.markdown(t), t["common"], *t["markers"]]
    for r in t["rows"]:
        out.extend(r["cells"])
    return out


def _check(t):
    terms = _terms()
    assert terms
    for text in _texts(t):
        for pattern, _say in terms:
            assert not pattern.search(text), (pattern.pattern, text)


def test_assumed_and_differing_hosts_use_no_framework_terms(tmp_path):
    t = base.build(tmp_path)
    assert tt.ASSUMED in t["markers"][0] or any(tt.ASSUMED in m for m in t["markers"])
    assert any(tt.VARIES in m for m in t["markers"])
    assert any("Not known" in r["cells"] for r in t["rows"])
    _check(t)


def test_host_with_no_value_uses_no_framework_terms(tmp_path):
    settings = dict(base.SETTINGS)
    s = dict(settings["ROTSQL1"])
    del s["time.poll"]
    settings["ROTSQL1"] = s
    settings["ROTSQL2"] = base.S("SRV1 (10.0.0.1)")
    settings["MOTSQL3"] = base.S("SRV1 (10.0.0.1)")
    settings["ROTAPP1"] = base.S("SRV1 (10.0.0.1)")
    t = base.build(tmp_path, settings=settings)
    assert "not known for ROTSQL1" in t["common"]
    _check(t)
