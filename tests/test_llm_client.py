"""P0-4: S20 LLM client. Rules under test: deterministic, fully recorded, never a stub."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
import yaml

from firmware_agent.config import ConfigError, load_project_config
from firmware_agent.project_layout import ensure_project_layout
from firmware_agent.slices.S20_LLMClient_and_Tools.client import (
    API_KEY_ENV,
    ENABLED_ENV,
    AuditConflict,
    LLMClient,
    LLMRequest,
    ProviderUnavailable,
    UrllibTransport,
    prompt_sha_of,
)

ANSWER = "## 生成说明\n- 依据 R-001 生成 boot_check()\n"


class FakeTransport:
    def __init__(self, status=200, body=None):
        self.status = status
        self.body = body or {"choices": [{"message": {"content": ANSWER}}]}
        self.calls: list[dict] = []

    def post_json(self, url, payload, headers, timeout):
        self.calls.append({"url": url, "payload": payload, "headers": headers, "timeout": timeout})
        return self.status, self.body


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    ensure_project_layout(root)
    (root / "Docs/config.yaml").write_text(
        yaml.safe_dump(
            {
                "project": {"name": "brake-controller"},
                "mcu": {"part": "STM32F407VGT6"},
                "toolchain": {"compiler": "arm-none-eabi-gcc"},
                "llm": {
                    "provider": "openai_compatible",
                    "model": "Qwen3.8-27B",
                    "max_tokens": 4096,
                    "base_url": "http://127.0.0.1:9/v1",
                },
            }
        ),
        encoding="utf-8",
    )
    return root


def request(context: str = "输入上下文") -> LLMRequest:
    return LLMRequest(task_id="T-001", action="elaborate", prompt_sha=prompt_sha_of(context), context=context)


def client_for(root: Path, transport) -> LLMClient:
    return LLMClient(load_project_config(root), root, transport=transport)


@pytest.fixture()
def with_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(API_KEY_ENV, "secret-not-in-config")
    monkeypatch.delenv(ENABLED_ENV, raising=False)


def bundle(root: Path, task: str = "T-001") -> Path:
    return root / "Docs/ai-generation/audit" / task


# --------------------------------------------------------------- determinism


def test_requests_are_pinned_to_deterministic_parameters(project: Path, with_key: None) -> None:
    transport = FakeTransport()
    client_for(project, transport).generate(request("same input"))

    payload = transport.calls[0]["payload"]
    assert payload["temperature"] == 0.0 and payload["seed"] == 0
    assert payload["model"] == "Qwen3.8-27B" and payload["max_tokens"] == 4096


def test_same_input_builds_the_same_request_and_output(project: Path, with_key: None) -> None:
    first, second = FakeTransport(), FakeTransport()
    a = client_for(project, first).generate(request("identical"))
    # A second call needs a new task id (audit outputs are not overwritten), so
    # determinism is compared on the request payload and the returned text.
    b = client_for(project, second).generate(
        LLMRequest(task_id="T-002", action="elaborate", prompt_sha=prompt_sha_of("identical"), context="identical")
    )

    assert first.calls[0]["payload"] == second.calls[0]["payload"]
    assert a.text == b.text == ANSWER
    assert a.raw_path.read_text(encoding="utf-8") == ANSWER


def test_sampling_cannot_be_configured(project: Path) -> None:
    path = project / "Docs/config.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["llm"]["temperature"] = 0.9
    path.write_text(yaml.safe_dump(data), encoding="utf-8")

    with pytest.raises(ConfigError) as err:
        load_project_config(project)
    assert "llm.temperature" in str(err.value)


# -------------------------------------------------------------------- audit


def test_every_call_leaves_an_audit_bundle(project: Path, with_key: None) -> None:
    client_for(project, FakeTransport()).generate(request("第一行\n第二行"))

    bundle_dir = bundle(project)
    task = json.loads((bundle_dir / "task.json").read_text(encoding="utf-8"))
    assert task["action"] == "elaborate" and task["model"] == "Qwen3.8-27B"
    assert task["temperature"] == 0.0 and task["seed"] == 0
    assert task["context_sha256"] == prompt_sha_of("第一行\n第二行")

    numbered = (bundle_dir / "input.numbered.txt").read_text(encoding="utf-8")
    assert numbered.startswith("     1| 第一行"), "anchored input is what later audits cite"
    assert (bundle_dir / "output.raw").read_text(encoding="utf-8") == ANSWER
    assert json.loads((bundle_dir / "response.json").read_text(encoding="utf-8"))


def test_credentials_never_reach_the_audit_bundle(project: Path, with_key: None) -> None:
    client_for(project, FakeTransport()).generate(request())

    for path in bundle(project).iterdir():
        assert "secret-not-in-config" not in path.read_text(encoding="utf-8"), path.name


def test_a_second_attempt_must_mint_a_new_task_id(project: Path, with_key: None) -> None:
    client = client_for(project, FakeTransport())
    client.generate(request())
    with pytest.raises(AuditConflict):
        client.generate(request())


def test_failed_attempt_is_still_recorded_and_can_be_retried(project: Path, with_key: None) -> None:
    client = client_for(project, FakeTransport(status=503, body={"error": "overloaded"}))
    with pytest.raises(ProviderUnavailable):
        client.generate(request())

    assert (bundle(project) / "task.json").exists(), "the attempt happened; the audit must say so"
    assert not (bundle(project) / "output.raw").exists(), "no output was produced"

    ok = client_for(project, FakeTransport())
    assert ok.generate(request()).text == ANSWER, "a retry under the same task id is allowed after a failure"


# ---------------------------------------------------------------- stub rule


def test_stub_provider_cannot_produce_text(project: Path, with_key: None) -> None:
    path = project / "Docs/config.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["llm"]["provider"] = "stub"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")

    transport = FakeTransport()
    with pytest.raises(ProviderUnavailable) as err:
        client_for(project, transport).generate(request())
    assert "stub" in str(err.value)
    assert transport.calls == [] and not bundle(project).exists(), "a stub must not look like a call"


def test_the_llm_can_be_turned_off(project: Path, with_key: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENABLED_ENV, "0")
    with pytest.raises(ProviderUnavailable) as err:
        client_for(project, FakeTransport()).generate(request())
    assert "disabled" in str(err.value)


def test_missing_key_is_an_error_not_a_default(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(API_KEY_ENV, raising=False)
    with pytest.raises(ProviderUnavailable) as err:
        client_for(project, FakeTransport()).generate(request())
    assert API_KEY_ENV in str(err.value)


def test_missing_base_url_is_named(project: Path, with_key: None) -> None:
    path = project / "Docs/config.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["llm"]["base_url"] = None
    path.write_text(yaml.safe_dump(data), encoding="utf-8")

    with pytest.raises(ProviderUnavailable) as err:
        client_for(project, FakeTransport()).generate(request())
    assert "llm.base_url" in str(err.value)


def test_response_without_content_is_not_read_as_success(project: Path, with_key: None) -> None:
    with pytest.raises(ProviderUnavailable):
        client_for(project, FakeTransport(body={"choices": []})).generate(request())


def test_unknown_action_is_refused_before_any_cost(project: Path, with_key: None) -> None:
    transport = FakeTransport()
    with pytest.raises(ValueError):
        client_for(project, transport).generate(
            LLMRequest(task_id="T-001", action="vibes", prompt_sha="x", context="ctx")
        )
    assert transport.calls == []


# -------------------------------------------------------------- real socket


def test_real_http_round_trip_and_connection_refusal(project: Path, with_key: None) -> None:
    seen: dict = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers["content-length"])
            seen["payload"] = json.loads(self.rfile.read(length))
            body = json.dumps({"choices": [{"message": {"content": ANSWER}}]}).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):  # silence the test server
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]

    path = project / "Docs/config.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["llm"]["base_url"] = f"http://127.0.0.1:{port}/v1"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")

    try:
        response = client_for(project, UrllibTransport()).generate(request("live"))
        assert response.text == ANSWER
        assert seen["payload"]["temperature"] == 0.0
    finally:
        server.shutdown()

    # Same client, nothing listening: an error, never placeholder text.
    data["llm"]["base_url"] = "http://127.0.0.1:1/v1"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(ProviderUnavailable):
        LLMClient(load_project_config(project), project, transport=UrllibTransport()).generate(
            LLMRequest(task_id="T-002", action="elaborate", prompt_sha="x", context="ctx")
        )
