from pathlib import Path

import pytest

from firmware_agent.agent import FirmwareAgent
from firmware_agent.project_layout import ensure_project_layout


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    root = tmp_path / "smoke-project"
    ensure_project_layout(root)
    return root


def test_agent_dry_run_smoke(project: Path) -> None:
    agent = FirmwareAgent(str(project))
    logs = agent.run(dry_run=True)
    assert logs
    assert any("TASK:" in line for line in logs)


def test_agent_without_a_provider_fails_instead_of_inventing_text(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The legacy --run path may not fall back to placeholder output."""
    from firmware_agent.llm.client import ProviderUnavailable

    monkeypatch.delenv("EPI_LLM_API_KEY", raising=False)
    monkeypatch.delenv("EPI_LLM_ENABLED", raising=False)

    agent = FirmwareAgent(str(project))
    with pytest.raises(ProviderUnavailable):
        agent.run(dry_run=False)
