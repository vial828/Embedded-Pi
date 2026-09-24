from __future__ import annotations

from firmware_agent.slices.S13_Long_Memory.long_memory import LongMemory
from firmware_agent.state import Task


def build_memory_pack(long_memory: LongMemory, task: Task, max_items: int = 5) -> str:
    """Return minimal long-memory pack relevant to current task."""
    periph = (task.peripheral or "").lower()
    req = (task.requirement_id or "").strip()

    decision_candidates = long_memory.decisions
    if periph:
        decision_candidates = [
            d for d in decision_candidates if any(periph in tag.lower() for tag in d.tags)
        ] or decision_candidates
    if req:
        decision_candidates = [
            d for d in decision_candidates if req in d.content or req in d.rationale
        ] or decision_candidates

    decisions = decision_candidates[-max_items:]
    constraints = long_memory.constraints[-max_items:]
    traces = long_memory.traceability[-max_items:]

    lines: list[str] = ["LongMemory:"]

    if decisions:
        lines.append("Decisions:")
        for d in decisions:
            lines.append(f"- {d.decision_id}: {d.content} | reason={d.rationale}")

    if constraints:
        lines.append("Constraints:")
        for c in constraints:
            lines.append(f"- {c.constraint_id}: ({c.severity}) {c.rule}")

    if traces:
        lines.append("Traceability:")
        for t in traces:
            lines.append(
                f"- {t.req_id} -> {t.artifact_type}:{t.artifact_ref} [{t.status}]"
            )

    if len(lines) == 1:
        lines.append("- N/A")

    return "\n".join(lines)
