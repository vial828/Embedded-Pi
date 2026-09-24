from pathlib import Path


DEFAULT_CONSTITUTION = """## Hard Rules
- Always verify generated code via compile step.
- Do not guess register values; query project data/tools.
- On uncertainty, return [NEED_CLARIFICATION: ...].
"""


def load_constitution(path: str) -> str:
    p = Path(path)
    if p.exists():
        return p.read_text(encoding="utf-8")
    return DEFAULT_CONSTITUTION
