from dataclasses import replace

from ev_factory.config import load_config
from ev_factory.originality import verbatim_clean, rubric_score, passes_originality


class FakeLLM:
    def __init__(self, reply):
        self.reply = reply
        self.calls = 0

    def complete(self, model, system, prompt, job_id, stage, max_tokens=1024):
        self.calls += 1
        return self.reply


def test_verbatim_guard_flags_copied_span():
    source = ["Tesla slashed the Model Y price by ten percent today in Europe"]
    copied = "In big news, Tesla slashed the Model Y price by ten percent today, analysts say."
    assert verbatim_clean(copied, source, span_words=8) is False


def test_verbatim_guard_passes_paraphrase():
    source = ["Tesla slashed the Model Y price by ten percent today in Europe"]
    paraphrase = "Tesla's European Model Y just got notably cheaper, a move worth unpacking."
    assert verbatim_clean(paraphrase, source, span_words=8) is True


def test_rubric_score_parses_and_clamps(tmp_config):
    cfg = load_config(tmp_config)
    assert rubric_score(FakeLLM("Score: 82 — strong analysis"), cfg, "s", "j") == 82
    assert rubric_score(FakeLLM("140"), cfg, "s", "j") == 100
    assert rubric_score(FakeLLM("no number here"), cfg, "s", "j") == 0


def test_passes_requires_both(tmp_config):
    cfg = replace(load_config(tmp_config), originality_threshold=70)
    src = ["alpha beta gamma delta epsilon zeta eta theta iota"]
    # clean paraphrase + high score -> pass
    ok, score, vb = passes_originality(FakeLLM("90"), cfg, "totally different words here", src, "j")
    assert ok is True and score == 90 and vb is True
    # high score but verbatim copy -> fail
    ok, _, vb = passes_originality(
        FakeLLM("90"), cfg, "alpha beta gamma delta epsilon zeta eta theta iota", src, "j"
    )
    assert ok is False and vb is False
    # clean but low score -> fail
    ok, score, _ = passes_originality(FakeLLM("40"), cfg, "unique wording throughout", src, "j")
    assert ok is False and score == 40
