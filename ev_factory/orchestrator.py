from __future__ import annotations

from ev_factory.config import Config
from ev_factory.db import JobRepository
from ev_factory.jobfolder import JobFolder
from ev_factory.models import JobState, StageStatus
from ev_factory.stages.base import Stage, StageContext
from ev_factory.statemachine import HAPPY_PATH, PARK_STATES, InvalidTransition, transition


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
            # Terminal or parked: halt. A parked job resumes only when a human
            # transitions it out of the park (e.g. STORY_REVIEW -> STORY_APPROVED).
            if current in (JobState.FAILED, JobState.PUBLISHED) or current in PARK_STATES:
                return current
            # Skip stages already completed (per-stage tracking, not milestone).
            if self.repo.get_stage_status(job_id, stage.name) == "done":
                continue
            # Respect the 'until' ceiling.
            if HAPPY_PATH.index(stage.produces_state) > HAPPY_PATH.index(until):
                break
            try:
                result = stage.run(ctx)
                if result.status is not StageStatus.DONE:
                    self.repo.set_error(job_id, result.message or f"{stage.name} failed")
                    return JobState.FAILED
                self.repo.mark_stage(job_id, stage.name, "done")
                # Advance the coarse milestone only if this stage moves it forward.
                if HAPPY_PATH.index(stage.produces_state) > HAPPY_PATH.index(current):
                    transition(self.repo, job_id, stage.produces_state)
            except (Exception, InvalidTransition) as exc:  # noqa: BLE001
                self.repo.set_error(job_id, f"{stage.name}: {exc}")
                return JobState.FAILED
            # If this stage produced a park state, halt for the human gate.
            if stage.produces_state in PARK_STATES:
                return JobState(self.repo.get_job(job_id)["state"])
        return JobState(self.repo.get_job(job_id)["state"])
