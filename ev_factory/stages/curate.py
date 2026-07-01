from __future__ import annotations

import json
import re

from ev_factory.models import JobState, StageResult
from ev_factory.stages.base import Stage, StageContext

CURATE_SYSTEM = (
    "You are an editor for an electric-vehicle news channel. From the candidate "
    "headlines, pick the single most newsworthy story that is NOT similar to the "
    "recent slugs listed. Propose an original ANGLE (a specific take, comparison, or "
    "analysis - not a summary). Reply ONLY with JSON: "
    '{"chosen_index": <int>, "angle": "<one sentence>"}.'
)


def _parse_choice(reply: str) -> dict:
    # Tolerate prose around the JSON: grab the first {...} block.
    m = re.search(r"\{.*\}", reply, re.DOTALL)
    return json.loads(m.group()) if m else json.loads(reply)


class CurateStage(Stage):
    name = "curate"
    produces_state = JobState.STORY_REVIEW

    def __init__(self, llm):
        self._llm = llm

    def run(self, ctx: StageContext) -> StageResult:
        ingest_path = ctx.folder.root / "ingest.json"
        if not ingest_path.exists():
            return StageResult.fail(self.name, "no ingest.json")
        candidates = ctx.folder.read_json(ingest_path)
        if not candidates:
            return StageResult.fail(self.name, "no candidates")

        recent = ctx.repo.recent_slugs(ctx.config.dedup_window)
        listing = "\n".join(
            f"{i}: {c['title']} ({c['link']})" for i, c in enumerate(candidates)
        )
        prompt = (
            f"Recent slugs to avoid repeating:\n{', '.join(recent) or '(none)'}\n\n"
            f"Candidates:\n{listing}"
        )
        reply = self._llm.complete(
            ctx.config.model_curate, CURATE_SYSTEM, prompt,
            job_id=ctx.job_id, stage=self.name,
        )
        choice = _parse_choice(reply)
        idx = int(choice["chosen_index"])
        chosen = candidates[idx]

        same_title_links = {
            c["link"] for c in candidates if c["title"] == chosen["title"]
        }
        story = {
            "title": chosen["title"],
            "link": chosen["link"],
            "source": chosen["source"],
            "points": chosen.get("points", []),
            "angle": choice["angle"],
            "sources": sorted(same_title_links),
            "single_source": len(same_title_links) < 2,
        }
        ctx.folder.write_json(ctx.folder.story_json, story)
        return StageResult.ok(self.name, data={"title": chosen["title"]})
