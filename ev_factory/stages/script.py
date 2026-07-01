from __future__ import annotations

from ev_factory.compliance import ComplianceReport
from ev_factory.models import JobState, StageResult
from ev_factory.originality import passes_originality
from ev_factory.stages.base import Stage, StageContext

SCRIPT_SYSTEM = (
    "You are a scriptwriter for an electric-vehicle news channel. Write an ORIGINAL "
    "spoken commentary script (~200 words) on the given story and angle. Add analysis, "
    "opinion, comparison, and context. NEVER reproduce source phrasing. Cite sources by "
    "name in-line. Output only the script text."
)


def _prompt(story: dict) -> str:
    points = "\n".join(f"- {p}" for p in story.get("points", []))
    return (
        f"Story: {story['title']}\nAngle: {story['angle']}\n"
        f"Facts:\n{points}\nSources: {', '.join(story.get('sources', []))}"
    )


class ScriptStage(Stage):
    name = "script"
    produces_state = JobState.SCRIPTED

    def __init__(self, llm):
        self._llm = llm

    def run(self, ctx: StageContext) -> StageResult:
        if not ctx.folder.story_json.exists():
            return StageResult.fail(self.name, "no story.json")
        story = ctx.folder.read_json(ctx.folder.story_json)
        source_texts = [story.get("title", ""), *story.get("points", [])]
        prompt = _prompt(story)

        script = self._llm.complete(
            ctx.config.model_script, SCRIPT_SYSTEM, prompt,
            job_id=ctx.job_id, stage=self.name, max_tokens=1024,
        )
        passed, score, vb = passes_originality(
            self._llm, ctx.config, script, source_texts, ctx.job_id
        )
        if not passed:
            # Regenerate once with an explicit push for more originality.
            script = self._llm.complete(
                ctx.config.model_script,
                SCRIPT_SYSTEM + " The previous draft was too close to the source; "
                "be substantially more original and analytical.",
                prompt, job_id=ctx.job_id, stage=self.name, max_tokens=1024,
            )
            passed, score, vb = passes_originality(
                self._llm, ctx.config, script, source_texts, ctx.job_id
            )

        ctx.folder.script_path("en").write_text(script, encoding="utf-8")
        ctx.folder.write_json(
            ctx.folder.root / "script_meta.json",
            {
                "transformation_score": score,
                "verbatim_ok": vb,
                "passed": passed,
                "sources": story.get("sources", []),
            },
        )

        report = ComplianceReport()
        report.add("copyright_text", True, "ingest stored no article body")
        report.add(
            "sources_min_two", not story.get("single_source", False),
            "requires >=2 sources",
        )
        report.add("not_repetitious", True, "curate deduped vs recent slugs")
        report.add("verbatim_clean", vb, "no copied spans" if vb else "copied span found")
        report.add(
            "transformation_score", score >= ctx.config.originality_threshold,
            f"score {score} vs threshold {ctx.config.originality_threshold}",
        )
        ctx.folder.write_json(ctx.folder.compliance_json, report.to_dict())
        return StageResult.ok(self.name, data={"passed": passed, "score": score})
