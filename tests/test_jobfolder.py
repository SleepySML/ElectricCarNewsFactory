from pathlib import Path

from ev_factory.jobfolder import JobFolder


def test_create_makes_dirs_and_id(tmp_path: Path):
    jf = JobFolder.create(tmp_path / "jobs", "2026-07-01", "tesla-price-cut")
    assert jf.job_id == "2026-07-01-tesla-price-cut"
    assert jf.audio_dir.is_dir()
    assert jf.video_dir.is_dir()


def test_language_scoped_paths(tmp_path: Path):
    jf = JobFolder.create(tmp_path / "jobs", "2026-07-01", "slug")
    assert jf.script_path("ru").name == "script_ru.md"
    assert jf.metadata_path("tr").name == "metadata_tr.json"


def test_write_and_read_json_roundtrip(tmp_path: Path):
    jf = JobFolder.create(tmp_path / "jobs", "2026-07-01", "slug")
    jf.write_json(jf.story_json, {"title": "Hello", "n": 2})
    assert jf.read_json(jf.story_json) == {"title": "Hello", "n": 2}
