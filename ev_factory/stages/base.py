from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ev_factory.config import Config
from ev_factory.db import JobRepository
from ev_factory.jobfolder import JobFolder
from ev_factory.models import JobState, StageResult


@dataclass
class StageContext:
    job_id: str
    folder: JobFolder
    config: Config
    repo: JobRepository

    @property
    def dry_run(self) -> bool:
        return self.config.dry_run


class Stage(ABC):
    name: str = ""
    produces_state: JobState | None = None

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if not cls.name or cls.produces_state is None:
            raise TypeError(
                f"{cls.__name__} must set class attrs 'name' and 'produces_state'"
            )

    @abstractmethod
    def run(self, ctx: StageContext) -> StageResult:
        ...
