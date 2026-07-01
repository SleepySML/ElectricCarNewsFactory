from __future__ import annotations

import re

RUBRIC_SYSTEM = (
    "You are a strict editorial reviewer scoring how ORIGINAL and TRANSFORMATIVE a "
    "news commentary script is versus merely rephrasing source articles. Score 0-100: "
    "reward original analysis, opinion, comparison, and added context; penalize bland "
    "paraphrase. Reply with the integer score first."
)


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def verbatim_clean(script: str, source_texts: list[str], span_words: int) -> bool:
    script_words = _words(script)
    script_spans = {
        " ".join(script_words[i : i + span_words])
        for i in range(len(script_words) - span_words + 1)
    }
    if not script_spans:
        return True
    for src in source_texts:
        sw = _words(src)
        for i in range(len(sw) - span_words + 1):
            if " ".join(sw[i : i + span_words]) in script_spans:
                return False
    return True


def rubric_score(llm, config, script: str, job_id: str) -> int:
    reply = llm.complete(
        config.model_curate, RUBRIC_SYSTEM, script, job_id=job_id, stage="originality"
    )
    m = re.search(r"\d+", reply)
    if not m:
        return 0
    return max(0, min(100, int(m.group())))


def passes_originality(
    llm, config, script: str, source_texts: list[str], job_id: str
) -> tuple[bool, int, bool]:
    vb = verbatim_clean(script, source_texts, config.verbatim_span_words)
    score = rubric_score(llm, config, script, job_id)
    passed = vb and score >= config.originality_threshold
    return passed, score, vb
