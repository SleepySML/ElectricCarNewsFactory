from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Config:
    jobs_dir: Path
    db_path: Path
    source_language: str
    target_languages: list[str]
    dry_run: bool
    monthly_spend_cap_usd: float
    rss_sources: list[str]

    @property
    def all_languages(self) -> list[str]:
        return [self.source_language, *self.target_languages]


def load_config(path: str | Path) -> Config:
    with open(path, "rb") as fh:
        data = tomllib.load(fh)
    return Config(
        jobs_dir=Path(data["jobs_dir"]),
        db_path=Path(data["db_path"]),
        source_language=data["source_language"],
        target_languages=list(data["target_languages"]),
        dry_run=bool(data["dry_run"]),
        monthly_spend_cap_usd=float(data["monthly_spend_cap_usd"]),
        rss_sources=list(data.get("rss_sources", [])),
    )
