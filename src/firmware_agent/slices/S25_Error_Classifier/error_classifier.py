class ErrorClassifier:
    """S25 error classifier stub."""

    def classify(self, output: str) -> str:
        text = (output or "").lower()
        if "compile" in text:
            return "compile_error"
        if "link" in text:
            return "link_error"
        if "crash" in text:
            return "runtime_crash"
        return "unknown"
