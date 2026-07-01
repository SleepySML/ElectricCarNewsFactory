from __future__ import annotations

from ev_factory.llm import SpendCapExceeded
from ev_factory.models import JobState, StageResult
from ev_factory.stages.base import Stage, StageContext

LOCALIZE_SYSTEM = (
    "You are a localizer for an electric-vehicle news channel. Translate and culturally "
    "adapt the following English commentary script into {lang} (ISO-639-1). Keep the "
    "meaning, tone, and length; adapt idioms naturally. Output only the translated script."
)


class LocalizeStage(Stage):
    name = "localize"
    produces_state = JobState.LOCALIZED

    def __init__(self, llm):
        self._llm = llm

    def run(self, ctx: StageContext) -> StageResult:
        en_path = ctx.folder.script_path("en")
        if not en_path.exists():
            return StageResult.fail(self.name, "no script_en.md")
        english = en_path.read_text(encoding="utf-8")

        done, failed = [], []
        for lang in ctx.config.target_languages:
            try:
                translated = self._llm.complete(
                    ctx.config.model_script,
                    LOCALIZE_SYSTEM.format(lang=lang),
                    english,
                    job_id=ctx.job_id,
                    stage=f"{self.name}:{lang}",
                    max_tokens=1024,
                )
                ctx.folder.script_path(lang).write_text(translated, encoding="utf-8")
                ctx.repo.set_language_status(ctx.job_id, lang, "done")
                done.append(lang)
            except SpendCapExceeded:
                raise
            except Exception:  # noqa: BLE001 - isolate one language's failure
                ctx.repo.set_language_status(ctx.job_id, lang, "failed")
                failed.append(lang)
        return StageResult.ok(self.name, data={"done": done, "failed": failed})
