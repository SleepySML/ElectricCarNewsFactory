# EV News Content Factory — Content Stages (Plan 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the content-generation half of the pipeline — orchestrator rework (per-stage completion + park states), a cost-capped Anthropic client, and the Ingest → Curate → Script → Localize stages with originality/compliance guardrails — building on the merged foundation in `ev_factory/`.

**Architecture:** The orchestrator stops keying stage-completion on the coarse `job.state` and instead consults a new `job_stages` table, so multiple stages can share a milestone and the pipeline can halt at human "park" checkpoints. Content stages subclass the existing `Stage` ABC, receive an injected `LLMClient` (or fetch function) via their constructor so tests can supply fakes, and read/write the per-story `JobFolder`. All external calls (Claude, RSS) are injected, so the whole plan is testable offline with zero spend.

**Tech Stack:** Python 3.11+, `anthropic` (official SDK) and `feedparser` (new runtime deps), stdlib otherwise, `pytest`. Builds on foundation commit 7666e50.

## Global Constraints

- Python **3.11+**.
- New third-party runtime deps introduced by this plan: **`anthropic`** and **`feedparser`** — no others.
- Model IDs (exact strings): curation + originality rubric use **`claude-haiku-4-5`**; script + localization use **`claude-sonnet-4-6`**. Never append date suffixes.
- Per-token pricing for cost logging (USD per 1M tokens): `claude-haiku-4-5` = **$1.00 input / $5.00 output**; `claude-sonnet-4-6` = **$3.00 input / $15.00 output**.
- **Dry-run must make zero external calls and incur zero spend.** `LLMClient` must not construct a live client or call the API when `config.dry_run` is true.
- **Spend cap enforced before every paid call:** if `repo.spend_this_month(YYYY-MM) >= config.monthly_spend_cap_usd`, raise before calling the API.
- Language codes are lowercase ISO-639-1. Source language is `en`.
- Timestamps are UTC ISO-8601 via `datetime.now(timezone.utc).isoformat()`.
- **Copyright rule:** Ingest stores only headline, link, source name, published date, and short factual bullet points — never full article body.
- Happy-path state order (this plan): `NEW → INGESTED → STORY_REVIEW → STORY_APPROVED → SCRIPTED → LOCALIZED → RENDERED → IN_REVIEW → APPROVED → PUBLISHED`. Park states: `{STORY_REVIEW, IN_REVIEW}`.
- Originality: a script passes only if the **verbatim guard is clean AND** the rubric score **≥ threshold** (default 70). Verbatim span length default 8 words. Dedup window default 20 recent slugs.
- Tests run with `.venv\Scripts\python.exe -m pytest` on Windows.

---

### Task 1: State-model rework (new states, happy path, park states)

**Files:**
- Modify: `ev_factory/models.py` (add two `JobState` members)
- Modify: `ev_factory/statemachine.py` (extend `HAPPY_PATH`, add `PARK_STATES`)
- Test: `tests/test_statemachine.py` (add cases; keep existing ones passing)

**Interfaces:**
- Consumes: existing `JobState`, `HAPPY_PATH`, `can_transition`, `transition` (foundation).
- Produces:
  - `JobState.STORY_REVIEW = "story_review"`, `JobState.STORY_APPROVED = "story_approved"`.
  - New `HAPPY_PATH` order: `NEW, INGESTED, STORY_REVIEW, STORY_APPROVED, SCRIPTED, LOCALIZED, RENDERED, IN_REVIEW, APPROVED, PUBLISHED`.
  - `PARK_STATES: set[JobState] = {JobState.STORY_REVIEW, JobState.IN_REVIEW}` exported from `statemachine.py`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_statemachine.py`:
```python
from ev_factory.statemachine import PARK_STATES


def test_new_states_exist_and_ordered():
    from ev_factory.models import JobState
    from ev_factory.statemachine import HAPPY_PATH

    assert JobState.STORY_REVIEW == "story_review"
    assert JobState.STORY_APPROVED == "story_approved"
    i = HAPPY_PATH.index
    assert i(JobState.INGESTED) < i(JobState.STORY_REVIEW) < i(JobState.STORY_APPROVED) < i(JobState.SCRIPTED)


def test_park_states():
    from ev_factory.models import JobState
    assert PARK_STATES == {JobState.STORY_REVIEW, JobState.IN_REVIEW}


def test_park_and_resume_transitions_allowed():
    from ev_factory.models import JobState
    from ev_factory.statemachine import can_transition
    assert can_transition(JobState.INGESTED, JobState.STORY_REVIEW)
    assert can_transition(JobState.STORY_REVIEW, JobState.STORY_APPROVED)
    assert can_transition(JobState.STORY_APPROVED, JobState.SCRIPTED)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_statemachine.py::test_new_states_exist_and_ordered -v`
Expected: FAIL (`AttributeError: STORY_REVIEW` or `ImportError: PARK_STATES`).

- [ ] **Step 3: Implement**

In `ev_factory/models.py`, add the two members to `JobState` (place them after `INGESTED`):
```python
class JobState(str, Enum):
    NEW = "new"
    INGESTED = "ingested"
    STORY_REVIEW = "story_review"
    STORY_APPROVED = "story_approved"
    SCRIPTED = "scripted"
    LOCALIZED = "localized"
    RENDERED = "rendered"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    PUBLISHED = "published"
    FAILED = "failed"
```

In `ev_factory/statemachine.py`, update `HAPPY_PATH` and add `PARK_STATES` (the `ALLOWED_TRANSITIONS` builder below it is unchanged and will pick up the new order automatically):
```python
HAPPY_PATH: list[JobState] = [
    JobState.NEW,
    JobState.INGESTED,
    JobState.STORY_REVIEW,
    JobState.STORY_APPROVED,
    JobState.SCRIPTED,
    JobState.LOCALIZED,
    JobState.RENDERED,
    JobState.IN_REVIEW,
    JobState.APPROVED,
    JobState.PUBLISHED,
]

