# S21 - Action Executor

Status: implemented (`action_executor.py`). The only slice that writes files or runs programs.

## Contract

```python
ex = ActionExecutor(project_root, task_id, allowed_executables=None)
ex.write_text("src/main.c", text) -> Path
ex.read_text("src/main.c") -> str
ex.run_command(["gcc", "-c", "src/main.c"], cwd=".", timeout=300) -> CommandResult
```

`CommandResult` carries `exit_code`, `stdout`, `stderr`, `duration_ms`, `timed_out`
and an `ok` property. There is deliberately **no `passed` field**: whether a result
is acceptable is the verifiers' job (S22-S24) and the quality gate's (S30).

## Rules

1. **Default-deny writes.** Only project-relative paths under `WRITABLE_PREFIXES`
   (`src/`, `include/`, `tests/`, `Docs/ai-generation/generated/`) may be written.
   Absolute paths, drive-qualified paths and anything resolving outside the
   project root are refused - including `Docs/prd`, `Docs/standards`, the workflow
   state, and the executor's own audit trail.
2. **Policy before I/O.** The check runs before the file is created. A refusal
   that still writes is the failure mode this slice exists to prevent, and a test
   pins it.
3. **Every action is logged**, successful, failed, or refused, to
   `Docs/ai-generation/audit/<task-id>/actions.jsonl` (the audit bundle location
   defined in `epi-llm-workflow-standard.md` §5). Sequence numbers continue across
   runs so two executors on one task cannot both claim action 1.
4. **Overwrites name their predecessor.** Each write records `previous_sha256`,
   so "the generator emptied the artifact" is a lookup instead of an excavation.
5. **No shell.** Commands run as argv lists with `shell=False`, inside the project,
   with a timeout. A shell would be a second, unlogged interpretation layer.
   A missing executable is returned as a result, not raised: "compiler not
   installed" has to be reportable by the verifier that found it.
6. **`allowed_executables`** is the control surface for callers acting on untrusted
   (model-produced) input - pass the configured toolchain binaries and nothing
   else. `None` means unrestricted and is only correct for trusted callers.

## Notes

`run_command` needs no LLM and no configuration, which is why P0-5 lands before
the code generator: it gives S22 a real compiler to fail against.
