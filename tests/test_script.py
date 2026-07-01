from dataclasses import replace

from ev_factory.config import load_config
from ev_factory.db import JobRepository
from ev_factory.jobfolder import JobFolder
from ev_factory.models import StageStatus
from ev_factory.compliance import ComplianceReport
from ev_factory.stages.base import StageContext
from ev_factory.stages.script import ScriptStage


class ScriptLLM:
    """Returns queued script drafts for 'script' calls and a score for 'originality' calls."""
    def __init__(self, drafts, score):
        self.drafts = list(drafts)
        self.score = score
        self.script_calls = 0

    def complete(self, model, system, prompt, job_id, stage, max_tokens=1024):
        if stage == "originality":
            return str(self.score)
        self.script_calls += 1
        return self.drafts.pop(0) if self.drafts else self.drafts_last

    @property
    def drafts_last(self):
        return "fallback draft"


def _ctx(tmp_config, story):
    cfg = replace(load_config(tmp_config), originality_threshold=70, verbatim_span_words=8)
    repo = JobRepository(cfg.db_path)
    repo.init_schema()
    folder = JobFolder.create(cfg.jobs_dir, "2026-07-01", "slug")
    repo.create_job(folder.job_id, "slug", "2026-07-01", cfg.all_languages)
    folder.write_json(folder.story_json, story)
    return cfg, repo, folder, StageContext(folder.job_id, folder, cfg, repo)


STORY = {
    "title": "Tesla cuts price", "link": "http://a", "source": "s1",
    "points": ["Tesla cut the Model Y price"], "angle": "what it means for rivals",
    "sources": ["http://a", "http://b"], "single_source": False,
}


def test_script_writes_script_and_meta_on_pass(tmp_config):
    cfg, repo, folder, ctx = _ctx(tmp_config, STORY)
    llm = ScriptLLM(drafts=["A wholly original take on pricing dynamics and rivals."], score=90)
    result = ScriptStage(llm).run(ctx)
    assert result.status is StageStatus.DONE
    assert folder.script_path("en").exists()
    meta = folder.read_json(folder.root / "script_meta.json")
    assert meta["passed"] is True
    assert meta["transformation_score"] == 90
    assert llm.script_calls == 1  # no regeneration needed


def test_script_regenerates_once_then_records_failure(tmp_config):
    cfg, repo, folder, ctx = _ctx(tmp_config, STORY)
    # Both drafts score low -> fail; must regenerate exactly once (2 script calls total).
    llm = ScriptLLM(drafts=["draft one", "draft two"], score=40)
    result = ScriptStage(llm).run(ctx)
    assert result.status is StageStatus.DONE  # not fatal
    assert llm.script_calls == 2
    report = ComplianceReport.from_dict(folder.read_json(folder.compliance_json))
    assert report.blocking is True  # transformation_score hard-fails


def test_script_fails_without_story(tmp_config):
    cfg = replace(load_config(tmp_config))
    repo = JobRepository(cfg.db_path)
    repo.init_schema()
    folder = JobFolder.create(cfg.jobs_dir, "2026-07-01", "slug")
    repo.create_job(folder.job_id, "slug", "2026-07-01", cfg.all_languages)
    ctx = StageContext(folder.job_id, folder, cfg, repo)
    result = ScriptStage(ScriptLLM(drafts=["x"], score=90)).run(ctx)
    assert result.status is StageStatus.FAILED
