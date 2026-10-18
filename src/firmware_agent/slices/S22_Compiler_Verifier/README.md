# S22 - Compiler Verifier

Status: implemented (`compiler_verifier.py`). Replaces the stub that returned
`passed=True` for every task, which is what made the whole `test` phase fake.

## Contract

```python
result = CompilerVerifier(config, project_root).verify("Compile generated firmware")
# VerifyResult(passed, output, stub=False, tool, duration_ms, commands)
```

`VerifyResult` is shared with S23/S24. Its `__post_init__` raises if
`stub=True and passed=True`: a stub cannot hand out a pass, which is the rule the
previous stubs broke.

## What it does

1. Reads the compiler from S03 config (`toolchain.compiler`) - never defaults it.
2. Collects `src/**/*.c` in sorted order (deterministic).
3. Runs `<compiler> --version` once, then one `-c` compile per source into
   `build/objects/…`, each through the S21 executor so argv and exit code land in
   `Docs/ai-generation/audit/compile-<task>/actions.jsonl`.
4. Returns `passed = every source compiled`, carrying the compiler's own
   diagnostics in `output`.

## What it refuses to do

| Situation | Verdict |
|---|---|
| No sources under `src/` | `passed=False` - zero work is not a clean build |
| No project root configured | `passed=False` - it will not invent a verdict |
| Compiler binary missing | `passed=False`, and `tool` says which binary it tried |
| One bad file among many | `passed=False`, with the per-file line and the compiler diagnostic |

## Not here yet

Target flags (`-mcpu`, `-mthumb`, linker script) and multi-file link steps. Those
are configuration decisions for the real MCU target; this slice performs a
compile-only check with whatever compiler the project declared, which is enough to
make "it builds" mean something before moving on to host tests (P0-7).
