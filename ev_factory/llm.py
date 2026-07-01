from __future__ import annotations

from datetime import datetime, timezone

from ev_factory.config import Config
from ev_factory.db import JobRepository

# (input_usd_per_1M, output_usd_per_1M)
PRICING: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-sonnet-4-6": (3.0, 15.0),
}


class SpendCapExceeded(Exception):
    pass


def _cost(model: str, in_tok: int, out_tok: int) -> float:
    in_price, out_price = PRICING.get(model, (0.0, 0.0))
    return in_tok / 1_000_000 * in_price + out_tok / 1_000_000 * out_price


class LLMClient:
    def __init__(self, config: Config, repo: JobRepository, client=None):
        self.config = config
        self.repo = repo
        self._client = client  # injected for tests; else lazily created

    def _ensure_client(self):
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY
        return self._client

    def complete(
        self,
        model: str,
        system: str,
        prompt: str,
        job_id: str,
        stage: str,
        max_tokens: int = 1024,
    ) -> str:
        if self.config.dry_run:
            raise RuntimeError(
                "LLMClient.complete called in dry_run; inject a fake client instead"
            )
        month = datetime.now(timezone.utc).isoformat()[:7]
        if self.repo.spend_this_month(month) >= self.config.monthly_spend_cap_usd:
            raise SpendCapExceeded(
                f"monthly spend cap {self.config.monthly_spend_cap_usd} reached"
            )
        client = self._ensure_client()
        resp = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
        self.repo.record_cost(
            job_id, stage, "anthropic",
            _cost(model, resp.usage.input_tokens, resp.usage.output_tokens),
        )
        return text