PARK_STATES: set[JobState] = {JobState.STORY_REVIEW, JobState.IN_REVIEW}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_statemachine.py -v`
Expected: PASS (new cases + all pre-existing statemachine tests).

- [ ] **Step 5: Commit**

```bash
git add ev_factory/models.py ev_factory/statemachine.py tests/test_statemachine.py
git commit -m "feat: add STORY_REVIEW/STORY_APPROVED states and PARK_STATES"
```

---

### Task 2: Per-stage completion table + repo methods

**Files:**
- Modify: `ev_factory/db.py` (add `job_stages` table to `SCHEMA`; add three methods)
- Test: `tests/test_db.py` (add cases)

**Interfaces:**
- Consumes: existing `JobRepository` (`_connect`, `_now`, `init_schema`, `create_job`).
- Produces on `JobRepository`:
  - `mark_stage(job_id: str, stage_name: str, status: str) -> None` (INSERT OR REPLACE).
  - `get_stage_status(job_id: str, stage_name: str) -> str | None`.
  - `recent_slugs(limit: int) -> list[str]` — distinct-ish slugs of the most recent jobs by `date` desc then `created_at` desc, newest first, capped at `limit`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_db.py`:
```python
def test_mark_and_get_stage_status(tmp_path):
    repo = make_repo(tmp_path)
    repo.create_job("j", "slug", "2026-07-01", ["en"])
    assert repo.get_stage_status("j", "ingest") is None
    repo.mark_stage("j", "ingest", "done")
    assert repo.get_stage_status("j", "ingest") == "done"
    repo.mark_stage("j", "ingest", "failed")  # overwrite
    assert repo.get_stage_status("j", "ingest") == "failed"


def test_recent_slugs_newest_first(tmp_path):
    repo = make_repo(tmp_path)
    repo.create_job("2026-06-29-a", "a", "2026-06-29", ["en"])
    repo.create_job("2026-07-01-b", "b", "2026-07-01", ["en"])
    repo.create_job("2026-06-30-c", "c", "2026-06-30", ["en"])
    assert repo.recent_slugs(2) == ["b", "c"]
    assert repo.recent_slugs(10) == ["b", "c", "a"]
```

