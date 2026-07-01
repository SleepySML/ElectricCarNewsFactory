from pathlib import Path

from ev_factory.config import load_config
from ev_factory.db import JobRepository
from ev_factory.jobfolder import JobFolder
from ev_factory.models import JobState, StageResult
from ev_factory.orchestrator import Orchestrator
from ev_factory.stages.base import Stage, StageContext


class RecordingStage(Stage):
    name = "ingest"
    produces_state = JobState.INGESTED

    def __init__(self):
        self.calls = 0

    def run(self, ctx: StageContext) -> StageResult:
        self.calls += 1
        return StageResult.ok(self.name)


class ScriptStage(Stage):
    name = "script"
    produces_state = JobState.SCRIPTED

    def run(self, ctx: StageContext) -> StageResult:
        return StageResult.ok(self.name)


class StoryReviewStage(Stage):
    """Produces STORY_REVIEW — adjacent to INGESTED in the current HAPPY_PATH."""

    name = "story_review"
    produces_state = JobState.STORY_REVIEW

    def run(self, ctx: StageContext) -> StageResult:
        return StageResult.ok(self.name)


class BoomStage(Stage):
    name = "script"
    produces_state = JobState.SCRIPTED

    def run(self, ctx: StageContext) -> StageResult:
        return StageResult.fail(self.name, "kaboom")


def _setup(tmp_config: Path):
    cfg = load_config(tmp_config)
    repo = JobRepository(cfg.db_path)
    repo.init_schema()
    JobFolder.create(cfg.jobs_dir, "2026-07-01", "slug")
    repo.create_job("2026-07-01-slug", "slug", "2026-07-01", ["en"])
    return cfg, repo


def test_run_job_advances_states(tmp_config: Path):
    cfg, repo = _setup(tmp_config)
    orch = Orchestrator(cfg, repo, [RecordingStage(), StoryReviewStage()])
    final = orch.run_job("2026-07-01-slug")
    assert final == JobState.STORY_REVIEW
    assert repo.get_job("2026-07-01-slug")["state"] == JobState.STORY_REVIEW


def test_run_job_stops_at_until(tmp_config: Path):
    cfg, repo = _setup(tmp_config)
    orch = Orchestrator(cfg, repo, [RecordingStage(), ScriptStage()])
    final = orch.run_job("2026-07-01-slug", until=JobState.INGESTED)
    assert final == JobState.INGESTED


def test_failed_stage_marks_job_failed(tmp_config: Path):
    cfg, repo = _setup(tmp_config)
    orch = Orchestrator(cfg, repo, [RecordingStage(), BoomStage()])
    final = orch.run_job("2026-07-01-slug")
    assert final == JobState.FAILED
    assert repo.get_job("2026-07-01-slug")["error"] == "kaboom"


def test_rerun_skips_completed_stages(tmp_config: Path):
    cfg, repo = _setup(tmp_config)
    ingest = RecordingStage()
    orch = Orchestrator(cfg, repo, [ingest, StoryReviewStage()])
    orch.run_job("2026-07-01-slug")
    orch.run_job("2026-07-01-slug")  # second run
    assert ingest.calls == 1  # not re-run


def test_rerun_failed_job_returns_failed_without_crash(tmp_config: Path):
    cfg, repo = _setup(tmp_config)
    orch = Orchestrator(cfg, repo, [RecordingStage(), BoomStage()])
    first = orch.run_job("2026-07-01-slug")
    assert first == JobState.FAILED
    # Re-running a FAILED job must return FAILED without raising ValueError.
    second = orch.run_job("2026-07-01-slug")
    assert second == JobState.FAILED


class RaisingStage(Stage):
    name = "script"
    produces_state = JobState.SCRIPTED

    def run(self, ctx: StageContext) -> StageResult:
        raise RuntimeError("kaboom")


def test_raising_stage_marks_job_failed(tmp_config: Path):
    cfg, repo = _setup(tmp_config)
    orch = Orchestrator(cfg, repo, [RecordingStage(), RaisingStage()])
    result = orch.run_job("2026-07-01-slug")
    assert result == JobState.FAILED
    error = repo.get_job("2026-07-01-slug")["error"]
    assert "script" in error
    assert "kaboom" in error


from ev_factory.models import JobState as _JS


class ParkStage(Stage):
    name = "curate"
    produces_state = _JS.STORY_REVIEW

    def run(self, ctx):
        return StageResult.ok(self.name)


class AfterParkStage(Stage):
    name = "script"
    produces_state = _JS.SCRIPTED

    def __init__(self):
        self.calls = 0

    def run(self, ctx):
        self.calls += 1
        return StageResult.ok(self.name)


class RenderA(Stage):
    name = "voice"
    produces_state = _JS.RENDERED

    def run(self, ctx):
        return StageResult.ok(self.name)


class RenderB(Stage):
    name = "assemble"
    produces_state = _JS.RENDERED

    def __init__(self):
        self.calls = 0

    def run(self, ctx):
        self.calls += 1
        return StageResult.ok(self.name)


def _ingest_stage():
    class Ing(Stage):
        name = "ingest"
        produces_state = _JS.INGESTED

        def run(self, ctx):
            return StageResult.ok(self.name)
    return Ing()


def test_parks_at_story_review_and_halts_until_approved(tmp_config):
    cfg, repo = _setup(tmp_config)
    after = AfterParkStage()
    orch = Orchestrator(cfg, repo, [_ingest_stage(), ParkStage(), after])

    final = orch.run_job("2026-07-01-slug")
    assert final == _JS.STORY_REVIEW
    assert after.calls == 0  # script did not run

    # Re-running while still parked must not run script.
    orch.run_job("2026-07-01-slug")
    assert after.calls == 0

    # Human approves -> resume.
    from ev_factory.statemachine import transition
    transition(repo, "2026-07-01-slug", _JS.STORY_APPROVED)
    final = orch.run_job("2026-07-01-slug")
    assert after.calls == 1
    assert final == _JS.SCRIPTED


def test_stages_sharing_a_milestone_both_run(tmp_config):
    cfg, repo = _setup(tmp_config)
    # Fast-forward the job to LOCALIZED so the two RENDERED stages are next.
    from ev_factory.statemachine import HAPPY_PATH
    from ev_factory.db import JobRepository  # noqa: F401
    repo.set_state("2026-07-01-slug", _JS.LOCALIZED)
    b = RenderB()
    orch = Orchestrator(cfg, repo, [RenderA(), b])
    final = orch.run_job("2026-07-01-slug", until=_JS.RENDERED)
    assert b.calls == 1  # second stage sharing RENDERED still ran (no collapse)
    assert final == _JS.RENDERED


def test_completed_stage_skipped_via_job_stages(tmp_config):
    cfg, repo = _setup(tmp_config)
    ing = _ingest_stage()
    # Mark ingest already done in the stage table.
    repo.mark_stage("2026-07-01-slug", "ingest", "done")
    calls = {"n": 0}

    class CountingIngest(Stage):
        name = "ingest"
        produces_state = _JS.INGESTED

        def run(self, ctx):
            calls["n"] += 1
            return StageResult.ok(self.name)

    orch = Orchestrator(cfg, repo, [CountingIngest()])
    orch.run_job("2026-07-01-slug", until=_JS.INGESTED)
    assert calls["n"] == 0  # skipped because job_stages says done
