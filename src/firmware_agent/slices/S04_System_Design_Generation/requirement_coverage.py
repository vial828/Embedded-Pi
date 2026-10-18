"""S04 (partial) - requirement -> architecture coverage over the design tables.

The acceptance criterion for P0-3 is "every requirement hangs on at least one
module; leftovers go to `unassigned` with a warning". The *source* of the module
manifest is still an open ruling (options A/B/C in `epi-dev-plan-and-log.md` §3),
but what every option needs afterwards is identical: join the requirements index
against the design's `req_ids` columns and report what is left over. Only the
adapter that produces the rows differs per option, so the ruling should cost one
function here, not a rewrite.

## Rules, inherited from S29/S30

- **Not-evaluated is a state of its own.** A missing requirements index, an index
  with no requirements (S02 scaffolds one), or an unparseable design yields
  `evaluated=False` with a reason. Reporting "0 unassigned" for a project whose
  PRD was never ingested is a vacuous truth.
- **A scaffold row is not an assignment.** The generated template row carries
  `name = N/A` and a sample `req_ids`. Counting it would certify a project whose
  design nobody has written yet - the same trap as a template config that loads
  with defaults.
- **Bad references are reported, never dropped.** A `req_ids` cell naming an ID
  that is not in the index is a broken trace; dropping it turns a broken trace
  into a clean report.
- **Deterministic.** Sorted output, no clock, no environment.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from firmware_agent.slices.S02_Project_Layout_and_Template_Generation.project_layout import (
    SYSTEM_DESIGN_TEMPLATE,
)
from firmware_agent.slices.S05_Parser.parser import parse_system_design
from firmware_agent.slices.S29_Test_Report_Output.test_report import (
    load_requirements_index,
)

__all__ = ["SYSTEM_DESIGN_RELATIVE", "Coverage", "check_project", "evaluate_coverage"]

SYSTEM_DESIGN_RELATIVE = "Docs/ai-generation/fw-architecture/system-design/system-design.md"

# Sections whose rows may claim requirements.
CLAIM_SECTIONS = ("MODULE_DESIGN_TABLE", "TASK_TABLE", "INTERFACE_TABLE")
_SECTION_ARTIFACT = {"MODULE_DESIGN_TABLE": "module", "TASK_TABLE": "task", "INTERFACE_TABLE": "interface"}

# A cell value meaning "not filled in yet". `N/A` is the project's constitution
# value for unknown (`unknown_value_policy: use_N/A`), so it can never mean linked.
PLACEHOLDER_CELLS = {"", "N/A", "n/a", "na", "-", "--"}

_REQ_ID_RE = re.compile(r"^R-\d{3,}$")


@dataclass(frozen=True)
class Coverage:
    evaluated: bool
    reason: str = ""
    assigned: dict[str, list[str]] = field(default_factory=dict)
    unassigned: list[str] = field(default_factory=list)
    unknown_refs: list[dict[str, Any]] = field(default_factory=list)
    placeholder_rows: int = 0

    @property
    def status(self) -> str:
        """not-evaluated | incomplete | complete - never a bare pass."""
        if not self.evaluated:
            return "not-evaluated"
        if self.unassigned or self.unknown_refs:
            return "incomplete"
        return "complete"

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": "epi.requirement-coverage/1",
            "status": self.status,
            "reason": self.reason,
            "requirements_total": len(self.assigned) + len(self.unassigned),
            "assigned": {req_id: sorted(claims) for req_id, claims in sorted(self.assigned.items())},
            "unassigned": list(self.unassigned),
            "unknown_refs": list(self.unknown_refs),
            "placeholder_rows": self.placeholder_rows,
        }


def _cells_of(row: Any) -> dict[str, str]:
    """`parse_table` yields rows as dicts keyed by header; normalise the cells."""
    return {key: (value or "").strip() for key, value in row.items()}


def _identity_of(section: str, row: dict[str, str]) -> str:
    artifact = _SECTION_ARTIFACT[section]
    key = row.get("module_id") or row.get("task_id") or row.get("if_id") or "?"
    return f"{artifact}:{key}"


def _is_placeholder_row(section: str, row: dict[str, str]) -> bool:
    """A row whose own identity is still `N/A` came from the scaffold, not from a designer."""
    if row.get("name", "").strip() in PLACEHOLDER_CELLS:
        return True
    identity = row.get("module_id") or row.get("task_id") or row.get("if_id")
    return (identity or "").strip() in PLACEHOLDER_CELLS


def evaluate_coverage(
    requirements: list[dict[str, Any]],
    design: dict[str, Any],
    *,
    design_label: str = SYSTEM_DESIGN_RELATIVE,
) -> Coverage:
    """Join the requirements index against the design tables. Pure: no files, no clock."""
    if not requirements:
        return Coverage(evaluated=False, reason="no requirements to map - PRD not ingested")

    known = {item.get("req_id") for item in requirements}
    assigned: dict[str, list[str]] = {}
    unknown_refs: list[dict[str, Any]] = []
    placeholder_rows = 0

    for section in CLAIM_SECTIONS:
        table = design.get(section) or {}
        headers, rows = table.get("headers") or [], table.get("rows") or []
        if "req_ids" not in headers:
            unknown_refs.append({"section": section, "problem": "table has no req_ids column"})
            continue

        for raw in rows:
            row = _cells_of(raw)
            if _is_placeholder_row(section, row):
                placeholder_rows += 1
                continue

            claimant = _identity_of(section, row)
            for token in re.split(r"[,\s]+", row.get("req_ids", "").strip()):
                if not token or token.strip().lower() in {"n/a", "na", "-", "--"}:
                    continue
                if not _REQ_ID_RE.match(token):
                    unknown_refs.append(
                        {"section": section, "claimant": claimant, "declared": token, "problem": "malformed requirement id"}
                    )
                    continue
                if token not in known:
                    unknown_refs.append(
                        {"section": section, "claimant": claimant, "declared": token, "problem": "unknown requirement id"}
                    )
                    continue
                assigned.setdefault(token, []).append(claimant)

    unassigned = [item["req_id"] for item in requirements if item["req_id"] not in assigned]
    if placeholder_rows and len(unassigned) == len(requirements):
        reason = f"{design_label} still holds {placeholder_rows} scaffold row(s) - no design has been reviewed yet"
    else:
        reason = ""

    return Coverage(
        evaluated=True,
        reason=reason,
        assigned=assigned,
        unassigned=unassigned,
        unknown_refs=unknown_refs,
        placeholder_rows=placeholder_rows,
    )


def check_project(project_root: Path) -> Coverage:
    """Adapter for the current source of truth: `system-design.md` tables.

    If the manifest ruling goes to a separate module-design document or a config
    file, this function is what changes - `evaluate_coverage` is already source-agnostic.
    """
    requirements, unavailable = load_requirements_index(project_root)
    if unavailable:
        return Coverage(evaluated=False, reason=unavailable)

    path = project_root / SYSTEM_DESIGN_RELATIVE
    if not path.exists():
        return Coverage(evaluated=False, reason=f"{SYSTEM_DESIGN_RELATIVE} does not exist")

    text = path.read_text(encoding="utf-8")
    if text.strip() == SYSTEM_DESIGN_TEMPLATE.strip():
        # Exact comparison against the template S02 generates - the same provenance
        # trick as `template: true` in config.yaml. Example rows in that template look
        # plausible (IF-001 / sensor_q), so no content heuristic can tell a scaffold
        # from a design; the bytes can.
        return Coverage(evaluated=False, reason=f"{SYSTEM_DESIGN_RELATIVE} is still the generated template - no design has been reviewed yet")

    try:
        design = parse_system_design(path)
    except Exception as error:  # noqa: BLE001 - converted to a verdict, not swallowed; an
        # unparseable design must report not-evaluated rather than "everything is covered"
        return Coverage(evaluated=False, reason=f"{SYSTEM_DESIGN_RELATIVE} could not be parsed: {error}")

    return evaluate_coverage(requirements, design)
