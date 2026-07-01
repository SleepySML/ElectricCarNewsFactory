import json
from types import SimpleNamespace

from ev_factory.config import load_config
from ev_factory.db import JobRepository
from ev_factory.jobfolder import JobFolder
from ev_factory.models import StageStatus
from ev_factory.stages.base import StageContext
from ev_factory.stages.curate import CurateStage


class FakeLLM:
    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    def complete(self, model, system, prompt, job_id, stage, max_tokens=1024):
        self.calls.append((model, prompt))
        return self.reply


def _ctx(tmp_config, candidates):
    cfg = load_config(tmp_config)
    repo = JobRepository(cfg.db_path)
    repo.init_schema()
    folder = JobFolder.create(cfg.jobs_dir, "2026-07-01", "slug")
    repo.create_job(folder.job_id, "slug", "2026-07-01", cfg.all_languages)
    folder.write_json(folder.root / "ingest.json", candidates)
    return cfg, repo, folder, StageContext(folder.job_id, folder, cfg, repo)


def test_curate_picks_and_writes_story(tmp_config):
    candidates = [
        {"title": "A", "link": "http://a", "source": "s1", "published": "", "points": ["x"]},
        {"title": "B", "link": "http://b", "source": "s2", "published": "", "points": ["y"]},
    ]
    cfg, repo, folder, ctx = _ctx(tmp_config, candidates)
    llm = FakeLLM(json.dumps({"chosen_index": 1, "angle": "why B matters"}))
    result = CurateStage(llm).run(ctx)
    assert result.status is StageStatus.DONE
    story = folder.read_json(folder.story_json)
    assert story["title"] == "B"
    assert story["angle"] == "why B matters"
    assert story["link"] == "http://b"


def test_curate_fails_without_ingest(tmp_config):
    cfg, repo, folder, ctx = _ctx(tmp_config, [])
    result = CurateStage(FakeLLM("{}")).run(ctx)
    assert result.status is StageStatus.FAILED


def test_curate_produces_park_state(tmp_config):
    from ev_factory.models import JobState
    assert CurateStage.__dict__["produces_state"] == JobState.STORY_REVIEW
