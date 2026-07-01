from dataclasses import replace

from ev_factory.config import load_config
from ev_factory.db import JobRepository
from ev_factory.jobfolder import JobFolder
from ev_factory.models import StageStatus
from ev_factory.stages.base import StageContext
from ev_factory.stages.localize import LocalizeStage


class LangLLM:
    def __init__(self, fail_langs=()):
        self.fail_langs = set(fail_langs)
        self.calls = []

    def complete(self, model, system, prompt, job_id, stage, max_tokens=1024):
        # The target language is encoded in the stage label "localize:<lang>".
        lang = stage.split(":")[-1]
        self.calls.append(lang)
        if lang in self.fail_langs:
            raise RuntimeError("translation boom")
        return f"[{lang}] translated"


def _ctx(tmp_config, langs):
    cfg = replace(load_config(tmp_config), target_languages=langs)
    repo = JobRepository(cfg.db_path)
    repo.init_schema()
    folder = JobFolder.create(cfg.jobs_dir, "2026-07-01", "slug")
    repo.create_job(folder.job_id, "slug", "2026-07-01", cfg.all_languages)
    folder.script_path("en").write_text("English script", encoding="utf-8")
    return cfg, repo, folder, StageContext(folder.job_id, folder, cfg, repo)


def test_localize_writes_each_language(tmp_config):
    cfg, repo, folder, ctx = _ctx(tmp_config, ["ru", "tr"])
    result = LocalizeStage(LangLLM()).run(ctx)
    assert result.status is StageStatus.DONE
    assert folder.script_path("ru").read_text(encoding="utf-8") == "[ru] translated"
    assert folder.script_path("tr").read_text(encoding="utf-8") == "[tr] translated"
    statuses = repo.get_language_statuses(folder.job_id)
    assert statuses["ru"] == "done" and statuses["tr"] == "done"


def test_localize_isolates_failing_language(tmp_config):
    cfg, repo, folder, ctx = _ctx(tmp_config, ["ru", "tr"])
    result = LocalizeStage(LangLLM(fail_langs={"ru"})).run(ctx)
    assert result.status is StageStatus.DONE  # tr still succeeded
    statuses = repo.get_language_statuses(folder.job_id)
    assert statuses["ru"] == "failed"
    assert statuses["tr"] == "done"
    assert folder.script_path("tr").exists()


def test_localize_fails_without_english(tmp_config):
    cfg = replace(load_config(tmp_config), target_languages=["ru"])
    repo = JobRepository(cfg.db_path)
    repo.init_schema()
    folder = JobFolder.create(cfg.jobs_dir, "2026-07-01", "slug")
    repo.create_job(folder.job_id, "slug", "2026-07-01", cfg.all_languages)
    ctx = StageContext(folder.job_id, folder, cfg, repo)
    result = LocalizeStage(LangLLM()).run(ctx)
    assert result.status is StageStatus.FAILED
