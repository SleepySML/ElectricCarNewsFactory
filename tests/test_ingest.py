from types import SimpleNamespace

from ev_factory.config import load_config
from ev_factory.db import JobRepository
from ev_factory.jobfolder import JobFolder
from ev_factory.models import JobState, StageStatus
from ev_factory.stages.base import StageContext
from ev_factory.stages.ingest import IngestStage


def _fake_feed(entries):
    return SimpleNamespace(entries=entries)


def _entry(title, link, summary, published="2026-07-01"):
    return SimpleNamespace(title=title, link=link, summary=summary, published=published)


def _ctx(tmp_config, tmp_path):
    cfg = load_config(tmp_config)
    # inject a source URL
    cfg.rss_sources.append("https://example.com/feed")
    repo = JobRepository(cfg.db_path)
    repo.init_schema()
    folder = JobFolder.create(cfg.jobs_dir, "2026-07-01", "slug")
    repo.create_job(folder.job_id, "slug", "2026-07-01", cfg.all_languages)
    return cfg, repo, folder, StageContext(folder.job_id, folder, cfg, repo)


def test_ingest_writes_candidates_without_body(tmp_config, tmp_path):
    cfg, repo, folder, ctx = _ctx(tmp_config, tmp_path)
    entries = [
        _entry("Tesla cuts price", "http://a", "First sentence. Second sentence. Third. Fourth."),
        _entry("Rivian R2 ships", "http://b", "Only one sentence here."),
    ]
    stage = IngestStage(fetch=lambda url: _fake_feed(entries))
    result = stage.run(ctx)
    assert result.status is StageStatus.DONE
    data = folder.read_json(folder.root / "ingest.json")
    assert len(data) == 2
    assert data[0]["title"] == "Tesla cuts price"
    assert data[0]["link"] == "http://a"
    assert len(data[0]["points"]) <= 3   # capped, never the full body
    assert "summary" not in data[0]       # no raw body field stored


def test_ingest_fails_when_no_candidates(tmp_config, tmp_path):
    cfg, repo, folder, ctx = _ctx(tmp_config, tmp_path)
    stage = IngestStage(fetch=lambda url: _fake_feed([]))
    result = stage.run(ctx)
    assert result.status is StageStatus.FAILED
