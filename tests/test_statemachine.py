from pathlib import Path

import pytest

from ev_factory.db import JobRepository
from ev_factory.models import JobState
from ev_factory.statemachine import (
    InvalidTransition,
    can_transition,
    next_state,
    transition,
)


def test_happy_path_transitions_allowed():
    assert can_transition(JobState.NEW, JobState.INGESTED)
    assert can_transition(JobState.IN_REVIEW, JobState.APPROVED)
    assert can_transition(JobState.APPROVED, JobState.PUBLISHED)


def test_any_active_state_can_fail():
    assert can_transition(JobState.SCRIPTED, JobState.FAILED)
    assert can_transition(JobState.RENDERED, JobState.FAILED)


def test_illegal_skips_rejected():
    assert not can_transition(JobState.NEW, JobState.PUBLISHED)
    assert not can_transition(JobState.PUBLISHED, JobState.NEW)


def test_next_state_walks_happy_path():
    assert next_state(JobState.NEW) == JobState.INGESTED
    assert next_state(JobState.APPROVED) == JobState.PUBLISHED
    assert next_state(JobState.PUBLISHED) is None
    assert next_state(JobState.FAILED) is None


def test_transition_persists(tmp_path: Path):
    repo = JobRepository(tmp_path / "t.db")
    repo.init_schema()
    repo.create_job("j", "slug", "2026-07-01", ["en"])
    transition(repo, "j", JobState.INGESTED)
    assert repo.get_job("j")["state"] == JobState.INGESTED


def test_transition_rejects_illegal(tmp_path: Path):
    repo = JobRepository(tmp_path / "t.db")
    repo.init_schema()
    repo.create_job("j", "slug", "2026-07-01", ["en"])
    with pytest.raises(InvalidTransition):
        transition(repo, "j", JobState.PUBLISHED)
