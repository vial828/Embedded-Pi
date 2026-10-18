# S29 - Test Report Output

Status: implemented (`test_report.py`). Consumes the verdicts from S22/S23/S24 and
writes `Docs/ai-generation/reports/test_report.json` + `.md`.

## What this slice owns

Two joins and nothing else:

1. lay the verifier verdicts out, and
2. join **declared** requirement links to test cases.

It runs no tools, decides no verdicts, and infers nothing. `semantic_inference:
forbidden` in the design constitution applies hardest here, because a report is
exactly where a guessed link would read as a fact.

## Declaring a requirement link

```c
/* requires: R-001, R-004 */
```

The link lives in the test file so it moves with the code, and it is a comment so
the compiler ignores it. IDs come from the S09 requirements index.

| Situation | Report says |
|---|---|
| Link resolves | requirement `covered`, test file listed under it |
| Requirement has no link | `untested`, counted in `requirements_untested` |
| Malformed (`R-1`, a typo) | `malformed_links`, traceability `broken` - never dropped, because dropping it would make the report clean |
| Unknown ID (`R-999`) | `unknown_ids`, traceability `broken` - a renumbered PRD shows up here instead of pointing at the wrong row |
| Index missing, unparseable, or `requirements: []` | traceability `not-evaluated` with the reason |

`not-evaluated` is not `complete`. S02 scaffolds an index with an empty list, so
"file present" does not mean "PRD ingested", and reporting complete coverage of
zero requirements is a vacuous truth.

## What a stage verdict is not

Every stage row carries `n/a (whole-project gate)` in the requirements column. A
whole-build compile verdict is not evidence about one requirement, and inventing
that association would be the report's own inference.

## `design_coverage`: the architecture half of the trace

`build_report(root, verdicts, design_coverage)` takes the S04 coverage dictionary
as an argument. S04 is not imported here: S04 already reads this module's
requirements loader, so reaching back would be a cycle - and a report should record
the design, not form opinions about it.

The section is always present. A caller that never ran the check gets
`{"status": "not-evaluated", "reason": "caller did not run the architecture
coverage check"}`, because a section that silently goes missing reads as "nothing to
report". S30 turns `incomplete` and `not-evaluated` both into rejections.

## Determinism

The markdown is rendered from the same dictionary as the JSON, so the two cannot
disagree, and neither carries a wall-clock timestamp: identical inputs produce
byte-identical files (asserted by test).

## Not here yet

Requirement→module→code traceability (needs the P0-3 module manifest decision),
coverage thresholds (S30 policy), and the decision log (S28).
