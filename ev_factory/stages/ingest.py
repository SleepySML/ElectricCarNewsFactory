from __future__ import annotations

import re

from ev_factory.models import JobState, StageResult
from ev_factory.stages.base import Stage, StageContext


def _points(summary: str, limit: int = 3) -> list[str]:
    # Split into sentences, keep only short factual fragments, cap the count.
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", summary or "") if s.strip()]
    return [s[:200] for s in sentences[:limit]]


class IngestStage(Stage):
    name = "ingest"
    produces_state = JobState.INGESTED

    def __init__(self, fetch=None):
        if fetch is None:
            import feedparser

            fetch = feedparser.parse
        self._fetch = fetch

    def run(self, ctx: StageContext) -> StageResult:
        candidates = []
        for url in ctx.config.rss_sources:
            feed = self._fetch(url)
            for entry in getattr(feed, "entries", []):
                candidates.append(
                    {
                        "title": getattr(entry, "title", ""),
                        "link": getattr(entry, "link", ""),
                        "source": url,
                        "published": getattr(entry, "published", ""),
                        "points": _points(getattr(entry, "summary", "")),
                    }
                )
        if not candidates:
            return StageResult.fail(self.name, "no candidates")
        ctx.folder.write_json(ctx.folder.root / "ingest.json", candidates)
        return StageResult.ok(self.name, data={"count": len(candidates)})
