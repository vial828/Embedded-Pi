from pathlib import Path
import json

from firmware_agent.memory.promotion import CandidateMemory, PromotionRuleEngine
from firmware_agent.project_layout import ensure_project_layout


def test_promotion_rule_engine_requires_whitelisted_source_ids(tmp_path: Path):
    project = tmp_path / "promotion-demo"
    ensure_project_layout(project)
    docs = project / "Docs"

    knowledge = docs / "ai-generation" / "knowledge"
    rules = {"version": "0.1", "rules": [{"source_id": "STD-ISR-001", "rule": "no printf in isr"}]}
    (knowledge / "rules.json").write_text(json.dumps(rules), encoding="utf-8")

    engine = PromotionRuleEngine(docs)

    bad = CandidateMemory(
        candidate_id="CAND-1",
        content="ISR no printf",
        evidence_source_ids=["UNKNOWN-ID"],
        affected_artifacts=["mod:a", "mod:b"],
        risk_signals=["runtime_crash"],
        recall_count_recent_n=5,
    )
    d1 = engine.decide(bad)
    assert not d1.approved

    good = CandidateMemory(
        candidate_id="CAND-2",
        content="ISR no printf",
        evidence_source_ids=["STD-ISR-001"],
        affected_artifacts=["mod:a", "mod:b"],
        risk_signals=["runtime_crash"],
        recall_count_recent_n=5,
    )
    d2 = engine.decide(good)
    assert d2.approved