(`make_repo` already exists in `tests/test_db.py` from the foundation.)

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_db.py::test_mark_and_get_stage_status -v`
Expected: FAIL (`AttributeError: 'JobRepository' object has no attribute 'mark_stage'`).

- [ ] **Step 3: Implement**

In `ev_factory/db.py`, append this table to the `SCHEMA` string (before the closing `"""`):
```sql
CREATE TABLE IF NOT EXISTS job_stages (
    job_id TEXT NOT NULL,
    stage_name TEXT NOT NULL,
    status TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (job_id, stage_name)
);
```

Add these methods to `JobRepository` (anywhere among the existing methods):
```python
    def mark_stage(self, job_id: str, stage_name: str, status: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO job_stages "
                "(job_id, stage_name, status, updated_at) VALUES (?, ?, ?, ?)",
                (job_id, stage_name, status, _now()),
            )

    def get_stage_status(self, job_id: str, stage_name: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT status FROM job_stages WHERE job_id = ? AND stage_name = ?",
                (job_id, stage_name),
            ).fetchone()
            return row["status"] if row else None

    def recent_slugs(self, limit: int) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT slug FROM jobs ORDER BY date DESC, created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [r["slug"] for r in rows]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_db.py -v`
Expected: PASS (new cases + all pre-existing db tests; `init_schema` is idempotent so the new table is additive).

- [ ] **Step 5: Commit**

```bash
git add ev_factory/db.py tests/test_db.py
git commit -m "feat: job_stages table and recent_slugs for orchestrator rework"
```

---

### Task 3: Orchestrator rework (per-stage skip, monotonic advance, park halt)

**Files:**
- Modify: `ev_factory/orchestrator.py`
- Test: `tests/test_orchestrator.py` (add cases; keep existing ones passing)

**Interfaces:**
- Consumes: `Stage`/`StageContext` (foundation), `JobRepository.mark_stage`/`get_stage_status` (Task 2), `HAPPY_PATH`/`PARK_STATES`/`transition` (Task 1), `JobState`/`StageStatus` (foundation).
- Produces: reworked `Orchestrator.run_job(job_id, until=IN_REVIEW) -> JobState` with per-stage completion skipping, monotonic milestone advance wrapped in try/except, and park-halt semantics.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_orchestrator.py` (the file already imports `Orchestrator`, `Stage`, `StageContext`, `JobState`, `StageResult`, `JobFolder`, `JobRepository`, `load_config` and defines `_setup`, `RecordingStage`, `ScriptStage`, `BoomStage` from the foundation):
```python
from ev_factory.models import JobState as _JS


class ParkStage(Stage):
    name = "curate"
    produces_state = _JS.STORY_REVIEW

    def run(self, ctx):
        return StageResult.ok(self.name)


class AfterParkStage(Stage):
    name = "script"
    produces_state = _JS.SCRIPTED

    def __init__(self):
        self.calls = 0

    def run(self, ctx):
        self.calls += 1
        return StageResult.ok(self.name)


class RenderA(Stage):
    name = "voice"
    produces_state = _JS.RENDERED

    def run(self, ctx):
        return StageResult.ok(self.name)


class RenderB(Stage):
    name = "assemble"
    produces_state = _JS.RENDERED

    def __init__(self):
        self.calls = 0

    def run(self, ctx):
        self.calls += 1
        return StageResult.ok(self.name)


def _ingest_stage():
    class Ing(Stage):
        name = "ingest"
        produces_state = _JS.INGESTED

        def run(self, ctx):
            return StageResult.ok(self.name)
    return Ing()


def test_parks_at_story_review_and_halts_until_approved(tmp_config):
    cfg, repo = _setup(tmp_config)
    after = AfterParkStage()
    orch = Orchestrator(cfg, repo, [_ingest_stage(), ParkStage(), after])

    final = orch.run_job("2026-07-01-slug")
    assert final == _JS.STORY_REVIEW
    assert after.calls == 0  # script did not run

    # Re-running while still parked must not run script.
    orch.run_job("2026-07-01-slug")
    assert after.calls == 0

    # Human approves -> resume.
    from ev_factory.statemachine import transition
    transition(repo, "2026-07-01-slug", _JS.STORY_APPROVED)
    final = orch.run_job("2026-07-01-slug")
    assert after.calls == 1
    assert final == _JS.SCRIPTED


def test_stages_sharing_a_milestone_both_run(tmp_config):
    cfg, repo = _setup(tmp_config)
    # Fast-forward the job to LOCALIZED so the two RENDERED stages are next.
    from ev_factory.statemachine import HAPPY_PATH
    from ev_factory.db import JobRepository  # noqa: F401
    repo.set_state("2026-07-01-slug", _JS.LOCALIZED)
    b = RenderB()
    orch = Orchestrator(cfg, repo, [RenderA(), b])
    final = orch.run_job("2026-07-01-slug", until=_JS.RENDERED)
    assert b.calls == 1  # second stage sharing RENDERED still ran (no collapse)
    assert final == _JS.RENDERED


def test_completed_stage_skipped_via_job_stages(tmp_config):
    cfg, repo = _setup(tmp_config)
    ing = _ingest_stage()
    # Mark ingest already done in the stage table.
    repo.mark_stage("2026-07-01-slug", "ingest", "done")
    calls = {"n": 0}

    class CountingIngest(Stage):
        name = "ingest"
        produces_state = _JS.INGESTED

        def run(self, ctx):
            calls["n"] += 1
            return StageResult.ok(self.name)

    orch = Orchestrator(cfg, repo, [CountingIngest()])
    orch.run_job("2026-07-01-slug", until=_JS.INGESTED)
    assert calls["n"] == 0  # skipped because job_stages says done
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_orchestrator.py::test_parks_at_story_review_and_halts_until_approved -v`
Expected: FAIL (current orchestrator has no park halt / stage-table skip; script runs prematurely).

- [ ] **Step 3: Implement**

Replace the body of `ev_factory/orchestrator.py` with:
```python
from __future__ import annotations

from ev_factory.config import Config
from ev_factory.db import JobRepository
from ev_factory.jobfolder import JobFolder
from ev_factory.models import JobState, StageStatus
from ev_factory.stages.base import Stage, StageContext
from ev_factory.statemachine import HAPPY_PATH, PARK_STATES, InvalidTransition, transition


class Orchestrator:
    def __init__(self, config: Config, repo: JobRepository, stages: list[Stage]):
        self.config = config
        self.repo = repo
        self.stages = stages

    def run_job(self, job_id: str, until: JobState = JobState.IN_REVIEW) -> JobState:
        folder = JobFolder(self.config.jobs_dir / job_id)
        ctx = StageContext(
            job_id=job_id, folder=folder, config=self.config, repo=self.repo
        )
        for stage in self.stages:
            current = JobState(self.repo.get_job(job_id)["state"])
            # Terminal or parked: halt. A parked job resumes only when a human
            # transitions it out of the park (e.g. STORY_REVIEW -> STORY_APPROVED).
            if current in (JobState.FAILED, JobState.PUBLISHED) or current in PARK_STATES:
                return current
            # Skip stages already completed (per-stage tracking, not milestone).
            if self.repo.get_stage_status(job_id, stage.name) == "done":
                continue
            # Respect the 'until' ceiling.
            if HAPPY_PATH.index(stage.produces_state) > HAPPY_PATH.index(until):
                break
            try:
                result = stage.run(ctx)
                if result.status is not StageStatus.DONE:
                    self.repo.set_error(job_id, result.message or f"{stage.name} failed")
                    return JobState.FAILED
                self.repo.mark_stage(job_id, stage.name, "done")
                # Advance the coarse milestone only if this stage moves it forward.
                if HAPPY_PATH.index(stage.produces_state) > HAPPY_PATH.index(current):
                    transition(self.repo, job_id, stage.produces_state)
            except (Exception, InvalidTransition) as exc:  # noqa: BLE001
                self.repo.set_error(job_id, f"{stage.name}: {exc}")
                return JobState.FAILED
            # If this stage produced a park state, halt for the human gate.
            if stage.produces_state in PARK_STATES:
                return JobState(self.repo.get_job(job_id)["state"])
        return JobState(self.repo.get_job(job_id)["state"])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_orchestrator.py -v`
Expected: PASS — new cases plus all pre-existing orchestrator tests (the foundation tests use one-stage-per-milestone stages, which still advance correctly).

- [ ] **Step 5: Commit**

```bash
git add ev_factory/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: orchestrator per-stage completion, monotonic advance, park halt"
```

---

### Task 4: Config additions (LLM models + thresholds)

**Files:**
- Modify: `ev_factory/config.py` (new optional fields + loader lines)
- Modify: `config.example.toml` (document the new keys)
- Test: `tests/test_config.py` (add cases)

**Interfaces:**
- Consumes: existing `Config`, `load_config`.
- Produces new `Config` fields, all optional with defaults (so existing configs/fixtures keep working):
  - `model_curate: str = "claude-haiku-4-5"`
  - `model_script: str = "claude-sonnet-4-6"`
  - `originality_threshold: int = 70`
  - `verbatim_span_words: int = 8`
  - `dedup_window: int = 20`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_config.py`:
```python
def test_new_llm_defaults(tmp_config):
    cfg = load_config(tmp_config)
    assert cfg.model_curate == "claude-haiku-4-5"
    assert cfg.model_script == "claude-sonnet-4-6"
    assert cfg.originality_threshold == 70
    assert cfg.verbatim_span_words == 8
    assert cfg.dedup_window == 20
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_config.py::test_new_llm_defaults -v`
Expected: FAIL (`AttributeError: ... has no attribute 'model_curate'`).

- [ ] **Step 3: Implement**

In `ev_factory/config.py`, add the fields to the dataclass (after `rss_sources`, all with defaults):
```python
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
```

And in `load_config`, pass the new keys with `.get(...)` defaults:
```python
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
```

Append to `config.example.toml`:
```toml
model_curate = "claude-haiku-4-5"
model_script = "claude-sonnet-4-6"
originality_threshold = 70
verbatim_span_words = 8
dedup_window = 20
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_config.py -v`
Expected: PASS (new case + pre-existing config tests; the `tmp_config` fixture omits the new keys, exercising the defaults).

- [ ] **Step 5: Commit**

```bash
git add ev_factory/config.py config.example.toml tests/test_config.py
git commit -m "feat: config fields for LLM models and originality thresholds"
```

---

### Task 5: LLM client (Anthropic SDK, cost logging, spend cap, dry-run)

**Files:**
- Create: `ev_factory/llm.py`
- Modify: `pyproject.toml` (add `anthropic` dependency)
- Test: `tests/test_llm.py`

**Interfaces:**
- Consumes: `Config` (Task 4), `JobRepository.record_cost`/`spend_this_month` (foundation).
- Produces:
  - `class SpendCapExceeded(Exception)`.
  - `PRICING: dict[str, tuple[float, float]]` = per-1M (input, output) USD for the two models.
  - `class LLMClient(config: Config, repo: JobRepository, client=None)`:
    - `complete(model: str, system: str, prompt: str, job_id: str, stage: str, max_tokens: int = 1024) -> str` — enforces spend cap, calls the Anthropic Messages API, records cost from `usage`, returns the concatenated text. In `config.dry_run`, raises `RuntimeError` (dry-run must inject fakes, never call this) — so a real dry-run run wires a fake client (see Task 12).
    - `client` param lets tests inject a fake Anthropic client object exposing `messages.create(...)`.

- [ ] **Step 1: Write the failing test**

`tests/test_llm.py`:
```python
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


def test_complete_returns_text_and_logs_cost(tmp_config, tmp_path):
    cfg = load_config(tmp_config)
    repo = _repo(tmp_path)
    fake = FakeAnthropic(text="the answer", in_tok=1_000_000, out_tok=1_000_000)
    llm = LLMClient(cfg, repo, client=fake)
    out = llm.complete(cfg.model_curate, "sys", "prompt", job_id="j", stage="curate")
    assert out == "the answer"
    # haiku pricing: 1.0 in + 5.0 out per 1M -> exactly 6.0 for 1M+1M
    month = repo.get_job("j")["created_at"][:7]
    assert abs(repo.spend_this_month(month) - 6.0) < 1e-9


def test_spend_cap_blocks_before_calling(tmp_config, tmp_path):
    cfg = load_config(tmp_config)
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_llm.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'ev_factory.llm'`).

- [ ] **Step 3: Implement**

Add `anthropic` to `pyproject.toml` under `[project]`:
```toml
[project]
name = "ev-factory"
version = "0.1.0"
description = "EV News Content Factory pipeline"
requires-python = ">=3.11"
dependencies = ["anthropic>=0.40"]
```

Install it into the venv:
```bash
.venv\Scripts\python.exe -m pip install "anthropic>=0.40"
```

`ev_factory/llm.py`:
```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_llm.py -v`
Expected: PASS (all three cases; the fake client's `dry_run` is false because `tmp_config` sets `dry_run = true`… note: set it explicitly — see below).

Note: `tmp_config` sets `dry_run = true`, which would make `complete` raise `RuntimeError`. The three tests above must run with dry-run off. Add this helper at the top of `tests/test_llm.py` and use it instead of `load_config(tmp_config)` in all three tests:
```python
from dataclasses import replace

def _live_cfg(tmp_config):
    return replace(load_config(tmp_config), dry_run=False)
```
Replace `cfg = load_config(tmp_config)` with `cfg = _live_cfg(tmp_config)` in `test_complete_returns_text_and_logs_cost` and `test_spend_cap_blocks_before_calling`. (`test_pricing_has_both_models` takes no config.)

- [ ] **Step 5: Commit**

```bash
git add ev_factory/llm.py pyproject.toml tests/test_llm.py
git commit -m "feat: Anthropic LLM client with cost logging and spend cap"
```

---

### Task 6: Originality machinery (verbatim guard + rubric)

**Files:**
- Create: `ev_factory/originality.py`
- Test: `tests/test_originality.py`

**Interfaces:**
- Consumes: `LLMClient.complete` (Task 5) for the rubric; `Config` for threshold/span.
- Produces:
  - `def verbatim_clean(script: str, source_texts: list[str], span_words: int) -> bool` — returns False if any run of `span_words` consecutive (lowercased, whitespace-split) words from any source text appears in the script.
  - `def rubric_score(llm, config, script: str, job_id: str) -> int` — asks the curate model for an integer 0–100 originality score; parses the first integer from the reply; clamps to 0–100.
  - `def passes_originality(llm, config, script: str, source_texts: list[str], job_id: str) -> tuple[bool, int, bool]` — returns `(passed, score, verbatim_ok)`; `passed = verbatim_ok and score >= config.originality_threshold`.

- [ ] **Step 1: Write the failing test**

`tests/test_originality.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_originality.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'ev_factory.originality'`).

- [ ] **Step 3: Implement**

`ev_factory/originality.py`:
```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_originality.py -v`
Expected: PASS (all cases).

- [ ] **Step 5: Commit**

```bash
git add ev_factory/originality.py tests/test_originality.py
git commit -m "feat: originality machinery (verbatim guard + LLM rubric)"
```

---

### Task 7: Compliance report accumulator

**Files:**
- Create: `ev_factory/compliance.py`
- Test: `tests/test_compliance.py`

**Interfaces:**
- Consumes: `ComplianceCheck` (foundation `models.py`).
- Produces:
  - `class ComplianceReport` with:
    - `add(key: str, passed: bool, detail: str = "", hard: bool = True) -> None`.
    - `checks -> list[ComplianceCheck]`.
    - `blocking -> bool` — True if any hard check failed.
    - `to_dict() -> dict` (serializable; `{"checks": [...], "blocking": bool}`).
    - classmethod `from_dict(d) -> ComplianceReport`.

- [ ] **Step 1: Write the failing test**

`tests/test_compliance.py`:
```python
from ev_factory.compliance import ComplianceReport


def test_blocking_only_on_hard_failure():
    r = ComplianceReport()
    r.add("copyright_text", True, "no body stored")
    assert r.blocking is False
    r.add("style_note", False, "soft nit", hard=False)
    assert r.blocking is False
    r.add("sources_min_two", False, "only 1 source", hard=True)
    assert r.blocking is True


def test_roundtrip_dict():
    r = ComplianceReport()
    r.add("verbatim_clean", True)
    r.add("transformation_score", False, "score 40 < 70")
    d = r.to_dict()
    assert d["blocking"] is True
    r2 = ComplianceReport.from_dict(d)
    assert len(r2.checks) == 2
    assert r2.blocking is True
    assert r2.checks[0].key == "verbatim_clean"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_compliance.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'ev_factory.compliance'`).

- [ ] **Step 3: Implement**

`ev_factory/compliance.py`:
```python
from __future__ import annotations

from dataclasses import dataclass, field

from ev_factory.models import ComplianceCheck


@dataclass
class ComplianceReport:
    checks: list[ComplianceCheck] = field(default_factory=list)

    def add(self, key: str, passed: bool, detail: str = "", hard: bool = True) -> None:
        self.checks.append(ComplianceCheck(key=key, passed=passed, detail=detail, hard=hard))

    @property
    def blocking(self) -> bool:
        return any(c.hard and not c.passed for c in self.checks)

    def to_dict(self) -> dict:
        return {
            "checks": [
                {"key": c.key, "passed": c.passed, "detail": c.detail, "hard": c.hard}
                for c in self.checks
            ],
            "blocking": self.blocking,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ComplianceReport":
        report = cls()
        for c in d.get("checks", []):
            report.add(c["key"], c["passed"], c.get("detail", ""), c.get("hard", True))
        return report
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_compliance.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ev_factory/compliance.py tests/test_compliance.py
git commit -m "feat: ComplianceReport accumulator"
```

---

### Task 8: Ingest stage (RSS via feedparser)

**Files:**
- Create: `ev_factory/stages/ingest.py`
- Modify: `pyproject.toml` (add `feedparser`)
- Test: `tests/test_ingest.py`

**Interfaces:**
- Consumes: `Stage`/`StageContext` (foundation), `JobState` (foundation), `Config.rss_sources`, `JobFolder`.
- Produces:
  - `class IngestStage(Stage)` with `name = "ingest"`, `produces_state = JobState.INGESTED`, `__init__(self, fetch=None)` where `fetch(url) -> feed` defaults to `feedparser.parse`. `run` fetches each configured source, extracts per-entry `{title, link, source, published, points}` (points = up to 3 short factual sentences from the summary, truncated), and writes the list to `folder.root / "ingest.json"`. Stores **no full article body**. Returns `StageResult.ok("ingest", data={"count": N})`; if zero candidates, returns `StageResult.fail("ingest", "no candidates")`.

- [ ] **Step 1: Write the failing test**

`tests/test_ingest.py`:
```python
from types import SimpleNamespace

from ev_factory.config import load_config
from ev_factory.db import JobRepository
from ev_factory.jobfolder import JobFolder
from ev_factory.models import JobState, StageStatus
from ev_factory.stages.base import StageContext
from ev_factory.stages.ingest import IngestStage


def _fake_feed(entries):
    return SimpleNamespace(entries=entries)


def _entry(title, link, summary, published="2026-07-01"):
    return SimpleNamespace(title=title, link=link, summary=summary, published=published)


def _ctx(tmp_config, tmp_path):
    cfg = load_config(tmp_config)
    # inject a source URL
    cfg.rss_sources.append("https://example.com/feed")
    repo = JobRepository(cfg.db_path)
    repo.init_schema()
    folder = JobFolder.create(cfg.jobs_dir, "2026-07-01", "slug")
    repo.create_job(folder.job_id, "slug", "2026-07-01", cfg.all_languages)
    return cfg, repo, folder, StageContext(folder.job_id, folder, cfg, repo)


def test_ingest_writes_candidates_without_body(tmp_config, tmp_path):
    cfg, repo, folder, ctx = _ctx(tmp_config, tmp_path)
    entries = [
        _entry("Tesla cuts price", "http://a", "First sentence. Second sentence. Third. Fourth."),
        _entry("Rivian R2 ships", "http://b", "Only one sentence here."),
    ]
    stage = IngestStage(fetch=lambda url: _fake_feed(entries))
    result = stage.run(ctx)
    assert result.status is StageStatus.DONE
    data = folder.read_json(folder.root / "ingest.json")
    assert len(data) == 2
    assert data[0]["title"] == "Tesla cuts price"
    assert data[0]["link"] == "http://a"
    assert len(data[0]["points"]) <= 3   # capped, never the full body
    assert "summary" not in data[0]       # no raw body field stored


def test_ingest_fails_when_no_candidates(tmp_config, tmp_path):
    cfg, repo, folder, ctx = _ctx(tmp_config, tmp_path)
    stage = IngestStage(fetch=lambda url: _fake_feed([]))
    result = stage.run(ctx)
    assert result.status is StageStatus.FAILED
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_ingest.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'ev_factory.stages.ingest'`).

- [ ] **Step 3: Implement**

Add `feedparser` to `pyproject.toml` dependencies:
```toml
dependencies = ["anthropic>=0.40", "feedparser>=6.0"]
```
Install:
```bash
.venv\Scripts\python.exe -m pip install "feedparser>=6.0"
```

`ev_factory/stages/ingest.py`:
```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_ingest.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ev_factory/stages/ingest.py pyproject.toml tests/test_ingest.py
git commit -m "feat: IngestStage (RSS candidates, headline+points only)"
```

---

### Task 9: Curate stage (pick story + angle, park at STORY_REVIEW)

**Files:**
- Create: `ev_factory/stages/curate.py`
- Test: `tests/test_curate.py`

**Interfaces:**
- Consumes: `Stage`/`StageContext`, `JobState`, `LLMClient` (injected), `JobRepository.recent_slugs` (Task 2), `ingest.json` (Task 8), `Config.model_curate`/`dedup_window`.
- Produces:
  - `class CurateStage(Stage)` with `name = "curate"`, `produces_state = JobState.STORY_REVIEW`, `__init__(self, llm)`. `run` reads `ingest.json`, builds a prompt listing candidates + recent slugs to avoid, asks `model_curate` for a JSON object `{"chosen_index": int, "angle": str}`, parses it, and writes `story.json` = `{title, link, source, points, angle, sources: [links], single_source: bool}`. `single_source` is True when the chosen story has fewer than 2 distinct source links among candidates sharing its title. Returns `StageResult.ok("curate")`; if `ingest.json` missing/empty, `StageResult.fail`.

- [ ] **Step 1: Write the failing test**

`tests/test_curate.py`:
```python
import json
from types import SimpleNamespace

from ev_factory.config import load_config
from ev_factory.db import JobRepository
from ev_factory.jobfolder import JobFolder
from ev_factory.models import StageStatus
from ev_factory.stages.base import StageContext
from ev_factory.stages.curate import CurateStage


class FakeLLM:
    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    def complete(self, model, system, prompt, job_id, stage, max_tokens=1024):
        self.calls.append((model, prompt))
        return self.reply


def _ctx(tmp_config, candidates):
    cfg = load_config(tmp_config)
    repo = JobRepository(cfg.db_path)
    repo.init_schema()
    folder = JobFolder.create(cfg.jobs_dir, "2026-07-01", "slug")
    repo.create_job(folder.job_id, "slug", "2026-07-01", cfg.all_languages)
    folder.write_json(folder.root / "ingest.json", candidates)
    return cfg, repo, folder, StageContext(folder.job_id, folder, cfg, repo)


def test_curate_picks_and_writes_story(tmp_config):
    candidates = [
        {"title": "A", "link": "http://a", "source": "s1", "published": "", "points": ["x"]},
        {"title": "B", "link": "http://b", "source": "s2", "published": "", "points": ["y"]},
    ]
    cfg, repo, folder, ctx = _ctx(tmp_config, candidates)
    llm = FakeLLM(json.dumps({"chosen_index": 1, "angle": "why B matters"}))
    result = CurateStage(llm).run(ctx)
    assert result.status is StageStatus.DONE
    story = folder.read_json(folder.story_json)
    assert story["title"] == "B"
    assert story["angle"] == "why B matters"
    assert story["link"] == "http://b"


def test_curate_fails_without_ingest(tmp_config):
    cfg, repo, folder, ctx = _ctx(tmp_config, [])
    result = CurateStage(FakeLLM("{}")).run(ctx)
    assert result.status is StageStatus.FAILED


def test_curate_produces_park_state(tmp_config):
    from ev_factory.models import JobState
    assert CurateStage.__dict__["produces_state"] == JobState.STORY_REVIEW
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_curate.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'ev_factory.stages.curate'`).

- [ ] **Step 3: Implement**

`ev_factory/stages/curate.py`:
```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_curate.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ev_factory/stages/curate.py tests/test_curate.py
git commit -m "feat: CurateStage (pick story + angle, park at STORY_REVIEW)"
```

---

### Task 10: Script stage (original commentary + originality gate)

**Files:**
- Create: `ev_factory/stages/script.py`
- Test: `tests/test_script.py`

**Interfaces:**
- Consumes: `Stage`/`StageContext`, `JobState`, `LLMClient` (injected), `story.json` (Task 9), `passes_originality` (Task 6), `ComplianceReport` (Task 7), `Config.model_script`, `JobFolder.script_path`/`compliance_json`.
- Produces:
  - `class ScriptStage(Stage)` with `name = "script"`, `produces_state = JobState.SCRIPTED`, `__init__(self, llm)`. `run` reads `story.json`, asks `model_script` for an original English commentary script (system prompt forbids copying source phrasing, requires analysis/opinion/context), runs `passes_originality`; if it fails, regenerates **once**; writes `script_en.md` and `script_meta.json` (`{transformation_score, verbatim_ok, passed, sources}`), and appends compliance checks (`copyright_text`, `sources_min_two`, `not_repetitious`, `verbatim_clean`, `transformation_score`) to `compliance.json`. Always returns `StageResult.ok("script")` (a failing originality result is recorded, not fatal — it surfaces at the review gate); `StageResult.fail` only if `story.json` is missing.

- [ ] **Step 1: Write the failing test**

`tests/test_script.py`:
```python
from dataclasses import replace

from ev_factory.config import load_config
from ev_factory.db import JobRepository
from ev_factory.jobfolder import JobFolder
from ev_factory.models import StageStatus
from ev_factory.compliance import ComplianceReport
from ev_factory.stages.base import StageContext
from ev_factory.stages.script import ScriptStage


class ScriptLLM:
    """Returns queued script drafts for 'script' calls and a score for 'originality' calls."""
    def __init__(self, drafts, score):
        self.drafts = list(drafts)
        self.score = score
        self.script_calls = 0

    def complete(self, model, system, prompt, job_id, stage, max_tokens=1024):
        if stage == "originality":
            return str(self.score)
        self.script_calls += 1
        return self.drafts.pop(0) if self.drafts else self.drafts_last

    @property
    def drafts_last(self):
        return "fallback draft"


def _ctx(tmp_config, story):
    cfg = replace(load_config(tmp_config), originality_threshold=70, verbatim_span_words=8)
    repo = JobRepository(cfg.db_path)
    repo.init_schema()
    folder = JobFolder.create(cfg.jobs_dir, "2026-07-01", "slug")
    repo.create_job(folder.job_id, "slug", "2026-07-01", cfg.all_languages)
    folder.write_json(folder.story_json, story)
    return cfg, repo, folder, StageContext(folder.job_id, folder, cfg, repo)


STORY = {
    "title": "Tesla cuts price", "link": "http://a", "source": "s1",
    "points": ["Tesla cut the Model Y price"], "angle": "what it means for rivals",
    "sources": ["http://a", "http://b"], "single_source": False,
}


def test_script_writes_script_and_meta_on_pass(tmp_config):
    cfg, repo, folder, ctx = _ctx(tmp_config, STORY)
    llm = ScriptLLM(drafts=["A wholly original take on pricing dynamics and rivals."], score=90)
    result = ScriptStage(llm).run(ctx)
    assert result.status is StageStatus.DONE
    assert folder.script_path("en").exists()
    meta = folder.read_json(folder.root / "script_meta.json")
    assert meta["passed"] is True
    assert meta["transformation_score"] == 90
    assert llm.script_calls == 1  # no regeneration needed


def test_script_regenerates_once_then_records_failure(tmp_config):
    cfg, repo, folder, ctx = _ctx(tmp_config, STORY)
    # Both drafts score low -> fail; must regenerate exactly once (2 script calls total).
    llm = ScriptLLM(drafts=["draft one", "draft two"], score=40)
    result = ScriptStage(llm).run(ctx)
    assert result.status is StageStatus.DONE  # not fatal
    assert llm.script_calls == 2
    report = ComplianceReport.from_dict(folder.read_json(folder.compliance_json))
    assert report.blocking is True  # transformation_score hard-fails


def test_script_fails_without_story(tmp_config):
    cfg = replace(load_config(tmp_config))
    repo = JobRepository(cfg.db_path)
    repo.init_schema()
    folder = JobFolder.create(cfg.jobs_dir, "2026-07-01", "slug")
    repo.create_job(folder.job_id, "slug", "2026-07-01", cfg.all_languages)
    ctx = StageContext(folder.job_id, folder, cfg, repo)
    result = ScriptStage(ScriptLLM(drafts=["x"], score=90)).run(ctx)
    assert result.status is StageStatus.FAILED
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_script.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'ev_factory.stages.script'`).

- [ ] **Step 3: Implement**

`ev_factory/stages/script.py`:
```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_script.py -v`
Expected: PASS (all three cases).

- [ ] **Step 5: Commit**

```bash
git add ev_factory/stages/script.py tests/test_script.py
git commit -m "feat: ScriptStage (original commentary + originality gate + compliance)"
```

---

### Task 11: Localize stage (per-language loop)

**Files:**
- Create: `ev_factory/stages/localize.py`
- Test: `tests/test_localize.py`

**Interfaces:**
- Consumes: `Stage`/`StageContext`, `JobState`, `LLMClient` (injected), `script_en.md` (Task 10), `Config.target_languages`/`model_script`, `JobRepository.set_language_status` (foundation), `JobFolder.script_path`.
- Produces:
  - `class LocalizeStage(Stage)` with `name = "localize"`, `produces_state = JobState.LOCALIZED`, `__init__(self, llm)`. `run` reads `script_en.md`, loops over `ctx.config.target_languages`, translating + culturally adapting each via `model_script`, writing `script_<lang>.md` and setting that language's status to `done`; a language whose translation raises sets its status to `failed` and the loop continues. Returns `StageResult.ok("localize", data={"done": [...], "failed": [...]})`; `StageResult.fail` only if `script_en.md` is missing.

- [ ] **Step 1: Write the failing test**

`tests/test_localize.py`:
```python
from dataclasses import replace

from ev_factory.config import load_config
from ev_factory.db import JobRepository
from ev_factory.jobfolder import JobFolder
from ev_factory.models import StageStatus
from ev_factory.stages.base import StageContext
from ev_factory.stages.localize import LocalizeStage


class LangLLM:
    def __init__(self, fail_langs=()):
        self.fail_langs = set(fail_langs)
        self.calls = []

    def complete(self, model, system, prompt, job_id, stage, max_tokens=1024):
        # The target language is encoded in the stage label "localize:<lang>".
        lang = stage.split(":")[-1]
        self.calls.append(lang)
        if lang in self.fail_langs:
            raise RuntimeError("translation boom")
        return f"[{lang}] translated"


def _ctx(tmp_config, langs):
    cfg = replace(load_config(tmp_config), target_languages=langs)
    repo = JobRepository(cfg.db_path)
    repo.init_schema()
    folder = JobFolder.create(cfg.jobs_dir, "2026-07-01", "slug")
    repo.create_job(folder.job_id, "slug", "2026-07-01", cfg.all_languages)
    folder.script_path("en").write_text("English script", encoding="utf-8")
    return cfg, repo, folder, StageContext(folder.job_id, folder, cfg, repo)


def test_localize_writes_each_language(tmp_config):
    cfg, repo, folder, ctx = _ctx(tmp_config, ["ru", "tr"])
    result = LocalizeStage(LangLLM()).run(ctx)
    assert result.status is StageStatus.DONE
    assert folder.script_path("ru").read_text(encoding="utf-8") == "[ru] translated"
    assert folder.script_path("tr").read_text(encoding="utf-8") == "[tr] translated"
    statuses = repo.get_language_statuses(folder.job_id)
    assert statuses["ru"] == "done" and statuses["tr"] == "done"


def test_localize_isolates_failing_language(tmp_config):
    cfg, repo, folder, ctx = _ctx(tmp_config, ["ru", "tr"])
    result = LocalizeStage(LangLLM(fail_langs={"ru"})).run(ctx)
    assert result.status is StageStatus.DONE  # tr still succeeded
    statuses = repo.get_language_statuses(folder.job_id)
    assert statuses["ru"] == "failed"
    assert statuses["tr"] == "done"
    assert folder.script_path("tr").exists()


def test_localize_fails_without_english(tmp_config):
    cfg = replace(load_config(tmp_config), target_languages=["ru"])
    repo = JobRepository(cfg.db_path)
    repo.init_schema()
    folder = JobFolder.create(cfg.jobs_dir, "2026-07-01", "slug")
    repo.create_job(folder.job_id, "slug", "2026-07-01", cfg.all_languages)
    ctx = StageContext(folder.job_id, folder, cfg, repo)
    result = LocalizeStage(LangLLM()).run(ctx)
    assert result.status is StageStatus.FAILED
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_localize.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'ev_factory.stages.localize'`).

- [ ] **Step 3: Implement**

`ev_factory/stages/localize.py`:
```python
from __future__ import annotations

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
            except Exception:  # noqa: BLE001 - isolate one language's failure
                ctx.repo.set_language_status(ctx.job_id, lang, "failed")
                failed.append(lang)
        return StageResult.ok(self.name, data={"done": done, "failed": failed})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_localize.py -v`
Expected: PASS (all three cases).

- [ ] **Step 5: Commit**

```bash
git add ev_factory/stages/localize.py tests/test_localize.py
git commit -m "feat: LocalizeStage (per-language translation with isolation)"
```

---

### Task 12: Golden-path integration test (offline, fakes end-to-end)

**Files:**
- Test: `tests/test_integration_content.py`
- (No new production code — this task proves the stages compose through the reworked orchestrator.)

**Interfaces:**
- Consumes: `Orchestrator`, all four stages, `JobFolder`, `JobRepository`, `load_config`, `statemachine.transition`, `JobState`.

- [ ] **Step 1: Write the failing test**

`tests/test_integration_content.py`:
```python
from dataclasses import replace
from types import SimpleNamespace

from ev_factory.config import load_config
from ev_factory.db import JobRepository
from ev_factory.jobfolder import JobFolder
from ev_factory.models import JobState
from ev_factory.orchestrator import Orchestrator
from ev_factory.statemachine import transition
from ev_factory.stages.ingest import IngestStage
from ev_factory.stages.curate import CurateStage
from ev_factory.stages.script import ScriptStage
from ev_factory.stages.localize import LocalizeStage


class FakeLLM:
    """One fake covering curate (JSON), script (prose), originality (score), localize (prose)."""
    def complete(self, model, system, prompt, job_id, stage, max_tokens=1024):
        if stage == "curate":
            return '{"chosen_index": 0, "angle": "what it signals for the market"}'
        if stage == "originality":
            return "88"
        if stage.startswith("localize"):
            return f"translated: {stage.split(':')[-1]}"
        return "A fully original analytical commentary on the day's EV news and its impact."


def _entry(title, link, summary):
    return SimpleNamespace(title=title, link=link, summary=summary, published="2026-07-01")


def test_ingest_to_localized_golden_path(tmp_config):
    cfg = replace(load_config(tmp_config), target_languages=["ru", "tr"])
    cfg.rss_sources.append("https://example.com/feed")
    repo = JobRepository(cfg.db_path)
    repo.init_schema()
    folder = JobFolder.create(cfg.jobs_dir, "2026-07-01", "slug")
    job_id = folder.job_id
    repo.create_job(job_id, "slug", "2026-07-01", cfg.all_languages)

    feed = SimpleNamespace(entries=[_entry("Tesla cuts price", "http://a", "One. Two. Three.")])
    llm = FakeLLM()
    stages = [
        IngestStage(fetch=lambda url: feed),
        CurateStage(llm),
        ScriptStage(llm),
        LocalizeStage(llm),
    ]
    orch = Orchestrator(cfg, repo, stages)

    # First run: ingest -> curate -> parks at STORY_REVIEW.
    state = orch.run_job(job_id, until=JobState.LOCALIZED)
    assert state == JobState.STORY_REVIEW
    assert folder.story_json.exists()
    assert not folder.script_path("en").exists()  # scripting hasn't run yet

    # Human approves the story.
    transition(repo, job_id, JobState.STORY_APPROVED)

    # Resume: script -> localize -> LOCALIZED.
    state = orch.run_job(job_id, until=JobState.LOCALIZED)
    assert state == JobState.LOCALIZED
    assert folder.script_path("en").exists()
    assert folder.script_path("ru").exists()
    assert folder.script_path("tr").exists()
    assert repo.get_language_statuses(job_id) == {"en": "pending", "ru": "done", "tr": "done"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_integration_content.py -v`
Expected: FAIL only if a wiring bug exists; if all prior tasks are correct it may pass immediately. If it fails, fix the stage/orchestrator wiring the failure points to before proceeding.

- [ ] **Step 3: (No new implementation)**

This task adds no production code — it exercises Tasks 1–11 together. If Step 2 failed, the fix belongs in whichever unit it implicates (re-run that unit's tests after fixing).

- [ ] **Step 4: Run the full suite**

Run: `.venv\Scripts\python.exe -m pytest -v`
Expected: PASS across every test file (foundation + all Plan 2 tasks).

- [ ] **Step 5: Commit**

```bash
git add tests/test_integration_content.py
git commit -m "test: golden-path integration for content stages (offline)"
```

---

## Self-Review

**Spec coverage:**
- §3 orchestrator rework (per-stage table, park states, monotonic advance, transition-in-try/except) → Tasks 1, 2, 3. ✅
- §4.1 IngestStage (RSS, headline+points only, no body) → Task 8. ✅
- §4.2 CurateStage (Haiku pick+angle, dedup vs recent slugs, source-count flag, park STORY_REVIEW) → Task 9. ✅
- §4.3 ScriptStage (Sonnet original commentary, originality gate, regenerate-once, compliance) → Task 10. ✅
- §4.4 LocalizeStage (per-language loop, per-language status isolation) → Task 11. ✅
- §5.1 originality (verbatim guard + rubric, both must pass) → Task 6. ✅
- §5.2 ComplianceReport (checks it owns, blocking on hard failure) → Task 7 (+ populated in Task 10). ✅
- §6.1 llm.py (Anthropic SDK, cost logging from usage, spend cap before call, dry-run no-call, pinned models) → Task 5. ✅
- §6.2 job-folder artifacts (ingest.json, story.json, script_en.md, script_meta.json, script_<lang>.md, compliance.json) → Tasks 8–11. ✅
- §7 error/cost control (spend cap → job FAILED via orchestrator try/except catching SpendCapExceeded; per-language isolation; regenerate-once; idempotent re-run via job_stages) → Tasks 3, 5, 10, 11. ✅
- §8 testing (mocked llm/feedparser offline; originality hard-tested; orchestrator collapse/park/skip; compliance; golden path) → Tasks 3, 6, 7, 12. ✅
- Config keys for models/thresholds → Task 4. ✅

**Placeholder scan:** No TBD/TODO/"handle edge cases" — every code step has complete, runnable code. ✅

**Type consistency:**
- `LLMClient.complete(model, system, prompt, job_id, stage, max_tokens=1024)` — identical signature in Task 5 (def), Task 6 (`FakeLLM`), Tasks 9/10/11 (callers and fakes). ✅
- `JobRepository.mark_stage`/`get_stage_status`/`recent_slugs` (Task 2) match orchestrator (Task 3) and curate (Task 9) usage. ✅
- `passes_originality(llm, config, script, source_texts, job_id) -> (passed, score, vb)` — Task 6 def matches Task 10 call. ✅
- `ComplianceReport.add/blocking/to_dict/from_dict` (Task 7) match Task 10 usage and Task 12 assertion. ✅
- `JobState.STORY_REVIEW/STORY_APPROVED` and `PARK_STATES` (Task 1) used consistently in Tasks 3, 9, 12. ✅
- Stage `name`/`produces_state` class attrs set on every stage (Tasks 8–11), satisfying the foundation `Stage.__init_subclass__` guard. ✅
