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
    orch = Orchestrator(cfg, repo, [RecordingStage(), ScriptStage()])
    final = orch.run_job("2026-07-01-slug")
    assert final == JobState.SCRIPTED
    assert repo.get_job("2026-07-01-slug")["state"] == JobState.SCRIPTED


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
    orch = Orchestrator(cfg, repo, [ingest, ScriptStage()])
    orch.run_job("2026-07-01-slug")
    orch.run_job("2026-07-01-slug")  # second run
    assert ingest.calls == 1  # not re-run
