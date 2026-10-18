"""S20 - LLM client. One provider, deterministic, fully recorded, and unable to lie.

The client exists to make three things impossible:

1. **A stub that reports success.** `provider: stub` raises. It never returns
   placeholder text, because a `[stub]` string flowing into a code generator is
   how a broken pipeline looks green (that is the incident pattern in §6 of the
   dev plan).
2. **An unrecorded call.** Every attempt writes an audit bundle under
   `Docs/ai-generation/audit/<task-id>/` before returning: `task.json` (the
   contract), `input.numbered.txt` (anchored input) and `output.raw` (the model's
   bytes, never rewritten). A second attempt with the same task id is refused -
   retries are a new attempt, not an overwrite.
3. **A silent nondeterministic run.** Requests pin `temperature=0` and a fixed
   seed. Configuration may not ask for sampling: a knob that changes
   reproducibility without saying so is the same class of silent default that S03
   was built to remove.

Credentials come from the environment only. The project config is committed to
git, so a key in it is a leaked key; the audit bundle deliberately never contains
the request headers.
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from firmware_agent.config import AppConfig

__all__ = [
    "AUDIT_RELATIVE_ROOT",
    "AuditConflict",
    "LLMClient",
    "LLMRequest",
    "LLMResponse",
    "ProviderUnavailable",
    "prompt_sha_of",
]

AUDIT_RELATIVE_ROOT = "Docs/ai-generation/audit"
ACTIONS = ("carry", "elaborate", "judge")
API_KEY_ENV = "EPI_LLM_API_KEY"
ENABLED_ENV = "EPI_LLM_ENABLED"
TRUTHY = {"1", "true", "yes", "on"}


class ProviderUnavailable(Exception):
    """No usable answer from the provider: disabled, unconfigured, unreachable.

    Callers must surface this as a failure. There is no fallback text, by design.
    """


class AuditConflict(Exception):
    """The audit bundle for this task id already holds an output."""


@dataclass(frozen=True)
class LLMRequest:
    task_id: str
    action: str
    prompt_sha: str
    context: str
    expect: str = "text"  # text | json | std_format


@dataclass(frozen=True)
class LLMResponse:
    text: str
    raw_path: Path
    model: str
    prompt_sha: str


class Transport(Protocol):
    def post_json(self, url: str, payload: dict[str, Any], headers: dict[str, str], timeout: int) -> tuple[int, dict]:
        ...


class UrllibTransport:
    """The real transport. Kept this thin so tests can substitute a recorder."""

    def post_json(self, url: str, payload: dict[str, Any], headers: dict[str, str], timeout: int) -> tuple[int, dict]:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"content-type": "application/json", **headers},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:  # 4xx/5xx still carry a body worth auditing
            body = exc.read().decode("utf-8", errors="replace")
            try:
                return exc.code, json.loads(body)
            except json.JSONDecodeError:
                return exc.code, {"error": body}
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise ProviderUnavailable(f"provider request failed: {exc}") from exc


def prompt_sha_of(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class LLMClient:
    def __init__(
        self,
        config: AppConfig,
        project_root: str | Path,
        *,
        transport: Transport | None = None,
        timeout: int = 120,
    ):
        self.config = config
        self.project_root = Path(project_root)
        self.transport = transport or UrllibTransport()
        self.timeout = timeout

    # ------------------------------------------------------------------ api

    def generate(self, req: LLMRequest) -> LLMResponse:
        self._check_preconditions(req)

        bundle = self.audit_dir(req.task_id)
        raw_path = bundle / "output.raw"
        if raw_path.exists():
            raise AuditConflict(
                f"{raw_path} already exists. A retried attempt needs a new task_id - "
                "overwriting an audit output would destroy the evidence it records."
            )

        payload = self._payload(req)
        base_url = (self.config.llm.base_url or "").rstrip("/")
        if not base_url:
            raise ProviderUnavailable(
                f"{self.config.source_path}: llm.base_url is not set, so no provider can be reached."
            )

        self._write_bundle(bundle, req, payload)

        status, body = self.transport.post_json(
            f"{base_url}/chat/completions",
            payload,
            {"authorization": f"Bearer {os.environ[API_KEY_ENV]}"},
            self.timeout,
        )
        text = self._extract(body, status)

        # The response goes down before the return value is handed over: a call
        # that produced no audit trail did not happen, and cannot be reviewed.
        raw_path.write_text(text, encoding="utf-8", newline="\n")
        (bundle / "response.json").write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
        return LLMResponse(text=text, raw_path=raw_path, model=self.config.llm.model, prompt_sha=req.prompt_sha)

    def audit_dir(self, task_id: str) -> Path:
        return self.project_root / AUDIT_RELATIVE_ROOT / task_id

    # ------------------------------------------------------------ internals

    def _check_preconditions(self, req: LLMRequest) -> None:
        if req.action not in ACTIONS:
            raise ValueError(f"action must be one of {ACTIONS}, got {req.action!r}")
        if not req.context.strip():
            raise ValueError("empty context: refusing to spend a call on nothing")

        enabled = os.environ.get(ENABLED_ENV)
        if enabled is not None and enabled.lower() not in TRUTHY:
            raise ProviderUnavailable(f"LLM use disabled ({ENABLED_ENV}={enabled!r})")

        if self.config.llm.provider == "stub":
            raise ProviderUnavailable(
                "llm.provider is 'stub'. Stubs may not return text: a placeholder that "
                "flows downstream as an answer is a false pass."
            )
        if self.config.llm.provider != "openai_compatible":
            raise ProviderUnavailable(f"no client implementation for provider {self.config.llm.provider!r}")
        if not os.environ.get(API_KEY_ENV):
            raise ProviderUnavailable(f"{API_KEY_ENV} is not set. Keys are never read from the config file.")
        if self.config.llm.temperature != 0.0:
            raise ProviderUnavailable(
                "llm.temperature must be 0. Sampling is not permitted for pipeline calls; "
                "delete the temperature line rather than setting it back."
            )

    def _payload(self, req: LLMRequest) -> dict[str, Any]:
        return {
            "model": self.config.llm.model,
            "messages": [{"role": "user", "content": req.context}],
            # Pinned, not configured: the acceptance criterion is same input, same
            # output, and that is not a per-project preference.
            "temperature": 0.0,
            "seed": 0,
            "max_tokens": self.config.llm.max_tokens,
        }

    def _write_bundle(self, bundle: Path, req: LLMRequest, payload: dict[str, Any]) -> None:
        bundle.mkdir(parents=True, exist_ok=True)
        numbered = "\n".join(f"{n:6d}| {line}" for n, line in enumerate(req.context.splitlines(), start=1))
        (bundle / "input.numbered.txt").write_text(numbered + "\n", encoding="utf-8", newline="\n")
        (bundle / "task.json").write_text(
            json.dumps(
                {
                    "task_id": req.task_id,
                    "action": req.action,
                    "expect": req.expect,
                    "prompt_sha": req.prompt_sha,
                    "context_sha256": prompt_sha_of(req.context),
                    "model": self.config.llm.model,
                    "provider": self.config.llm.provider,
                    "temperature": payload["temperature"],
                    "seed": payload["seed"],
                    "requested_at_utc": datetime.now(UTC).isoformat(timespec="milliseconds"),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def _extract(self, body: dict[str, Any], status: int) -> str:
        if status >= 400:
            raise ProviderUnavailable(f"provider returned HTTP {status}: {json.dumps(body)[:500]}")
        try:
            return body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderUnavailable(f"provider response has no message content: {json.dumps(body)[:500]}") from exc
