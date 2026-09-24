class RetryStrategy:
    """S26 retry strategy stub."""

    def should_retry(self, error_type: str, retry_count: int, max_retry: int = 2) -> bool:
        if retry_count >= max_retry:
            return False
        return error_type in {
            "compile_error",
            "link_error",
            "runtime_crash",
            "behavior_error",
            "static_analysis_error",
            "hil_fail",
            "unknown",
        }
