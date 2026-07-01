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
    model_curate: str = "claude-haiku-4-5"
    model_script: str = "claude-sonnet-4-6"
    originality_threshold: int = 70
    verbatim_span_words: int = 8
    dedup_window: int = 20

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
        model_curate=data.get("model_curate", "claude-haiku-4-5"),
        model_script=data.get("model_script", "claude-sonnet-4-6"),
        originality_threshold=int(data.get("originality_threshold", 70)),
        verbatim_span_words=int(data.get("verbatim_span_words", 8)),
        dedup_window=int(data.get("dedup_window", 20)),
    )
