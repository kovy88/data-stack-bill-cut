from dataclasses import dataclass, field
from enum import StrEnum


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


CONFIDENCE_MEANING = {
    Confidence.HIGH: "config change; saving modelled from your own query and billing history",
    Confidence.MEDIUM: "saving is certain in bytes/credits, but the owner must confirm the change",
    Confidence.LOW: "needs a short live test before the saving can be counted",
}


@dataclass(frozen=True)
class Finding:
    check: str
    title: str
    resource: str
    annual_usd_low: float
    annual_usd_high: float
    confidence: Confidence
    action: str
    evidence: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    fix_sql: str | None = None


def totals_by_confidence(findings: list[Finding]) -> dict[Confidence, tuple[float, float]]:
    totals = {c: (0.0, 0.0) for c in Confidence}
    for f in findings:
        low, high = totals[f.confidence]
        totals[f.confidence] = (low + f.annual_usd_low, high + f.annual_usd_high)
    return totals
