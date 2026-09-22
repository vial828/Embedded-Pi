from pathlib import Path

from firmware_agent.agent import FirmwareAgent
from firmware_agent.project_layout import ensure_project_layout


def test_agent_dry_run_smoke(tmp_path: Path):
    project = tmp_path / "smoke-project"
    ensure_project_layout(project)

    agent = FirmwareAgent(str(project))
    logs = agent.run(dry_run=True)
    assert logs
    assert any("TASK:" in line for line in logs)
