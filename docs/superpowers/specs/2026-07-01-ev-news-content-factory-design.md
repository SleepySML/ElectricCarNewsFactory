# EV News Content Factory — Design Spec

**Date:** 2026-07-01
**Status:** Approved (design), pending implementation plan
**Owner:** evgenij.sleepy@gmail.com

## 1. Purpose

A locally-run, semi-automated content pipeline that produces one flagship electric-vehicle
news story per day, localized into multiple languages, and publishes it as long-form + short-form
video to YouTube, Instagram, and TikTok — one channel per language per platform.

The system is **semi-automated**: it drafts everything unattended, but **nothing publishes
without explicit human approval** through a local review gate. The primary non-functional
requirement is **strict compliance with YouTube policy to avoid demonetization or bans**.

## 2. Confirmed Requirements

| Decision | Choice |
|---|---|
| Automation level | Semi-automated with a human review gate before publishing |
| Video format | AI avatar presenter delivering **original commentary/analysis** (not re-read headlines) |
| Cadence | 1 flagship story/day → 1 long-form + shorts |
| Localization | EN is the source language; localized into RU, TR, and additional languages (design is language-agnostic) |
| Channel model | Separate channel per language, per platform |
| Build & host | Custom code, runs locally on the user's machine (Windows, RTX 3060 12GB) |
| Budget | Minimal — under $100/month in paid APIs |
| Voice | User's own **ElevenLabs cloned voice**, used across **all** languages (Multilingual v2) |
| Avatar (English) | Paid service (HeyGen) fed the ElevenLabs audio — polished flagship |
| Avatar (other languages) | Local lip-sync on the RTX 3060 (record one silent "presenter loop", retalk per language) |

### Cost estimate (target < $100/mo)

- LLM (curate + script + localize): ~$5–20/mo (Claude Haiku tier)
- ElevenLabs Multilingual v2 (Creator): ~$22/mo
- HeyGen (English avatar, cheap tier): ~$29/mo
- Everything else (local rendering, FFmpeg, review UI, platform APIs): $0
- **Total: ~$55–80/mo**

**Cost-saver (optional):** the "avatar renderer" is a swappable interface. English can be flipped
to the same local lip-sync used for other languages, dropping HeyGen (~$29/mo) if desired.

## 3. Architecture Overview

A **staged pipeline**. Each stage is an independent, testable module with a clear input/output
contract, reading from and writing to a shared per-story **job folder** plus a small **SQLite**
database. Stories flow left-to-right; the **human review gate** sits immediately before publishing.

```
 [1] INGEST          [2] CURATE          [3] SCRIPT           [4] LOCALIZE
 news sources  ──►   dedupe + rank  ──►  original EN     ──►  translate + culturally
 (RSS/APIs)          pick 1 story        commentary          adapt script → RU/TR/…
                     + compliance        script (LLM)
                     pre-check                                        │
                                                                      ▼
 [8] PUBLISH        [7] REVIEW GATE      [6] ASSEMBLE          [5] VOICE + AVATAR
 platform APIs ◄──  local web UI     ◄── FFmpeg: video     ◄── ElevenLabs TTS (user's
 per lang/channel   approve/reject       + captions +           voice, all langs)
 (scheduled)        per language         graphics + music       EN → HeyGen avatar
                                                                 others → local lip-sync
```

**Principles**

- Each stage is a separate module; any stage can be run, tested, retried, or swapped in isolation.
- Nothing publishes without passing Stage 7 (human review) — the ban-safety backbone.
- The **compliance layer is cross-cutting**, not a stage: enforced at Curate (source vetting),
  Script (originality/transformation), Assemble (copyright), and Review (final human sign-off).

## 4. Components & Tech Choices

| Stage | Tool | Notes / cost |
|---|---|---|
| Ingest | Python + `feedparser` over a curated allowlist of EV RSS/news APIs | Free. Stores only headline + link + short factual points (never full article body) |
| Curate | LLM (Claude Haiku) ranks, dedupes, flags copyright/misinfo risk | Pennies/day |
| Script | LLM writes **original analysis** script (context, opinion, comparison) | ~$0.05–0.20/story |
| Localize | LLM translates + culturally adapts per language | Cheap tokens |
| Voice | ElevenLabs Multilingual v2, user's cloned voice, all languages | Creator ~$22/mo |
| Avatar (EN) | HeyGen fed the ElevenLabs audio (paid tier) | ~$29/mo |
| Avatar (others) | Local lip-sync on RTX 3060 from a pre-recorded silent presenter loop | Free |
| Assemble | FFmpeg: burn captions, lower-thirds, B-roll, music | Free |
| Review UI | Local web app (FastAPI backend + lightweight frontend) | Free |
| Publish | YouTube Data API, Instagram Graph API, TikTok Content Posting API | Free API access |
| Orchestration | Local scheduler (APScheduler / Windows Task Scheduler) + SQLite job DB | Free |

