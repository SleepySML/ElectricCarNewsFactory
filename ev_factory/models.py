from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum


class JobState(str, Enum):
    NEW = "new"
    INGESTED = "ingested"
    SCRIPTED = "scripted"
    LOCALIZED = "localized"
    RENDERED = "rendered"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    PUBLISHED = "published"
    FAILED = "failed"


class StageStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class StageResult:
    stage: str
    status: StageStatus
    message: str = ""
    data: dict = field(default_factory=dict)

    @classmethod
    def ok(cls, stage: str, message: str = "", data: dict | None = None) -> "StageResult":
        return cls(stage=stage, status=StageStatus.DONE, message=message, data=data or {})

    @classmethod
    def fail(cls, stage: str, message: str) -> "StageResult":
        return cls(stage=stage, status=StageStatus.FAILED, message=message)


@dataclass
class ComplianceCheck:
    key: str
    passed: bool
    detail: str = ""
    hard: bool = True


def make_slug(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug[:60].rstrip("-")
