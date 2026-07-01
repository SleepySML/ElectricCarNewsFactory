from __future__ import annotations

from ev_factory.config import Config
from ev_factory.db import JobRepository
from ev_factory.jobfolder import JobFolder
from ev_factory.models import JobState, StageStatus
from ev_factory.stages.base import Stage, StageContext
from ev_factory.statemachine import HAPPY_PATH, transition


class Orchestrator:
    def __init__(self, config: Config, repo: JobRepository, stages: list[Stage]):
        self.config = config
        self.repo = repo
        self.stages = stages

    def run_job(self, job_id: str, until: JobState = JobState.IN_REVIEW) -> JobState:
        folder = JobFolder(self.config.jobs_dir / job_id)
        ctx = StageContext(
            job_id=job_id, folder=folder, config=self.config, repo=self.repo
        )
        for stage in self.stages:
            current = JobState(self.repo.get_job(job_id)["state"])
            # Guard: terminal states cannot be advanced further.
            if current in (JobState.FAILED, JobState.PUBLISHED):
                return current
            # Skip stages already passed (idempotent re-run).
            if HAPPY_PATH.index(stage.produces_state) <= HAPPY_PATH.index(current):
                continue
            # Respect the 'until' ceiling.
            if HAPPY_PATH.index(stage.produces_state) > HAPPY_PATH.index(until):
                break
            try:
                result = stage.run(ctx)
            except Exception as exc:  # noqa: BLE001 - convert to job failure
                self.repo.set_error(job_id, f"{stage.name}: {exc}")
                return JobState.FAILED
            if result.status is not StageStatus.DONE:
                self.repo.set_error(job_id, result.message or f"{stage.name} failed")
                return JobState.FAILED
            transition(self.repo, job_id, stage.produces_state)
        return JobState(self.repo.get_job(job_id)["state"])
