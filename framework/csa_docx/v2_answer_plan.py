"""Explicit answer plans for the V2 evidence-led writer."""
from __future__ import annotations

import json
from pathlib import Path

VERSION = "v2-answer-plan-v1"


def build_plan(card: dict, slices: dict[str, dict]) -> dict[str, dict]:
    obligations = (card.get("obligations") or {}).get("blocks", {})
    out = {}
    for question in card.get("questions", []):
        if not isinstance(question, dict) or not question.get("id"):
            continue
        qid = str(question["id"])
        block = obligations.get(qid, {}) if isinstance(obligations, dict) else {}
        slice_data = slices.get(qid, {})
        preserved = [
            {"fact": item.get("fact", ""), "evidence_ids": item.get("evidence_ids", [])}
            for item in block.get("must_preserve", []) if isinstance(item, dict)
        ]
        optional = [
            {"slot": item.get("slot", ""), "text": item.get("text", ""),
             "evidence_ids": item.get("evidence_ids", [])}
            for item in block.get("findings", []) if isinstance(item, dict) and item.get("text")
        ]
        out[qid] = {
            "plan_version": VERSION,
            "block": qid,
            "question": question,
            "required_points": preserved,
            "optional_points": optional,
            "known_gaps": [],
            "conflicts": slice_data.get("conflicts", []),
            "allowed_evidence_ids": list(slice_data.get("allowed_evidence_ids", [])),
            "rating_options": list(block.get("ratings") or card.get("ratings") or []),
            "rating_basis": "requirement rating must be supported by the required points and evidence"
            if question.get("kind") == "requirement" else "describe the evidenced current state",
            "table_columns": list(block.get("table_columns") or []),
        }
    return out


def write_plan(directory: str | Path, plan: dict[str, dict]) -> tuple[str, str]:
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    json_path = root / "answer-plan.json"
    md_path = root / "answer-plan.md"
    json_path.write_text(json.dumps({"plan_version": VERSION, "blocks": plan}, indent=2, ensure_ascii=False) + "\n",
                          encoding="utf-8")
    lines = ["# V2 answer plan", "", "The framework selects the evidence and the writer executes this plan.", ""]
    for qid, item in plan.items():
        lines += [f"## {qid}", "", item["question"].get("text", ""), "", "### Required points", ""]
        for point in item["required_points"]:
            lines.append(f"- {point['fact']} ({', '.join(point['evidence_ids'])})")
        lines += ["", "### Optional points", ""]
        for point in item["optional_points"]:
            lines.append(f"- {point['text']} ({', '.join(point['evidence_ids'])})")
        lines += ["", f"Allowed evidence: {', '.join(item['allowed_evidence_ids'])}",
                  f"Rating basis: {item['rating_basis']}", ""]
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return str(json_path), str(md_path)
