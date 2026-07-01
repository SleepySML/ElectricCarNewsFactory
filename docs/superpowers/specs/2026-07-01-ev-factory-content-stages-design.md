# EV News Content Factory — Content Stages (Plan 2) Design Spec

**Date:** 2026-07-01
**Status:** Approved (design), pending implementation plan
**Owner:** evgenij.sleepy@gmail.com
**Builds on:** the merged foundation (`ev_factory/`, commit 7666e50) and the master design
`docs/superpowers/specs/2026-07-01-ev-news-content-factory-design.md`.

## 1. Purpose

Implement the content-generation half of the pipeline: turn a day's EV news into a single chosen
story and an original, transformative commentary script, localized into the target languages —
with the compliance guardrails that keep the channel safe on YouTube. This plan also performs the
prerequisite **orchestrator rework** the final foundation review flagged, so the pipeline can drive
multiple stages per milestone and support human checkpoints.

The output of Plan 2 is: given RSS fixtures (or live feeds), the pipeline produces a compliance-checked
English script plus localized scripts, pausing at two human checkpoints. Media (voice/avatar/assemble),
the review web UI, and publishing remain later plans.

## 2. Confirmed Requirements

| Decision | Choice |
|---|---|
| Orchestrator completion model | Per-stage completion table + park states (Approach A) |
| Early human checkpoint | Yes — approve the chosen story + angle **before** scripting (a `STORY_REVIEW` park), in addition to the existing pre-publish review |
| LLM provider | Anthropic Claude API (key available via `ANTHROPIC_API_KEY`) |
| Model tiers | `claude-haiku-4-5` for curation + originality rubric; `claude-sonnet-4-6` for script + localization |
| News sources | A recommended starter allowlist of EV RSS feeds, editable in `config.toml` |
| Originality enforcement | LLM rubric **and** deterministic verbatim guard — both must pass |
| Budget | Unchanged — under $100/month; one story/day on Haiku/Sonnet is a few cents/day |
| Runs | Locally on Windows / RTX 3060 |

## 3. Orchestrator & State-Model Rework (Approach A)

### 3.1 State milestones

`JobState` happy path becomes:

```
NEW → INGESTED → CURATED → STORY_REVIEW → SCRIPTED → LOCALIZED
    → RENDERED → IN_REVIEW → APPROVED → PUBLISHED        (FAILED reachable from any active state)
```

`RENDERED → IN_REVIEW → APPROVED → PUBLISHED` remain from the foundation and are exercised by later
plans; Plan 2's far end is `LOCALIZED`. New members added this plan: `CURATED`, `STORY_REVIEW`.

**Park states:** `PARK_STATES = {STORY_REVIEW, IN_REVIEW}`. When a stage produces a park state, the
orchestrator advances the milestone, marks the stage done, and **returns** — the pipeline waits for a
human action to transition the job out of the park. (Plan 2 introduces `STORY_REVIEW`; the human
approval mechanism/UI is Plan 4, but the state and park semantics are built and tested here via direct
state transitions.)

### 3.2 Per-stage completion table

New table (added additively via the existing `CREATE TABLE IF NOT EXISTS` in `init_schema`):

```sql
job_stages(
    job_id     TEXT NOT NULL,
    stage_name TEXT NOT NULL,
    status     TEXT NOT NULL,   -- pending | running | done | failed | skipped
    updated_at TEXT NOT NULL,
    PRIMARY KEY (job_id, stage_name)
)
```

New `JobRepository` methods: `mark_stage(job_id, stage_name, status)` and
`get_stage_status(job_id, stage_name) -> str | None`.

### 3.3 Orchestrator changes (`orchestrator.py`)

- **Skip rule:** skip a stage iff `get_stage_status(job_id, stage.name) == "done"`. Never skip by
  milestone index. This removes the collapse bug (multiple stages sharing a `produces_state`).
- **On `DONE`:** `mark_stage(job_id, stage.name, "done")`, then advance `job.state` to
  `stage.produces_state` only if it is further along the happy path (monotonic milestone).
- **Park:** if `stage.produces_state in PARK_STATES`, after advancing, `return` (stop the run).
- **Transition safety:** the `transition()` call is wrapped in the stage try/except, so an illegal or
  gapped transition becomes a clean `set_error`/`FAILED`, not an uncaught escape (review finding M1).
- `Stage`/`StageContext` are unchanged — existing stages and tests keep working.

## 4. Content Stages

All stages live in `ev_factory/stages/`, subclass `Stage`, read/write the `JobFolder` and DB, and honor
`ctx.dry_run` (in dry-run they make **no** paid API calls and return fixture-shaped stubs).

### 4.1 `IngestStage` (`ingest.py`) → `INGESTED`
Fetches the config RSS allowlist with `feedparser`. Stores **only** headline, link, source name,
published date, and a few short factual bullet points per item — **never** the full article body
(copyright rule). Writes `ingest.json` (candidate list). New dependency: `feedparser`.

**Starter allowlist** (editable in `config.toml`, `rss_sources`): InsideEVs, Electrek, CleanTechnica,
Green Car Reports, and manufacturer press rooms (Tesla, Rivian, Hyundai, BYD). All RSS.

### 4.2 `CurateStage` (`curate.py`) → `CURATED`, parks at `STORY_REVIEW`
A Claude Haiku call ranks candidates, dedupes against the last N story slugs (repetition rule), and
picks the single best story with a suggested original **angle**. Runs a source-count check
(≥2 reputable sources; single-source stories are flagged). Writes `story.json` (chosen story, angle,
candidate list, source URLs). `produces_state = STORY_REVIEW` (a park), so the orchestrator stops here
for the early human approval.

