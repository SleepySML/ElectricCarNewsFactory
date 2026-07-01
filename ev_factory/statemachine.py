from __future__ import annotations

from ev_factory.db import JobRepository
from ev_factory.models import JobState

HAPPY_PATH: list[JobState] = [
    JobState.NEW,
    JobState.INGESTED,
    JobState.STORY_REVIEW,
    JobState.STORY_APPROVED,
    JobState.SCRIPTED,
    JobState.LOCALIZED,
    JobState.RENDERED,
    JobState.IN_REVIEW,
    JobState.APPROVED,
    JobState.PUBLISHED,
]

PARK_STATES: set[JobState] = {JobState.STORY_REVIEW, JobState.IN_REVIEW}

_TERMINAL = {JobState.PUBLISHED, JobState.FAILED}

ALLOWED_TRANSITIONS: dict[JobState, set[JobState]] = {}
for _i, _state in enumerate(HAPPY_PATH):
    _targets: set[JobState] = set()
    if _i + 1 < len(HAPPY_PATH):
        _targets.add(HAPPY_PATH[_i + 1])
    if _state not in _TERMINAL:
        _targets.add(JobState.FAILED)
    ALLOWED_TRANSITIONS[_state] = _targets
ALLOWED_TRANSITIONS[JobState.FAILED] = set()


class InvalidTransition(Exception):
    pass


def can_transition(src: JobState, dst: JobState) -> bool:
    return dst in ALLOWED_TRANSITIONS.get(src, set())


def next_state(src: JobState) -> JobState | None:
    if src in _TERMINAL:
        return None
    idx = HAPPY_PATH.index(src)
    if idx + 1 < len(HAPPY_PATH):
        return HAPPY_PATH[idx + 1]
    return None


def transition(repo: JobRepository, job_id: str, dst: JobState) -> None:
    job = repo.get_job(job_id)
    if job is None:
        raise InvalidTransition(f"unknown job {job_id}")
    src = JobState(job["state"])
    if not can_transition(src, dst):
        raise InvalidTransition(f"{src.value} -> {dst.value} not allowed")
    repo.set_state(job_id, dst)
