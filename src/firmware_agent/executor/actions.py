from pathlib import Path


class ActionExecutor:
    def __init__(self, project_root: str):
        self.project_root = Path(project_root)

    def write_text(self, relative_path: str, content: str) -> Path:
        path = self.project_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path
