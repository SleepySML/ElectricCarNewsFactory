from dataclasses import replace
from types import SimpleNamespace

import pytest

from ev_factory.config import load_config
from ev_factory.db import JobRepository
from ev_factory.llm import LLMClient, SpendCapExceeded, PRICING


class FakeMessages:
    def __init__(self, text, in_tok, out_tok):
        self._text = text
        self._in = in_tok
        self._out = out_tok
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=self._text)],
            usage=SimpleNamespace(input_tokens=self._in, output_tokens=self._out),
        )


class FakeAnthropic:
    def __init__(self, text="hello", in_tok=1000, out_tok=2000):
        self.messages = FakeMessages(text, in_tok, out_tok)


def _repo(tmp_path):
    repo = JobRepository(tmp_path / "t.db")
    repo.init_schema()
    repo.create_job("j", "slug", "2026-07-01", ["en"])
    return repo


def _live_cfg(tmp_config):
    return replace(load_config(tmp_config), dry_run=False)


def test_complete_returns_text_and_logs_cost(tmp_config, tmp_path):
    cfg = _live_cfg(tmp_config)
    repo = _repo(tmp_path)
    fake = FakeAnthropic(text="the answer", in_tok=1_000_000, out_tok=1_000_000)
    llm = LLMClient(cfg, repo, client=fake)
    out = llm.complete(cfg.model_curate, "sys", "prompt", job_id="j", stage="curate")
    assert out == "the answer"
    # haiku pricing: 1.0 in + 5.0 out per 1M -> exactly 6.0 for 1M+1M
    month = repo.get_job("j")["created_at"][:7]
    assert abs(repo.spend_this_month(month) - 6.0) < 1e-9


def test_spend_cap_blocks_before_calling(tmp_config, tmp_path):
    cfg = _live_cfg(tmp_config)
    repo = _repo(tmp_path)
    # Pre-load spend at/over the cap.
    repo.record_cost("j", "prior", "anthropic", cfg.monthly_spend_cap_usd)
    fake = FakeAnthropic()
    llm = LLMClient(cfg, repo, client=fake)
    with pytest.raises(SpendCapExceeded):
        llm.complete(cfg.model_script, "sys", "p", job_id="j", stage="script")
    assert fake.messages.calls == []  # never called the API


def test_pricing_has_both_models():
    assert PRICING["claude-haiku-4-5"] == (1.0, 5.0)
    assert PRICING["claude-sonnet-4-6"] == (3.0, 15.0)
