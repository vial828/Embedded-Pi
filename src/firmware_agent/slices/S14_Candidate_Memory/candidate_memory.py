from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CandidateMemory:
    candidate_id: str
    content: str
    evidence_source_ids: list[str] = field(default_factory=list)
    affected_artifacts: list[str] = field(default_factory=list)
    risk_signals: list[str] = field(default_factory=list)
    recall_count_recent_n: int = 0
