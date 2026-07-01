from pathlib import Path

from ev_factory.db import JobRepository
from ev_factory.models import JobState


def make_repo(tmp_path: Path) -> JobRepository:
    repo = JobRepository(tmp_path / "t.db")
    repo.init_schema()
    return repo


def test_init_schema_is_idempotent(tmp_path: Path):
    repo = make_repo(tmp_path)
    repo.init_schema()  # second call must not raise
    assert repo.get_job("missing") is None


def test_create_and_get_job(tmp_path: Path):
    repo = make_repo(tmp_path)
    repo.create_job("2026-07-01-slug", "slug", "2026-07-01", ["en", "ru"])
    job = repo.get_job("2026-07-01-slug")
    assert job["state"] == JobState.NEW
    assert job["slug"] == "slug"
    assert repo.get_language_statuses("2026-07-01-slug") == {"en": "pending", "ru": "pending"}


def test_set_state_and_error(tmp_path: Path):
    repo = make_repo(tmp_path)
    repo.create_job("j", "slug", "2026-07-01", ["en"])
    repo.set_state("j", JobState.SCRIPTED)
    assert repo.get_job("j")["state"] == JobState.SCRIPTED
    repo.set_error("j", "boom")
    job = repo.get_job("j")
    assert job["state"] == JobState.FAILED
    assert job["error"] == "boom"


def test_language_status_update(tmp_path: Path):
    repo = make_repo(tmp_path)
    repo.create_job("j", "slug", "2026-07-01", ["en", "ru"])
    repo.set_language_status("j", "ru", "failed")
    assert repo.get_language_statuses("j")["ru"] == "failed"


def test_list_jobs_by_state(tmp_path: Path):
    repo = make_repo(tmp_path)
    repo.create_job("a", "a", "2026-07-01", ["en"])
    repo.create_job("b", "b", "2026-07-01", ["en"])
    repo.set_state("b", JobState.IN_REVIEW)
    ids = [j["id"] for j in repo.list_jobs(state=JobState.IN_REVIEW)]
    assert ids == ["b"]
    assert len(repo.list_jobs()) == 2


def test_cost_logging_and_month_sum(tmp_path: Path):
    repo = make_repo(tmp_path)
    repo.create_job("j", "slug", "2026-07-01", ["en"])
    repo.record_cost("j", "voice", "elevenlabs", 1.5)
    repo.record_cost("j", "script", "anthropic", 0.25)
    month = repo.get_job("j")["created_at"][:7]
    assert abs(repo.spend_this_month(month) - 1.75) < 1e-9


def test_post_record_and_idempotency_lookup(tmp_path: Path):
    repo = make_repo(tmp_path)
    repo.create_job("j", "slug", "2026-07-01", ["en"])
    assert repo.get_post("j", "en", "youtube") is None
    repo.record_post("j", "en", "youtube", "vid123", "http://y/vid123")
    post = repo.get_post("j", "en", "youtube")
    assert post["post_id"] == "vid123"


def test_mark_and_get_stage_status(tmp_path):
    repo = make_repo(tmp_path)
    repo.create_job("j", "slug", "2026-07-01", ["en"])
    assert repo.get_stage_status("j", "ingest") is None
    repo.mark_stage("j", "ingest", "done")
    assert repo.get_stage_status("j", "ingest") == "done"
    repo.mark_stage("j", "ingest", "failed")  # overwrite
    assert repo.get_stage_status("j", "ingest") == "failed"


def test_recent_slugs_newest_first(tmp_path):
    repo = make_repo(tmp_path)
    repo.create_job("2026-06-29-a", "a", "2026-06-29", ["en"])
    repo.create_job("2026-07-01-b", "b", "2026-07-01", ["en"])
    repo.create_job("2026-06-30-c", "c", "2026-06-30", ["en"])
    assert repo.recent_slugs(2) == ["b", "c"]
    assert repo.recent_slugs(10) == ["b", "c", "a"]