### 4.3 `ScriptStage` (`script.py`) → `SCRIPTED`
A Claude Sonnet call writes the original English commentary from story + angle + facts — instructed to
add analysis, opinion, comparison, and context, cite sources inline, and never reproduce source
phrasing. The originality machinery (§5) then scores it; a failing script is regenerated **once**, then
flagged (never silently published). Writes `script_en.md` and `script_meta.json` (transformation score,
citations).

### 4.4 `LocalizeStage` (`localize.py`) → `LOCALIZED`
A single stage that loops over `config.target_languages`, translating + culturally adapting the EN
script via Claude Sonnet. Writes `script_<lang>.md` per language and records **per-language** status via
`repo.set_language_status`, so one language failing does not block the others. Being one looping stage
(not per-language stage instances) keeps it clean under the completion model.

## 5. Originality & Compliance Machinery

### 5.1 `originality.py` — two independent checks, both must pass
1. **Verbatim guard** (deterministic, no cost): rejects the script if any span of ≥ N consecutive words
   (default 8, configurable) from the stored source facts/headlines appears verbatim. Pure Python,
   fixture-testable.
2. **LLM rubric** (Claude Haiku): scores 0–100 against a fixed rubric — adds analysis/opinion? adds
   context/comparison? original framing? cites ≥2 sources? Returns score + per-criterion rationale.

A script **passes** only if the verbatim guard is clean **and** rubric score ≥ threshold (default 70,
configurable). Failure triggers one regeneration in `ScriptStage`; if it still fails, the failure is
recorded in the compliance report and surfaces at the review gate.

### 5.2 `compliance.py` — `ComplianceReport` accumulator
Built on the existing `ComplianceCheck` model; travels in `compliance.json`. Plan 2 populates the checks
it owns: `copyright_text` (ingest stored no article body), `sources_min_two`, `not_repetitious`
(dedupe), `transformation_score`, `verbatim_clean`. Later plans append footage/music/AI-disclosure
checks. Any hard check failing marks the report as blocking (the review gate will refuse publish).

## 6. LLM Client & Data Flow

### 6.1 `llm.py`
Thin wrapper over the **official Anthropic Python SDK** (`anthropic` package — new dependency). Reads
`ANTHROPIC_API_KEY` from env; exposes `complete(model, system, prompt, max_tokens) -> str` and a
JSON-returning variant; relies on the SDK's built-in retry/backoff for transient errors; logs per-call
cost via `repo.record_cost(...)` (computed from the response `usage` input/output tokens × the model's
per-token price, pinned in config) so spend rolls into `spend_this_month()`. Enforces the spend cap
**before** each paid call (over cap → raises → orchestrator marks the job `FAILED`). In `dry_run` it
never constructs a live client or calls the API — it returns injected fixture responses, so the whole
pipeline runs offline for free. Model IDs pinned in config: `claude-haiku-4-5` (curate/rubric),
`claude-sonnet-4-6` (script/localize). The `anthropic` client is the ONLY third-party runtime dependency
introduced by this plan besides `feedparser`.

### 6.2 Job-folder artifacts after Plan 2

```
jobs/2026-07-01-slug/
  ingest.json        # candidates: headline/link/source/date/facts only
  story.json         # chosen story + angle + sources + candidates
  script_en.md       # original commentary
  script_meta.json   # transformation score, citations
  script_ru.md, script_tr.md, …
  compliance.json    # accumulating checks
```

## 7. Error Handling & Cost Control

- **Spend cap** enforced in `llm.py` before every paid call; over cap → job `FAILED` with a clear
  message rather than overspending.
- **Per-language isolation:** a language failing in Localize sets that language's status to `failed`
  and the loop continues.
- **Regenerate-once** on originality failure, then flag — no infinite loops, no silent pass.
- **Idempotent re-run:** the new `job_stages` table lets a re-run skip completed stages; a failed stage
  re-runs cleanly and overwrites its own outputs.
- **Dry-run** covers every stage via fixtures — the full flow is testable at zero cost and zero external
  calls.

## 8. Testing Strategy

- Each stage unit-tested against fixtures with `llm.py` and `feedparser` **mocked** (offline/free):
  Ingest with a canned RSS sample; Curate/Script/Localize with canned Claude responses.
- **Originality machinery** hard-tested: verbatim guard (copied span rejects, paraphrase passes),
  rubric threshold behavior, regenerate-once path.
- **Orchestrator rework** tested: two stages sharing a milestone both run (collapse regression),
  park-at-`STORY_REVIEW` stops the run, skip-completed via `job_stages`, transition failure captured as
  job failure.
- **Compliance** accumulation tested: a hard-check failure marks the report blocking.
- **Golden-path integration test** (dry-run, fixtures): `create → ingest → curate → park at
  STORY_REVIEW`, then `resume → script → localize → park at LOCALIZED`.

## 9. Out of Scope (this plan)

- Media production (voice/avatar/assemble) — Plan 3.
- The review web UI that surfaces the two checkpoints — Plan 4 (Plan 2 exercises park/approve via direct
  state transitions in tests).
- Publishing + scheduler — Plan 5.
- Live scheduling/cron of the daily run.

## 10. Open Questions for Implementation Planning

- Final starter RSS URL list (exact feed URLs) to seed `config.toml`.
- Dedup window size N (how many recent story slugs to compare against) and verbatim span length N.
- Exact rubric wording and pass threshold (default 70).
