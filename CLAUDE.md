# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A locally-run, semi-automated pipeline that turns daily electric-vehicle news into original, localized
short/long-form video content for YouTube, Instagram, and TikTok. The overriding non-functional
requirement is **strict YouTube-policy compliance** (avoid reused-content / mass-produced strikes), so
originality and copyright guardrails are first-class, not afterthoughts. Nothing publishes without human
review. Design docs and per-plan specs live in `docs/superpowers/specs/`; implementation plans in
`docs/superpowers/plans/`. Read the relevant spec before changing a subsystem — the specs carry the
"why" (compliance rules, budget constraints) that the code alone doesn't.

Built in sequential plans, each its own spec → plan → build cycle:
- **Foundation** (merged): the pipeline chassis.
- **Plan 2 — content stages** (merged): orchestrator rework + Ingest → Curate → Script → Localize.
- **Plans 3–5** (not built): media production (voice/avatar/assemble), review web UI, publishing+scheduler.

## Commands (Windows / PowerShell)

There is a project virtualenv at `.venv` with `pytest` and the runtime deps installed. Always invoke it
explicitly — a bare `pytest`/`python` is usually the wrong interpreter here:

```powershell
.venv\Scripts\python.exe -m pytest -q                          # full suite
.venv\Scripts\python.exe -m pytest tests/test_orchestrator.py -v   # one file
.venv\Scripts\python.exe -m pytest tests/test_orchestrator.py::test_parks_at_story_review_and_halts_until_approved -v  # one test
.venv\Scripts\python.exe -m pip install "<pkg>"                # add a dep (also add it to pyproject.toml)
```

CLI entrypoint (argparse in `ev_factory/cli.py`, currently `create` + `status` only):

```powershell
.venv\Scripts\python.exe -m ev_factory.cli create --title "..." --date 2026-07-01 --config config.toml
.venv\Scripts\python.exe -m ev_factory.cli status --config config.toml
```

Config: copy `config.example.toml` to `config.toml` (git-ignored). `config.toml`, `jobs/`, and `*.db`
are all git-ignored. There is no build step, linter, or formatter configured — TDD (pytest) is the loop.

## Architecture — the big picture

A **staged pipeline**. Each stage is an independent, injectable unit; the orchestrator runs a list of
them and a job flows through coarse **milestone states** while the human gates progress at two **park**
points. The parts only make sense together:

- **`models.py`** — `JobState` (the milestone enum), `StageStatus`, `StageResult` (what a stage returns),
  `ComplianceCheck`, `make_slug`.
- **`statemachine.py`** — `HAPPY_PATH` (ordered milestones), the auto-derived `ALLOWED_TRANSITIONS`
  (each state may advance to the next, or to `FAILED`), `PARK_STATES = {STORY_REVIEW, IN_REVIEW}`, and
  `transition()` which enforces adjacency. Happy path:
  `NEW → INGESTED → STORY_REVIEW → STORY_APPROVED → SCRIPTED → LOCALIZED → RENDERED → IN_REVIEW → APPROVED → PUBLISHED`.
- **`db.py`** — `JobRepository` over SQLite. Two things that look redundant but aren't: `jobs.state` is
  the **coarse milestone**; the `job_stages` table (`mark_stage`/`get_stage_status`) is the **per-stage
  completion record**. The orchestrator skips stages by `job_stages`, never by milestone — this is what
  lets multiple stages share one milestone. Also holds per-language status, cost log
  (`record_cost`/`spend_this_month`), and posts (idempotency).
- **`jobfolder.py`** — `JobFolder`: one human-inspectable directory per story (`jobs/YYYY-MM-DD-slug/`)
  holding `ingest.json`, `story.json`, `script_<lang>.md`, `script_meta.json`, `compliance.json`, and
  `audio/`+`video/`. Stages pass structured data through these files. JSON is written UTF-8
  `ensure_ascii=False` (Cyrillic/Turkish content).
- **`stages/base.py`** — the `Stage` ABC. A concrete stage sets class attrs `name` and `produces_state`
  (enforced by `__init_subclass__`) and implements `run(ctx: StageContext) -> StageResult`.
  `StageContext` carries `job_id`, `folder`, `config`, `repo`, and `dry_run`.
- **`orchestrator.py`** — `Orchestrator.run_job(job_id, until=...)`. The load-bearing logic: skip a stage
  iff its `job_stages` row is `done`; advance the milestone via `transition()` **only if the stage's
  `produces_state` is further along** (so stages sharing a milestone don't collide); **halt** when the
  current state is a park state or a stage produces one; convert any exception (incl. `SpendCapExceeded`,
  `InvalidTransition`) to a clean job `FAILED`.
- **`llm.py`** — `LLMClient`: thin Anthropic SDK wrapper. Enforces the monthly spend cap **before** each
  paid call, logs cost from `usage` (`PRICING` per model), and **refuses to call the API in dry-run**
  (tests inject a fake `client`). Models pinned in config: `claude-haiku-4-5` (curate/rubric),
  `claude-sonnet-4-6` (script/localize).
- **`originality.py`** — the YouTube-compliance heart. `passes_originality` = **verbatim guard clean AND
  rubric score ≥ threshold** (both required). Never weaken this to one check.
- **`compliance.py`** — `ComplianceReport` accumulator; `blocking` is true if any *hard* check failed.
  The review gate must refuse to publish when blocking. (Currently `ScriptStage` writes it fresh; media
  stages will need read-merge-write.)
- **`stages/{ingest,curate,script,localize}.py`** — Ingest (RSS via `feedparser`, stores **headline +
  link + points only, never article body**), Curate (Haiku picks story + original angle, dedupes vs
  recent slugs, **parks at STORY_REVIEW**), Script (Sonnet original commentary, runs originality gate,
  regenerates once on failure, writes compliance), Localize (per-language loop, isolates a failing
  language via `set_language_status`).

### How stages get their dependencies

Stages that call the LLM take it via **constructor injection** (`CurateStage(llm)`), and `IngestStage`
takes a `fetch` function — so tests pass fakes and the whole pipeline is exercised offline with zero
spend and zero network. `StageContext` is deliberately not the injection point for the LLM. When adding
a stage, follow this pattern and keep `run()` pure of hidden I/O.

### Control flow / park semantics

The orchestrator halts at a park state and returns; it does **not** resume on its own. A human (Plan 4's
UI, or a direct `transition()` in tests) moves the job out of the park — e.g. `STORY_REVIEW →
STORY_APPROVED` — and the next `run_job` continues. `until=` bounds how far a run goes.

## Conventions that matter

- **Runtime deps are deliberately minimal**: stdlib + `anthropic` + `feedparser` only. Don't add
  dependencies without a strong reason; the foundation modules are stdlib-only.
- **Model IDs are exact strings** (`claude-haiku-4-5`, `claude-sonnet-4-6`) — never append date suffixes.
  For anything touching the Anthropic SDK / models / pricing, consult the `claude-api` skill rather than
  memory.
- **Everything is offline-testable.** New external calls must be injectable and dry-run-safe.
- **Timestamps** are UTC ISO-8601; **language codes** are lowercase ISO-639-1 (source is `en`).
- Git: the remote is `github.com/SleepySML/ElectricCarNewsFactory` and must be pushed via the
  `github.com-sleepysml` SSH alias (a second GitHub account on this machine owns plain `github.com`).
