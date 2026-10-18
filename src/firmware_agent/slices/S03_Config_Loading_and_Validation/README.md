# S03 Config-Loading-and-Validation

Status: implemented (`config.py`, loaded by the workflow and re-exported as `firmware_agent.config`).

## Contract

Two rules hold the module together.

1. **No silent defaults for anything that changes what runs.** `project.name`,
   `mcu.part`, `toolchain.compiler`, `llm.provider`, `llm.model` are required and
   each carries the reason it may not be defaulted, printed with the error.
   Defaults are allowed only where they change cost or budget, not what gets
   produced (token budgets, `paths`, `gate`).
2. **"Still the generated template" is a recorded fact.** S02 stamps
   `template: true` into the config it generates; S03 reads that stamp instead of
   sniffing values. Strict validation and a scaffolded project therefore coexist:
   the loader reports "structurally valid, not yet configured".

## Behaviour

- `load_project_config(root)` resolves `Docs/config.yaml`, then root `config.yaml`;
  a missing config is an error listing every path tried.
- Unknown keys are rejected, and a missing required key next to a near-miss key is
  reported as a probable typo.
- `llm.provider` must be in `SUPPORTED_PROVIDERS`; an unknown provider would
  otherwise ship project source to a model nobody chose.
- `paths.*` must stay project-relative (no absolute paths, drive letters, or `..`)
  so one project directory works on both development machines.
- `toolchain.resolved_objcopy()` derives objcopy from the compiler, keeping its
  directory; a non-gcc compiler must state objcopy explicitly.
- `gate.allow_missing_inputs` is the persistent, checked-in input waiver. The
  workflow records which authority waived (`waived_by: config|cli`) so a waived run
  never looks like a gated one.

## Consumers

`workflow.py` (gate + config report), `agent.py` (legacy `--run`), S17 context
assembler (typed on `AppConfig`).
