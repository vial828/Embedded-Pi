from firmware_agent.slices.S22_Compiler_Verifier.compiler_verifier import (
    CompilerVerifier,
    VerifyResult,
)
from firmware_agent.slices.S23_Static_Verifier.static_verifier import StaticVerifier
from firmware_agent.slices.S24_Simulator_Verifier.simulator_verifier import SimulatorVerifier
from firmware_agent.slices.S25_Error_Classifier.error_classifier import ErrorClassifier
from firmware_agent.slices.S26_Retry_Strategy.retry_strategy import RetryStrategy


class Verifier:
    """Compatibility facade over S22~S26 verifier slices."""

    def __init__(self) -> None:
        self.compiler = CompilerVerifier()
        self.static = StaticVerifier()
        self.sim = SimulatorVerifier()
        self.classifier = ErrorClassifier()
        self.retry = RetryStrategy()

    def verify(self, task_name: str) -> VerifyResult:
        # Keep M0 behavior: compiler verify is authoritative pass/fail signal.
        return self.compiler.verify(task_name)
