from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import json

from firmware_agent.slices.S14_Candidate_Memory.candidate_memory import CandidateMemory


@dataclass
class PromotionDecision:
    candidate_id: str
    approved: bool
    score: int
    reasons: list[str] = field(default_factory=list)


class PromotionRuleEngine:
    """Deterministic promotion engine: LLM can propose, engine decides."""

    HIGH_RISK_SIGNALS = {
        "compile_error",
        "link_error",
        "runtime_crash",
        "behavior_error",
        "static_analysis_error",
        "hil_fail",
    }

    def __init__(self, docs_root: Path):
        self.knowledge_dir = docs_root / "ai-generation" / "knowledge"
        self.knowledge_dir.mkdir(parents=True, exist_ok=True)

    def _load_known_source_ids(self) -> set[str]:
        ids: set[str] = set()
        for name, key in [
            ("rules.json", "rules"),
            ("requirements_index.json", "requirements"),
            ("register_index.json", "register_items"),
        ]:
            p = self.knowledge_dir / name
            if not p.exists():
                continue
            data = json.loads(p.read_text(encoding="utf-8") or "{}")
            for item in data.get(key, []):
                sid = item.get("source_id") or item.get("id")
                if sid:
                    ids.add(str(sid))
        return ids

    def decide(self, c: CandidateMemory, approve_threshold: int = 70) -> PromotionDecision:
        score = 0
        reasons: list[str] = []

        known_ids = self._load_known_source_ids()
        if c.evidence_source_ids and all(sid in known_ids for sid in c.evidence_source_ids):
            score += 35
            reasons.append("authoritative_source_id_verified")
        else:
            reasons.append("source_id_missing_or_not_whitelisted")

        if len(set(c.affected_artifacts)) >= 2:
            score += 25
            reasons.append("cross_artifact_impact_detected")

        if any(sig in self.HIGH_RISK_SIGNALS for sig in c.risk_signals):
            score += 25
            reasons.append("high_failure_cost_signal_detected")

        if c.recall_count_recent_n >= 3:
            score += 15
            reasons.append("high_reuse_frequency_detected")

        approved = score >= approve_threshold and "source_id_missing_or_not_whitelisted" not in reasons
        return PromotionDecision(candidate_id=c.candidate_id, approved=approved, score=score, reasons=reasons)
