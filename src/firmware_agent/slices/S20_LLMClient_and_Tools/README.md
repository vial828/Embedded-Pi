# S20 - LLM Client

Status: implemented (`client.py`). One provider (`openai_compatible`), deterministic,
fully recorded, and structurally unable to fake an answer.

## Contract (frozen in `epi-dev-plan-and-log.md` §4.2)

```python
client = LLMClient(config, project_root, transport=None, timeout=120)
resp = client.generate(LLMRequest(task_id, action, prompt_sha, context, expect="text"))
# -> LLMResponse(text, raw_path, model, prompt_sha)
```

`action` is `carry | elaborate | judge` - the classification the LLM standard uses
to decide what a call may produce. It is validated even though P0 only elaborates,
because every audit level hangs off it.

## Guarantees

| Failure mode | How it is prevented |
|---|---|
| A stub that reports success | `provider: stub` raises `ProviderUnavailable` before any transport call and writes no audit bundle |
| An unrecorded call | `task.json` + `input.numbered.txt` are written before the request; `output.raw` + `response.json` before the return |
| Rewritten history | A second call with the same `task_id` raises `AuditConflict`. A failed attempt leaves no `output.raw`, so it may be retried under the same id |
| Silent nondeterminism | `temperature=0` and `seed=0` are pinned in the request; `llm.temperature != 0` is rejected at config load |
| Credential leakage | The key comes from `EPI_LLM_API_KEY` only, never from the committed config, and a test asserts it appears in no audit file |
| Turning the harness off | `EPI_LLM_ENABLED=0` raises instead of quietly skipping |

## Notes

- `transport` is injectable. Tests use a fake transport for determinism and one
  real `HTTPServer` round trip so the actual urllib path stays covered.
- Nothing in P0 consumes this yet; the first real consumer is code generation
  (P0-6). The legacy `--run` agent is wired to it and fails loudly when no
  provider is configured, which is the point: it used to print `[stub] ...`.
- `Docs/ai-generation/audit/<task-id>/` is the audit bundle defined in
  `epi-llm-workflow-standard.md` §5. `mapping.json`, `audit.l0-l2.json` and the
  review files arrive with the PRD deep-parsing hook, not here.
