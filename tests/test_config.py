from pathlib import Path

from ev_factory.config import Config, load_config


def test_load_config_parses_fields(tmp_config: Path):
    cfg = load_config(tmp_config)
    assert isinstance(cfg, Config)
    assert cfg.source_language == "en"
    assert cfg.target_languages == ["ru", "tr"]
    assert cfg.dry_run is True
    assert cfg.monthly_spend_cap_usd == 90.0
    assert isinstance(cfg.jobs_dir, Path)


def test_all_languages_puts_source_first(tmp_config: Path):
    cfg = load_config(tmp_config)
    assert cfg.all_languages == ["en", "ru", "tr"]
