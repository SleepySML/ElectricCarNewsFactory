from __future__ import annotations

from dataclasses import dataclass, field

from ev_factory.models import ComplianceCheck


@dataclass
class ComplianceReport:
    checks: list[ComplianceCheck] = field(default_factory=list)

    def add(self, key: str, passed: bool, detail: str = "", hard: bool = True) -> None:
        self.checks.append(ComplianceCheck(key=key, passed=passed, detail=detail, hard=hard))

    @property
    def blocking(self) -> bool:
        return any(c.hard and not c.passed for c in self.checks)

    def to_dict(self) -> dict:
        return {
            "checks": [
                {"key": c.key, "passed": c.passed, "detail": c.detail, "hard": c.hard}
                for c in self.checks
            ],
            "blocking": self.blocking,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ComplianceReport":
        report = cls()
        for c in d.get("checks", []):
            report.add(c["key"], c["passed"], c.get("detail", ""), c.get("hard", True))
        return report
