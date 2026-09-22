# Embedded-Pi / firmware-agent

M0 bootstrap for an autonomous embedded firmware development agent.

## Quick start

```bash
python -m venv .venv
source .venv/Scripts/activate  # Windows Git Bash
pip install -e .[dev]
epi C:/path/to/project
epi C:/path/to/project --reset-schema-template
epi C:/path/to/project --schema-compile
```

## Current scope (M0)

- Project skeleton and CLI entrypoint
- `epi /path/to/project`: check project layout against plan and auto-create missing tree/files under `Docs/`
- authoritative schema file: `Docs/ai-generation/fw-architecture/system-design/system-design.md` (strict format, no semantic free-text parsing)
- `epi /path/to/project --reset-schema-template`: force overwrite canonical `system-design.md` template
- `epi /path/to/project --schema-compile`: run fixed parser/validator and emit deterministic JSON outputs
- two-layer memory is persisted under `Docs/ai-generation/memory/`:
  - short memory: `working_memory.json`
  - long memory: `long_memory.json` (decisions/constraints/traceability)
- deterministic promotion support data is under `Docs/ai-generation/knowledge/`:
  - `rules.json`, `requirements_index.json`, `register_index.json`, `artifact_graph.json`
  - long-memory promotion is decided by rule engine (LLM proposes, program decides)
- Typed config loading and validation
- Basic state/task models
- Context assembler scaffold
- Verifier/Executor/LLM client stubs

## Next

Implement Phase 0 end-to-end flow:
1. Generate UART driver files
2. Write files to output
3. Compile and retry on failure
