from pathlib import Path

import pytest

from ev_factory.config import load_config
from ev_factory.db import JobRepository
from ev_factory.jobfolder import JobFolder
from ev_factory.models import JobState, StageResult
from ev_factory.stages.base import Stage, StageContext


def test_context_dry_run_delegates(tmp_config: Path):
    cfg = load_config(tmp_config)
    ctx = StageContext(job_id="j", folder=JobFolder(Path("x")), config=cfg,
                       repo=JobRepository(cfg.db_path))
    assert ctx.dry_run is True


def test_concrete_stage_runs():
    class DummyStage(Stage):
        name = "dummy"
        produces_state = JobState.INGESTED

        def run(self, ctx: StageContext) -> StageResult:
            return StageResult.ok(self.name)

    assert DummyStage().run(ctx=None).stage == "dummy"


def test_stage_without_attrs_rejected():
    with pytest.raises(TypeError):
        class Bad(Stage):
            def run(self, ctx):
                return None
