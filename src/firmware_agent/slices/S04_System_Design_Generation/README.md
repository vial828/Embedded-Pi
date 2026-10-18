# S04 - System Design Generation

Status: **partial**. `requirement_coverage.py` implements the checkable half of
P0-3. Generation of the design itself is deliberately not implemented - see
"Open ruling" below.

## What exists

`check_project(project_root)` joins `requirements_index.json` against the
requirement-bearing columns of the design tables (`MODULE_DESIGN_TABLE`,
`TASK_TABLE`, `INTERFACE_TABLE` `req_ids`) and answers one question: which
requirements does the reviewed architecture not account for?

```
Coverage(evaluated, reason, assigned, unassigned, unknown_refs, placeholder_rows)
  .status -> "complete" | "incomplete" | "not-evaluated"
```

The workflow calls it at `wait_for_design_review`, before asking for approval, and
records the status in `state.json`. A warning, not a gate - see below.

## Rules inherited from S29/S30

- **`not-evaluated` is its own state.** No ingested PRD, or no design document, is
  reported as such. "0 unassigned" for a project with no requirements is a vacuous
  truth.
- **An untouched template is not a design.** The check compares the document
  byte-for-byte against the template S02 generates - the same provenance trick as
  `template: true` in `config.yaml`. No content heuristic can do this: the
  template's example rows look real (`IF-001 / sensor_q`), so a scaffold would
  otherwise pass as a design.
- **A scaffold row claims nothing.** A row whose own `name` or id is `N/A` came
  from the generator, not from a designer.
- **Broken references are named, never dropped.** `R-999` in a `req_ids` cell is
  reported with its claimant (`module:MOD-001`); dropping it would turn a broken
  trace into a clean report.

## Manifest source: implemented as B, pending confirmation

Where the module manifest lives was undecided (**A** a human-authored
`module-design.md`, **B** `system-design.md` stays the sole source and S04 only
checks coverage, **C** a new `config/architecture.yaml`).

The code ships **B**, because the evidence points there and idling helps nobody:
the canonical schema *already* has `req_ids` on module/task/interface rows and a
`TRACEABILITY_LINKS` section, S06 already validates those IDs, and the workflow
already has a human review gate (`wait_for_design_review`) which is where a person
fills the table in. Option A would give one fact two homes.

This is reversible by construction, not by refactor: `evaluate_coverage(requirements,
design)` is source-agnostic and `check_project` is the only function that knows where
the rows come from. If the ruling goes to A or C, `check_project` is replaced and
nothing else moves - including the S30 rule, which reads the coverage report rather
than the design document.

The gate consequence is `architecture-coverage` in S30: an architecture that maps
nothing cannot certify a run, which is the same reasoning as refusing to certify one
where a verifier was a stub.

## Not here

Generating design content from requirements. `semantic_inference: forbidden` - the
agent may report that a requirement is unmapped, it may not invent the module that
would map it.
