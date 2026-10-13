"""Annotation model: the only artefact an LLM is allowed to produce from a PRD.

The LLM never writes requirement text. It claims character ranges of the extracted
source and labels them; code slices the text itself. That single restriction is what
makes silent rewriting impossible - see verification.verify_annotation().
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path

LABEL_ATOM = "atom"
LABEL_QUALIFIER = "qualifier"
LABEL_OPEN_ENDED = "open_ended"
LABEL_NOISE = "noise"
LABELS = frozenset({LABEL_ATOM, LABEL_QUALIFIER, LABEL_OPEN_ENDED, LABEL_NOISE})

# Labels that carry requirement meaning. Everything a customer could complain was
# "swallowed" must be inside a requirement claim, never inside noise.
REQUIREMENT_LABELS = frozenset({LABEL_ATOM, LABEL_QUALIFIER, LABEL_OPEN_ENDED})


def source_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Claim:
    """One labelled character range: doc[start:end]."""

    label: str
    start: int
    end: int
    quote: str = ""
    group: str = ""
    detail: str = ""

    @property
    def length(self) -> int:
        return self.end - self.start

    def overlaps(self, other: "Claim") -> bool:
        return self.start < other.end and other.start < self.end


@dataclass
class Annotation:
    source_path: str
    source_sha256: str
    claims: list[Claim] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "source_path": self.source_path,
            "source_sha256": self.source_sha256,
            "claims": [asdict(c) for c in self.claims],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Annotation":
        known = {f for f in Claim.__dataclass_fields__}
        claims = [Claim(**{k: v for k, v in c.items() if k in known}) for c in data.get("claims", [])]
        return cls(
            source_path=data.get("source_path", ""),
            source_sha256=data.get("source_sha256", ""),
            claims=claims,
        )


def load_annotation(path: Path) -> Annotation:
    return Annotation.from_dict(json.loads(path.read_text(encoding="utf-8")))


def save_annotation(path: Path, annotation: Annotation) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(annotation.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


def claims_of(annotation: Annotation, *labels: str) -> list[Claim]:
    wanted = set(labels) or LABELS
    return [c for c in annotation.claims if c.label in wanted]


def groups(annotation: Annotation) -> dict[str, list[Claim]]:
    """Claims bucketed by story group id, in first-seen order."""
    buckets: dict[str, list[Claim]] = {}
    for claim in annotation.claims:
        buckets.setdefault(claim.group, []).append(claim)
    return buckets
