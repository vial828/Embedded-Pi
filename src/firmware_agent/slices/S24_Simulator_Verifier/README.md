# S24 - Host Test Runner (minimal simulator verifier)

Status: implemented (`simulator_verifier.py`). Replaces the `passed=True` stub for
the host-side part of the `test` phase.

## What it does

1. Collects `tests/**/*_test.c` in sorted order.
2. Builds each with `toolchain.host_compiler` plus every `src/**/*.c`, `-I include`.
3. Runs the resulting binary with a timeout; exit code 0 is the only pass.
4. Reports per-test `PASS`/`FAIL`/`BUILD FAILED` with the program's own output,
   and returns `passed = every test built and passed`.

Build and run both go through the S21 executor, so argv, exit codes and output
land in `Docs/ai-generation/audit/hosttest-<task>/actions.jsonl`.

## Test convention

`#include <assert.h>`, a `main()`, return 0. No harness and no generated
framework: the C standard library already asserts, and inventing a test framework
would be this project generating content it is supposed to only wire up.

We never pass `-DNDEBUG`, because that silently turns every `assert` into a no-op
and would make a suite of assertions pass vacuously.

## Verdicts

| Situation | Result |
|---|---|
| No `*_test.c` under `tests/` | `passed=False` - a suite that collected nothing proves nothing |
| Tests exist, `toolchain.host_compiler` unset | `passed=False`, naming the setting. A cross compiler cannot build a runnable binary, so this is not something to default |
| Test does not compile | `passed=False` with `BUILD FAILED` and the compiler diagnostic - never a skip |
| Test hangs | `passed=False` with `timed_out` after the configured timeout |
| One failing case among passing ones | `passed=False`, both lines kept in the report |

## Not here yet

Running on the target/simulator, coverage measurement, and per-test-module link
lists (today every test links all of `src/`, which is simple and fails loudly when
that is wrong).
