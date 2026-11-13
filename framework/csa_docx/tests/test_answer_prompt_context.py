import json
import runpy
from pathlib import Path


CSA = runpy.run_path(str(Path(__file__).parents[3] / "bin" / "csa"))


def test_answer_prompt_contains_bounded_contract_and_block_obligations(tmp_path):
    work = tmp_path / "csa-work-v2"; (work / "cards").mkdir(parents=True)
    card = work / "cards" / "X.md"; card.write_text("# X\n", encoding="utf-8")
    card.with_suffix(".json").write_text(json.dumps({
        "questions": [{"id": "B1", "kind": "observation", "text": "What?"}],
        "evidence": {"B1": {"rows": [{"id": "E-1", "claim": "x"}]}},
        "obligations": {"contract_version": "answer-contract-v1", "blocks": {"B1": {"evidence_ids": ["E-1"]}}}
    }), encoding="utf-8")
    p = {"key": "x", "label": "X", "project_context": str(tmp_path / "context.yaml"),
         "work_dir": str(work), "project_root": str(tmp_path)}
    route = {"verb": "answer", "file": "csa-answer-agent.md", "title": "CSA Answer Agent",
             "inputs": "SECTION, CARD*, SHEET*, MODE=answer", "local_inputs": ""}
    prompt = CSA["build_prompt"](p, route, ["1", f"CARD={card}", f"SHEET={work / 'X.answer.md'}"], local=False)
    assert "ANSWER CONTRACT: answer-contract-v1" in prompt
    assert '"evidence_ids":["E-1"]' in prompt
    assert "CONTEXT_VERSION=answer-contract-v1" in prompt


def test_answer_prompt_obligation_context_is_scoped_to_only_blocks(tmp_path):
    work = tmp_path / "csa-work-v2"; (work / "cards").mkdir(parents=True)
    card = work / "cards" / "X.md"; card.write_text("# X\n", encoding="utf-8")
    card.with_suffix(".json").write_text(json.dumps({
        "questions": [{"id": "B1", "kind": "observation"}, {"id": "B2", "kind": "observation"}],
        "evidence": {"B1": {"rows": [{"id": "E-1"}]}, "B2": {"rows": [{"id": "E-2"}]}}
    }), encoding="utf-8")
    p = {"key": "x", "label": "X", "project_context": str(tmp_path / "context.yaml"),
         "work_dir": str(work), "project_root": str(tmp_path)}
    route = {"verb": "answer", "file": "csa-answer-agent.md", "title": "CSA Answer Agent",
             "inputs": "SECTION, CARD*, SHEET*, MODE=answer, ONLY", "local_inputs": ""}
    prompt = CSA["build_prompt"](p, route, ["1", f"CARD={card}", f"SHEET={work / 'X.answer.md'}", "ONLY=B1"], local=False)
    assert '"B1"' in prompt and '"B2"' not in prompt
