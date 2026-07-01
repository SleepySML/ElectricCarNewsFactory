import textwrap
from pathlib import Path

import pytest


@pytest.fixture
def tmp_config(tmp_path: Path) -> Path:
    """Write a minimal config.toml into a temp dir and return its path."""
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        textwrap.dedent(
            f"""
            jobs_dir = "{(tmp_path / 'jobs').as_posix()}"
            db_path = "{(tmp_path / 'ev_factory.db').as_posix()}"
            source_language = "en"
            target_languages = ["ru", "tr"]
            dry_run = true
            monthly_spend_cap_usd = 90.0
            rss_sources = []
            """
        ).strip()
    )
    return cfg
