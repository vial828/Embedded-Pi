from firmware_agent.slices.S22_Compiler_Verifier.compiler_verifier import VerifyResult


class StaticVerifier:
    """S23 static verifier stub."""

    def verify(self, task_name: str) -> VerifyResult:
        # Marked as a stub and never passing: an unmarked stub pass is what makes a
        # broken pipeline look green, and S30 can only reject what it can see.
        return VerifyResult(
            passed=False,
            output=f"[stub] static analysis not implemented; no verdict for {task_name!r}",
            stub=True,
            tool="stub",
        )