**Avatar renderer interface (local, other languages):** record one silent "presenter loop" video
of the user once; per language, run an audio-driven lip-sync model (e.g. Wav2Lip / video-retalking /
SadTalker class) on the RTX 3060 to retalk the loop to that language's ElevenLabs audio. Keeps a
consistent real-person brand across all channels at zero per-video cost.

## 5. Compliance Layer (YouTube ban-avoidance) — the backbone

A **compliance checklist object** travels with each job. The review UI surfaces it, and
**publishing is blocked unless every hard check passes and a human approves.**

| Risk | Rule enforced | Where |
|---|---|---|
| Reused / inauthentic content | Never read an article verbatim. Script must add original analysis, opinion, comparison, context. Output scored for % transformation; low scores rejected. | Script |
| Mass-produced / repetitious | Only 1 flagship story/day. Each script structurally unique (no fixed template sentences). Similarity check rejects scripts too close to recent ones. | Curate + Script |
| Copyright — footage | B-roll only from a hard allowlist: licensed/CC0 libraries (Pexels/Pixabay), user's own media, or manufacturer press-kit media with usage rights. No scraped clips. | Assemble |
| Copyright — music | Only royalty-free/licensed tracks (YouTube Audio Library / CC0). | Assemble |
| Copyright — text | Ingest stores only headline + link + short factual points, never full article body. | Ingest |
| AI disclosure | Every upload sets YouTube's "altered/synthetic content" flag + a description line disclosing AI avatar/voice. Meets YouTube + EU rules. | Publish |
| Misinformation | Facts must trace to ≥2 reputable sources; script cites sources; review gate shows the source list. | Curate + Review |
| Attribution | Auto-generated description credits every source with links. | Assemble + Publish |

Compliance is unit-tested hard (see §9): copyright allowlist, transformation scoring, and the
disclosure flag each have explicit tests.

## 6. Human Review Gate

A local web app is the control panel. For each day's story it shows, **per language**:

- Rendered video preview (long-form + each short)
- Script with **transformation score** and **source citations**
- **Compliance checklist** (green/red per item; publish disabled if any red)
- Generated title, description, tags, thumbnail, hashtags
- Actions: **Approve** / **Reject (with note)** / **Edit metadata** / **Regenerate stage**

Approve → job enters the publish queue at the chosen schedule. Reject → job halts, note logged,
optional stage re-run. Nothing reaches a platform without an explicit approve.

## 7. Data Flow, Storage & Orchestration

- **Job folder per story per day:** `jobs/YYYY-MM-DD-slug/` containing `story.json`,
  `script_en.md`, `script_ru.md`, …, `audio/`, `video/`, `compliance.json`, `metadata_*.json`.
  Human-inspectable; easy to debug and re-run.
- **SQLite DB:** job state machine, per-language status, per-platform post IDs, cost logging.
- **State machine:** `ingested → scripted → localized → rendered → in_review → approved →
  published | failed`. Any stage can be retried independently without redoing prior work.
- **Scheduler:** a morning run executes stages 1–6 unattended and parks jobs at `in_review`;
  the user reviews during the day; approved jobs auto-publish at platform-optimal times.

## 8. Error Handling & Cost Control

- Every external call (LLM, ElevenLabs, HeyGen, platform APIs) is wrapped with **retries + a hard
  monthly spend cap**; hitting the cap pauses paid stages and alerts rather than overspending.
- Any stage failure marks the job `failed` with the error captured in the job folder; other
  languages continue independently (one language failing doesn't block the rest).
- **Idempotent stages:** re-running a stage overwrites its own outputs cleanly; publish checks the
  DB for an existing post ID first, so it never double-posts.
- **Dry-run mode** for everything: test the whole flow with zero spend and zero posts.

## 9. Testing Strategy

- Each stage has unit tests against fixture inputs (sample RSS, sample script) with **mocked
  external APIs** — the whole pipeline is testable offline for free.
- A **golden-path integration test** runs ingest→assemble in dry-run on fixtures.
- **Compliance checks are unit-tested hard**: copyright allowlist, transformation scoring, and
  disclosure flag each have explicit tests.
- Publishing tested against platform sandbox/test modes before going live.

## 10. Out of Scope (initial version)

- Fully-autonomous posting without human review (explicitly rejected — review gate is required).
- Analytics/performance-optimization loop (comment sentiment, A/B thumbnails) — a later phase.
- Paid ad promotion, community management, monetization dashboards.
- More than one flagship story/day (higher volume is a known YouTube ban risk).

## 11. Open Questions for Implementation Planning

- Exact initial language set beyond EN/RU/TR to seed the language config.
- Which specific local lip-sync model to standardize on for the RTX 3060 (quality vs. speed).
- Platform API access status (YouTube Data API quota, Instagram Graph API business account,
  TikTok Content Posting API approval) — these have onboarding lead times.
- Preferred LLM provider/model per stage within budget.
