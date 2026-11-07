import csv

from csa_docx import host_settings as H
from csa_docx import topic_tables as T

PROFILE = {"kind": "sets", "attribute": "gpo.applied", "attribute_not": "gpo.not_applied", "key": "GPO", "columns": []}


def _work(tmp_path, applied, not_applied=None):
    (tmp_path / "hosts").mkdir()
    with (tmp_path / "hosts" / "hosts.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["host", "role", "site", "in_scope", "capture"])
        for h, role in (("H1", "Log Server, DAAM"), ("H2", "Log Server, DAAM"), ("H3", "Jump Host")):
            w.writerow([h, role, "A", "yes", "x"])
    with (tmp_path / "hosts" / "host_settings.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=H.FIELDS)
        w.writeheader()
        for h, v in applied.items():
            w.writerow({"host": h, "topic": "group_policy", "attribute": "gpo.applied", "value": v})
        for h, v in (not_applied or {}).items():
            w.writerow({"host": h, "topic": "group_policy", "attribute": "gpo.not_applied", "value": v})
    return tmp_path


def test_baseline_members_show_once_as_a_set_and_the_rest_are_listed(tmp_path):
    base = "2019 Prod - Baseline GPO, 2019 Prod - Baseline Firewall, 2019 Prod - Baseline Restricted Groups"
    w = _work(tmp_path, {"H1": f"Common, {base}, Log FW", "H2": f"Common, {base}, Log FW", "H3": f"Common, {base}, Jump FW"},
              {"H3": "Audit GPO"})
    t = T.build_sets(w, "Group Policy Observations", "", PROFILE)
    assert t["columns"] == ["Role", "Hosts", "Baseline set", "Role-specific policies"]
    rows = {(r["role"], tuple(r["hosts"])): r["cells"] for r in t["rows"]}
    assert rows[("Log Server", ("H1", "H2"))] == ["2019 baseline", "Log FW"]
    assert rows[("Jump Host", ("H3",))] == ["2019 baseline", "Jump FW"]
    assert t["common"].startswith("Applied by all 3 hosts: ") and "Common" in t["common"]
    assert any("Audit GPO" in m and "H3" in m for m in t["markers"])


def test_hosts_of_one_role_that_differ_get_their_own_row(tmp_path):
    w = _work(tmp_path, {"H1": "Common, A GPO", "H2": "Common, B GPO", "H3": "Common"})
    t = T.build_sets(w, "Group Policy Observations", "", PROFILE)
    log_rows = [r for r in t["rows"] if r["role"] == "Log Server"]
    assert len(log_rows) == 2 and log_rows[0]["first"] and not log_rows[1]["first"]
