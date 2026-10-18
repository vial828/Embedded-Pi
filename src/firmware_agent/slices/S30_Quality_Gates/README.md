# S30 - Quality Gates

Status: implemented (`quality_gate.py`). Judges the S29 report and writes
`Docs/ai-generation/reports/quality_gate.json`.

## Input and output

The gate reads the **report dictionary** from S29. It runs no tools, reads no
files, and reads no clock. If it recomputed its own facts it could disagree with
the report printed beside it, and a reviewer would have no way to tell which one
was lying.

```
evaluate(report, min_requirement_coverage=config.gate.min_requirement_coverage)
  -> GateVerdict(verdict="accepted" | "rejected", reasons=[...], not_judged=[...], metrics={...})
```

## Rules

| Rule | Rejects when |
|---|---|
| `no-stub-participation` | any stage produced no evidence (stub) |
| `no-failed-stage` | any stage failed |
| `architecture-coverage` | requirements the reviewed architecture does not map, **or** coverage was not evaluated |
| `traceability-complete` | a trace link is malformed or unknown, **or** traceability was `not-evaluated` |
| `requirement-coverage` | coverage below `gate.min_requirement_coverage` - only when configured |

`no-stub-participation` is the headline rule of this project: a run in which a
verifier was a stub cannot be certified, however green the other stages look. A
stub is an absence of evidence, and absences are what audits exist to catch.

`architecture-coverage` is the same argument one level up. A project whose design
document is still the generated template has an architecture that maps nothing, so
the run cannot be certified either - "the tests pass" says nothing about whether
the design accounts for the requirements. Note this is the gate judging a
*coverage report*, not the gate holding an opinion about design quality: it reads
`design_coverage` from the report and reports the reason it was given.

## `rejected` means "not certified", not "stop"

S23 is a stub today, so every run is rejected. If rejection blocked the workflow,
the only way to finish a run would be to remove the gate - precisely the pressure
that turns gates into decoration.

So the verdict is recorded instead: `state.json` carries `quality_gate`,
`quality_gate.json` carries the reasons, and CI (S31) fails on it. Work proceeds
and stays inspectable; certification is withheld until the evidence exists.

## A rule that cannot be judged is not a pass

`gate.min_requirement_coverage` defaults to unset. Unset does not become 0.0 (a
free pass) or 1.0 (this project inventing a quality bar the customer never set):
the rule lands in `not_judged` with the reason, and the report says
`not-configured`. An unjudgeable rule that reads as satisfied is the same failure
as a stub that reports success.

## Not here yet

Per-requirement gate thresholds, the CI matrix (S31), and gate policy as a
reviewed artifact rather than a config file.
