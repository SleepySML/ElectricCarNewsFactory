from pathlib import Path

from ev_factory.cli import main
from ev_factory.config import load_config
from ev_factory.db import JobRepository
from ev_factory.models import JobState


def test_create_makes_job_and_folder(tmp_config: Path, capsys):
    rc = main(["create", "--title", "Tesla Cuts Price!", "--date", "2026-07-01",
               "--config", str(tmp_config)])
    assert rc == 0
    job_id = capsys.readouterr().out.strip()
    assert job_id == "2026-07-01-tesla-cuts-price"

    cfg = load_config(tmp_config)
    assert (cfg.jobs_dir / job_id / "story.json").exists()
    repo = JobRepository(cfg.db_path)
    assert repo.get_job(job_id)["state"] == JobState.NEW
    assert set(repo.get_language_statuses(job_id)) == {"en", "ru", "tr"}


def test_status_lists_jobs(tmp_config: Path, capsys):
    main(["create", "--title", "A", "--date", "2026-07-01", "--config", str(tmp_config)])
    capsys.readouterr()
    rc = main(["status", "--config", str(tmp_config)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "2026-07-01-a" in out
    assert "new" in out
