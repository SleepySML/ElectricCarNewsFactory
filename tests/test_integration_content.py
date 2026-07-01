from dataclasses import replace
from types import SimpleNamespace

from ev_factory.config import load_config
from ev_factory.db import JobRepository
from ev_factory.jobfolder import JobFolder
from ev_factory.models import JobState
from ev_factory.orchestrator import Orchestrator
from ev_factory.statemachine import transition
from ev_factory.stages.ingest import IngestStage
from ev_factory.stages.curate import CurateStage
from ev_factory.stages.script import ScriptStage
from ev_factory.stages.localize import LocalizeStage


class FakeLLM:
    """One fake covering curate (JSON), script (prose), originality (score), localize (prose)."""
    def complete(self, model, system, prompt, job_id, stage, max_tokens=1024):
        if stage == "curate":
            return '{"chosen_index": 0, "angle": "what it signals for the market"}'
        if stage == "originality":
            return "88"
        if stage.startswith("localize"):
            return f"translated: {stage.split(':')[-1]}"
        return "A fully original analytical commentary on the day's EV news and its impact."


def _entry(title, link, summary):
    return SimpleNamespace(title=title, link=link, summary=summary, published="2026-07-01")


def test_ingest_to_localized_golden_path(tmp_config):
    cfg = replace(load_config(tmp_config), target_languages=["ru", "tr"])
    cfg.rss_sources.append("https://example.com/feed")
    repo = JobRepository(cfg.db_path)
    repo.init_schema()
    folder = JobFolder.create(cfg.jobs_dir, "2026-07-01", "slug")
    job_id = folder.job_id
    repo.create_job(job_id, "slug", "2026-07-01", cfg.all_languages)

    feed = SimpleNamespace(entries=[_entry("Tesla cuts price", "http://a", "One. Two. Three.")])
    llm = FakeLLM()
    stages = [
        IngestStage(fetch=lambda url: feed),
        CurateStage(llm),
        ScriptStage(llm),
        LocalizeStage(llm),
    ]
    orch = Orchestrator(cfg, repo, stages)

    # First run: ingest -> curate -> parks at STORY_REVIEW.
    state = orch.run_job(job_id, until=JobState.LOCALIZED)
    assert state == JobState.STORY_REVIEW
    assert folder.story_json.exists()
    assert not folder.script_path("en").exists()  # scripting hasn't run yet

    # Human approves the story.
    transition(repo, job_id, JobState.STORY_APPROVED)

    # Resume: script -> localize -> LOCALIZED.
    state = orch.run_job(job_id, until=JobState.LOCALIZED)
    assert state == JobState.LOCALIZED
    assert folder.script_path("en").exists()
    assert folder.script_path("ru").exists()
    assert folder.script_path("tr").exists()
    assert repo.get_language_statuses(job_id) == {"en": "pending", "ru": "done", "tr": "done"}
