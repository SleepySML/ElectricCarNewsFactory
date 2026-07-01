# EV News Content Factory — Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the pipeline foundation — the job data model, SQLite database, per-story job folders, state machine, generic stage orchestrator, and CLI — so a story can be created and driven through its lifecycle states, fully offline and testable, with dry-run guaranteeing zero spend and zero posting.

**Architecture:** A staged pipeline where each content/media stage (built in later plans) is an injected `Stage` object. This plan builds the *chassis*: a `JobRepository` over SQLite tracks each job's state and per-language status; a `JobFolder` holds human-inspectable artifacts on disk; a `StateMachine` enforces legal transitions; and an `Orchestrator` runs an injected list of stages in order, parking a job at `IN_REVIEW` and marking `FAILED` on error. Real stages are added by later plans against the `Stage` interface defined here.

**Tech Stack:** Python 3.11+, standard-library only for core (`sqlite3`, `tomllib`, `pathlib`, `dataclasses`, `argparse`, `datetime`, `enum`), `pytest` for tests. No third-party runtime dependencies in this plan.

## Global Constraints

- Python **3.11+** required (uses stdlib `tomllib`).
- Core foundation uses **standard library only** — no third-party runtime deps in this plan.
- **Dry-run mode must guarantee zero external spend and zero posting** — foundation stages are injected, so the orchestrator itself performs no external calls; dry-run is threaded through `Config` and `StageContext` for later plans to honor.
- **Stages must be idempotent** — re-running a stage overwrites its own outputs cleanly and never double-acts.
- **Language codes are lowercase ISO-639-1 strings** (`"en"`, `"ru"`, `"tr"`). Source language is `en`.
- **Timestamps are UTC ISO-8601 strings** via `datetime.now(timezone.utc).isoformat()`.
- **Job id format:** `YYYY-MM-DD-slug` (also the job-folder name).
- All money amounts are USD floats; monthly spend cap is enforced before any paid stage (later plans) via `JobRepository.spend_this_month()`.

---

### Task 1: Project scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `ev_factory/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `config.example.toml`
- Create: `.gitignore`
- Test: `tests/test_smoke.py`

**Interfaces:**
- Consumes: nothing (first task).
- Produces: the `ev_factory` importable package; `pytest` runnable; `tmp_config` fixture available to later tests.

- [ ] **Step 1: Write the failing test**

`tests/test_smoke.py`:
```python
def test_package_imports():
    import ev_factory
    assert ev_factory.__version__ == "0.1.0"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_smoke.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ev_factory'`

- [ ] **Step 3: Create the package and support files**

`pyproject.toml`:
```toml
[project]
name = "ev-factory"
version = "0.1.0"
description = "EV News Content Factory pipeline"
requires-python = ">=3.11"

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"

[tool.setuptools.packages.find]
include = ["ev_factory*"]
```

`ev_factory/__init__.py`:
```python
__version__ = "0.1.0"
```

`tests/__init__.py`: (empty file)

`.gitignore`:
```
__pycache__/
*.pyc
.pytest_cache/
jobs/
*.db
config.toml
.venv/
```

`config.example.toml`:
```toml
jobs_dir = "jobs"
db_path = "ev_factory.db"
source_language = "en"
target_languages = ["ru", "tr"]
dry_run = true
monthly_spend_cap_usd = 90.0
rss_sources = []
```

`tests/conftest.py`:
```python
import textwrap
from pathlib import Path

import pytest


@pytest.fixture
def tmp_config(tmp_path: Path) -> Path:
    """Write a minimal config.toml into a temp dir and return its path."""
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        textwrap.dedent(
            f"""
            jobs_dir = "{(tmp_path / 'jobs').as_posix()}"
            db_path = "{(tmp_path / 'ev_factory.db').as_posix()}"
            source_language = "en"
            target_languages = ["ru", "tr"]
            dry_run = true
            monthly_spend_cap_usd = 90.0
            rss_sources = []
            """
        ).strip()
    )
    return cfg
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_smoke.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml ev_factory/__init__.py tests/__init__.py tests/conftest.py config.example.toml .gitignore tests/test_smoke.py
git commit -m "chore: scaffold ev_factory package and pytest"
```

---

### Task 2: Configuration loading

**Files:**
- Create: `ev_factory/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: `tmp_config` fixture (Task 1).
- Produces:
  - `@dataclass Config` with fields: `jobs_dir: Path`, `db_path: Path`, `source_language: str`, `target_languages: list[str]`, `dry_run: bool`, `monthly_spend_cap_usd: float`, `rss_sources: list[str]`.
  - `Config.all_languages` property → `[source_language, *target_languages]`.
  - `load_config(path: str | Path) -> Config`.

- [ ] **Step 1: Write the failing test**

`tests/test_config.py`:
```python
from pathlib import Path

from ev_factory.config import Config, load_config


def test_load_config_parses_fields(tmp_config: Path):
    cfg = load_config(tmp_config)
    assert isinstance(cfg, Config)
    assert cfg.source_language == "en"
    assert cfg.target_languages == ["ru", "tr"]
    assert cfg.dry_run is True
    assert cfg.monthly_spend_cap_usd == 90.0
    assert isinstance(cfg.jobs_dir, Path)


def test_all_languages_puts_source_first(tmp_config: Path):
    cfg = load_config(tmp_config)
    assert cfg.all_languages == ["en", "ru", "tr"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ev_factory.config'`

- [ ] **Step 3: Write minimal implementation**

`ev_factory/config.py`:
```python
from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Config:
    jobs_dir: Path
    db_path: Path
    source_language: str
    target_languages: list[str]
    dry_run: bool
    monthly_spend_cap_usd: float
    rss_sources: list[str]

    @property
    def all_languages(self) -> list[str]:
        return [self.source_language, *self.target_languages]


def load_config(path: str | Path) -> Config:
    with open(path, "rb") as fh:
        data = tomllib.load(fh)
    return Config(
        jobs_dir=Path(data["jobs_dir"]),
        db_path=Path(data["db_path"]),
        source_language=data["source_language"],
        target_languages=list(data["target_languages"]),
        dry_run=bool(data["dry_run"]),
        monthly_spend_cap_usd=float(data["monthly_spend_cap_usd"]),
        rss_sources=list(data.get("rss_sources", [])),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_config.py -v`
Expected: PASS (both tests)

- [ ] **Step 5: Commit**

```bash
git add ev_factory/config.py tests/test_config.py
git commit -m "feat: config loading from config.toml"
```

---

### Task 3: Core models and enums

**Files:**
- Create: `ev_factory/models.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `class JobState(str, Enum)`: `NEW, INGESTED, SCRIPTED, LOCALIZED, RENDERED, IN_REVIEW, APPROVED, PUBLISHED, FAILED`.
  - `class StageStatus(str, Enum)`: `PENDING, RUNNING, DONE, FAILED, SKIPPED`.
  - `@dataclass StageResult`: `stage: str`, `status: StageStatus`, `message: str = ""`, `data: dict = {}`. Helpers `StageResult.ok(stage, message="", data=None)` and `StageResult.fail(stage, message)`.
  - `@dataclass ComplianceCheck`: `key: str`, `passed: bool`, `detail: str = ""`, `hard: bool = True`.
  - `def make_slug(title: str) -> str` → lowercase, hyphenated, alphanumeric-only, max 60 chars.

- [ ] **Step 1: Write the failing test**

`tests/test_models.py`:
```python
from ev_factory.models import (
    ComplianceCheck,
    JobState,
    StageResult,
    StageStatus,
    make_slug,
)


def test_jobstate_values_are_lowercase_strings():
    assert JobState.IN_REVIEW.value == "in_review"
    assert JobState.PUBLISHED == "published"


def test_stage_result_ok_and_fail_helpers():
    ok = StageResult.ok("script", message="done", data={"n": 1})
    assert ok.status is StageStatus.DONE
    assert ok.data == {"n": 1}

    bad = StageResult.fail("voice", "api error")
    assert bad.status is StageStatus.FAILED
    assert bad.message == "api error"


def test_compliance_check_defaults_to_hard():
    c = ComplianceCheck(key="copyright_text", passed=True)
    assert c.hard is True


def test_make_slug_normalizes():
    assert make_slug("Tesla Cuts Model Y Price by 10%!") == "tesla-cuts-model-y-price-by-10"
    assert make_slug("  Rivian   R2  ") == "rivian-r2"
    assert len(make_slug("x" * 200)) <= 60
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ev_factory.models'`

- [ ] **Step 3: Write minimal implementation**

`ev_factory/models.py`:
```python
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum


class JobState(str, Enum):
    NEW = "new"
    INGESTED = "ingested"
    SCRIPTED = "scripted"
    LOCALIZED = "localized"
    RENDERED = "rendered"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    PUBLISHED = "published"
    FAILED = "failed"


class StageStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class StageResult:
    stage: str
    status: StageStatus
    message: str = ""
    data: dict = field(default_factory=dict)

    @classmethod
    def ok(cls, stage: str, message: str = "", data: dict | None = None) -> "StageResult":
        return cls(stage=stage, status=StageStatus.DONE, message=message, data=data or {})

    @classmethod
    def fail(cls, stage: str, message: str) -> "StageResult":
        return cls(stage=stage, status=StageStatus.FAILED, message=message)


@dataclass
class ComplianceCheck:
    key: str
    passed: bool
    detail: str = ""
    hard: bool = True


def make_slug(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug[:60].rstrip("-")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_models.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add ev_factory/models.py tests/test_models.py
git commit -m "feat: core models, enums, and slug helper"
```

---

### Task 4: Job folder helpers

**Files:**
- Create: `ev_factory/jobfolder.py`
- Test: `tests/test_jobfolder.py`

**Interfaces:**
- Consumes: `make_slug` (Task 3).
- Produces:
  - `class JobFolder(root: Path)` with:
    - classmethod `create(jobs_dir: Path, date: str, slug: str) -> JobFolder` — makes `jobs_dir/date-slug/` and its `audio/` and `video/` subdirs, returns the instance.
    - property `job_id -> str` (the folder name, `date-slug`).
    - `story_json -> Path`, `compliance_json -> Path`, `audio_dir -> Path`, `video_dir -> Path`.
    - `script_path(lang: str) -> Path` → `script_<lang>.md`.
    - `metadata_path(lang: str) -> Path` → `metadata_<lang>.json`.
    - `write_json(path: Path, obj) -> None` and `read_json(path: Path) -> object` (UTF-8, indent=2).

- [ ] **Step 1: Write the failing test**

`tests/test_jobfolder.py`:
```python
from pathlib import Path

from ev_factory.jobfolder import JobFolder


def test_create_makes_dirs_and_id(tmp_path: Path):
    jf = JobFolder.create(tmp_path / "jobs", "2026-07-01", "tesla-price-cut")
    assert jf.job_id == "2026-07-01-tesla-price-cut"
    assert jf.audio_dir.is_dir()
    assert jf.video_dir.is_dir()


def test_language_scoped_paths(tmp_path: Path):
    jf = JobFolder.create(tmp_path / "jobs", "2026-07-01", "slug")
    assert jf.script_path("ru").name == "script_ru.md"
    assert jf.metadata_path("tr").name == "metadata_tr.json"


def test_write_and_read_json_roundtrip(tmp_path: Path):
    jf = JobFolder.create(tmp_path / "jobs", "2026-07-01", "slug")
    jf.write_json(jf.story_json, {"title": "Hello", "n": 2})
    assert jf.read_json(jf.story_json) == {"title": "Hello", "n": 2}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_jobfolder.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ev_factory.jobfolder'`

- [ ] **Step 3: Write minimal implementation**

`ev_factory/jobfolder.py`:
```python
from __future__ import annotations

import json
from pathlib import Path


class JobFolder:
    def __init__(self, root: Path):
        self.root = Path(root)

    @classmethod
    def create(cls, jobs_dir: Path, date: str, slug: str) -> "JobFolder":
        root = Path(jobs_dir) / f"{date}-{slug}"
        jf = cls(root)
        jf.audio_dir.mkdir(parents=True, exist_ok=True)
        jf.video_dir.mkdir(parents=True, exist_ok=True)
        return jf

    @property
    def job_id(self) -> str:
        return self.root.name

    @property
    def story_json(self) -> Path:
        return self.root / "story.json"

    @property
    def compliance_json(self) -> Path:
        return self.root / "compliance.json"

    @property
    def audio_dir(self) -> Path:
        return self.root / "audio"

    @property
    def video_dir(self) -> Path:
        return self.root / "video"

    def script_path(self, lang: str) -> Path:
        return self.root / f"script_{lang}.md"

    def metadata_path(self, lang: str) -> Path:
        return self.root / f"metadata_{lang}.json"

    def write_json(self, path: Path, obj) -> None:
        path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")

    def read_json(self, path: Path):
        return json.loads(path.read_text(encoding="utf-8"))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_jobfolder.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add ev_factory/jobfolder.py tests/test_jobfolder.py
git commit -m "feat: per-story job folder helpers"
```

---

### Task 5: SQLite database and JobRepository

**Files:**
- Create: `ev_factory/db.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Consumes: `JobState` (Task 3).
- Produces `class JobRepository(db_path: str | Path)` with:
  - `init_schema() -> None` (idempotent; `CREATE TABLE IF NOT EXISTS`).
  - `create_job(job_id: str, slug: str, date: str, languages: list[str]) -> None` — inserts the job row in state `NEW` and one `job_languages` row per language with status `pending`.
  - `get_job(job_id: str) -> dict | None` — keys: `id, slug, date, state, error, created_at, updated_at`.
  - `set_state(job_id: str, state: JobState) -> None` (updates `updated_at`).
  - `set_error(job_id: str, message: str) -> None` (sets state `FAILED` and `error`).
  - `set_language_status(job_id: str, lang: str, status: str) -> None`.
  - `get_language_statuses(job_id: str) -> dict[str, str]`.
  - `list_jobs(state: JobState | None = None) -> list[dict]`.
  - `record_cost(job_id: str, stage: str, provider: str, amount_usd: float) -> None`.
  - `spend_this_month(year_month: str) -> float` — sum of costs where `created_at` starts with `year_month` (e.g. `"2026-07"`).
  - `record_post(job_id: str, lang: str, platform: str, post_id: str, url: str) -> None`.
  - `get_post(job_id: str, lang: str, platform: str) -> dict | None`.

- [ ] **Step 1: Write the failing test**

`tests/test_db.py`:
```python
from pathlib import Path

from ev_factory.db import JobRepository
from ev_factory.models import JobState


def make_repo(tmp_path: Path) -> JobRepository:
    repo = JobRepository(tmp_path / "t.db")
    repo.init_schema()
    return repo


def test_init_schema_is_idempotent(tmp_path: Path):
    repo = make_repo(tmp_path)
    repo.init_schema()  # second call must not raise
    assert repo.get_job("missing") is None


def test_create_and_get_job(tmp_path: Path):
    repo = make_repo(tmp_path)
    repo.create_job("2026-07-01-slug", "slug", "2026-07-01", ["en", "ru"])
    job = repo.get_job("2026-07-01-slug")
    assert job["state"] == JobState.NEW
    assert job["slug"] == "slug"
    assert repo.get_language_statuses("2026-07-01-slug") == {"en": "pending", "ru": "pending"}


def test_set_state_and_error(tmp_path: Path):
    repo = make_repo(tmp_path)
    repo.create_job("j", "slug", "2026-07-01", ["en"])
    repo.set_state("j", JobState.SCRIPTED)
    assert repo.get_job("j")["state"] == JobState.SCRIPTED
    repo.set_error("j", "boom")
    job = repo.get_job("j")
    assert job["state"] == JobState.FAILED
    assert job["error"] == "boom"


def test_language_status_update(tmp_path: Path):
    repo = make_repo(tmp_path)
    repo.create_job("j", "slug", "2026-07-01", ["en", "ru"])
    repo.set_language_status("j", "ru", "failed")
    assert repo.get_language_statuses("j")["ru"] == "failed"


def test_list_jobs_by_state(tmp_path: Path):
    repo = make_repo(tmp_path)
    repo.create_job("a", "a", "2026-07-01", ["en"])
    repo.create_job("b", "b", "2026-07-01", ["en"])
    repo.set_state("b", JobState.IN_REVIEW)
    ids = [j["id"] for j in repo.list_jobs(state=JobState.IN_REVIEW)]
    assert ids == ["b"]
    assert len(repo.list_jobs()) == 2


def test_cost_logging_and_month_sum(tmp_path: Path):
    repo = make_repo(tmp_path)
    repo.create_job("j", "slug", "2026-07-01", ["en"])
    repo.record_cost("j", "voice", "elevenlabs", 1.5)
    repo.record_cost("j", "script", "anthropic", 0.25)
    month = repo.get_job("j")["created_at"][:7]
    assert abs(repo.spend_this_month(month) - 1.75) < 1e-9


def test_post_record_and_idempotency_lookup(tmp_path: Path):
    repo = make_repo(tmp_path)
    repo.create_job("j", "slug", "2026-07-01", ["en"])
    assert repo.get_post("j", "en", "youtube") is None
    repo.record_post("j", "en", "youtube", "vid123", "http://y/vid123")
    post = repo.get_post("j", "en", "youtube")
    assert post["post_id"] == "vid123"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_db.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ev_factory.db'`

- [ ] **Step 3: Write minimal implementation**

`ev_factory/db.py`:
```python
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from ev_factory.models import JobState


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    slug TEXT NOT NULL,
    date TEXT NOT NULL,
    state TEXT NOT NULL,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS job_languages (
    job_id TEXT NOT NULL,
    lang TEXT NOT NULL,
    status TEXT NOT NULL,
    PRIMARY KEY (job_id, lang)
);
CREATE TABLE IF NOT EXISTS costs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    provider TEXT NOT NULL,
    amount_usd REAL NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS posts (
    job_id TEXT NOT NULL,
    lang TEXT NOT NULL,
    platform TEXT NOT NULL,
    post_id TEXT NOT NULL,
    url TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (job_id, lang, platform)
);
"""


class JobRepository:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    def create_job(self, job_id: str, slug: str, date: str, languages: list[str]) -> None:
        now = _now()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO jobs (id, slug, date, state, error, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, NULL, ?, ?)",
                (job_id, slug, date, JobState.NEW.value, now, now),
            )
            conn.executemany(
                "INSERT INTO job_languages (job_id, lang, status) VALUES (?, ?, 'pending')",
                [(job_id, lang) for lang in languages],
            )

    def get_job(self, job_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            return dict(row) if row else None

    def set_state(self, job_id: str, state: JobState) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE jobs SET state = ?, updated_at = ? WHERE id = ?",
                (state.value, _now(), job_id),
            )

    def set_error(self, job_id: str, message: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE jobs SET state = ?, error = ?, updated_at = ? WHERE id = ?",
                (JobState.FAILED.value, message, _now(), job_id),
            )

    def set_language_status(self, job_id: str, lang: str, status: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE job_languages SET status = ? WHERE job_id = ? AND lang = ?",
                (status, job_id, lang),
            )

    def get_language_statuses(self, job_id: str) -> dict[str, str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT lang, status FROM job_languages WHERE job_id = ?", (job_id,)
            ).fetchall()
            return {r["lang"]: r["status"] for r in rows}

    def list_jobs(self, state: JobState | None = None) -> list[dict]:
        with self._connect() as conn:
            if state is None:
                rows = conn.execute("SELECT * FROM jobs ORDER BY created_at").fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM jobs WHERE state = ? ORDER BY created_at", (state.value,)
                ).fetchall()
            return [dict(r) for r in rows]

    def record_cost(self, job_id: str, stage: str, provider: str, amount_usd: float) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO costs (job_id, stage, provider, amount_usd, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (job_id, stage, provider, amount_usd, _now()),
            )

    def spend_this_month(self, year_month: str) -> float:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(amount_usd), 0.0) AS total FROM costs "
                "WHERE substr(created_at, 1, 7) = ?",
                (year_month,),
            ).fetchone()
            return float(row["total"])

    def record_post(
        self, job_id: str, lang: str, platform: str, post_id: str, url: str
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO posts "
                "(job_id, lang, platform, post_id, url, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (job_id, lang, platform, post_id, url, _now()),
            )

    def get_post(self, job_id: str, lang: str, platform: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM posts WHERE job_id = ? AND lang = ? AND platform = ?",
                (job_id, lang, platform),
            ).fetchone()
            return dict(row) if row else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_db.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add ev_factory/db.py tests/test_db.py
git commit -m "feat: SQLite JobRepository with jobs, languages, costs, posts"
```

---

### Task 6: State machine

**Files:**
- Create: `ev_factory/statemachine.py`
- Test: `tests/test_statemachine.py`

**Interfaces:**
- Consumes: `JobState` (Task 3), `JobRepository` (Task 5).
- Produces:
  - `ALLOWED_TRANSITIONS: dict[JobState, set[JobState]]` implementing `NEW→INGESTED→SCRIPTED→LOCALIZED→RENDERED→IN_REVIEW→APPROVED→PUBLISHED`, plus every non-terminal state may go to `FAILED`. Terminal states: `PUBLISHED`, `FAILED` (no outgoing except `FAILED→` none).
  - `HAPPY_PATH: list[JobState]` in order (NEW … PUBLISHED).
  - `class InvalidTransition(Exception)`.
  - `def can_transition(src: JobState, dst: JobState) -> bool`.
  - `def next_state(src: JobState) -> JobState | None` (next along HAPPY_PATH, `None` if terminal).
  - `def transition(repo: JobRepository, job_id: str, dst: JobState) -> None` — validates against the job's current state, raises `InvalidTransition` on illegal move, else calls `repo.set_state`.

- [ ] **Step 1: Write the failing test**

`tests/test_statemachine.py`:
```python
from pathlib import Path

import pytest

from ev_factory.db import JobRepository
from ev_factory.models import JobState
from ev_factory.statemachine import (
    InvalidTransition,
    can_transition,
    next_state,
    transition,
)


def test_happy_path_transitions_allowed():
    assert can_transition(JobState.NEW, JobState.INGESTED)
    assert can_transition(JobState.IN_REVIEW, JobState.APPROVED)
    assert can_transition(JobState.APPROVED, JobState.PUBLISHED)


def test_any_active_state_can_fail():
    assert can_transition(JobState.SCRIPTED, JobState.FAILED)
    assert can_transition(JobState.RENDERED, JobState.FAILED)


def test_illegal_skips_rejected():
    assert not can_transition(JobState.NEW, JobState.PUBLISHED)
    assert not can_transition(JobState.PUBLISHED, JobState.NEW)


def test_next_state_walks_happy_path():
    assert next_state(JobState.NEW) == JobState.INGESTED
    assert next_state(JobState.APPROVED) == JobState.PUBLISHED
    assert next_state(JobState.PUBLISHED) is None
    assert next_state(JobState.FAILED) is None


def test_transition_persists(tmp_path: Path):
    repo = JobRepository(tmp_path / "t.db")
    repo.init_schema()
    repo.create_job("j", "slug", "2026-07-01", ["en"])
    transition(repo, "j", JobState.INGESTED)
    assert repo.get_job("j")["state"] == JobState.INGESTED


def test_transition_rejects_illegal(tmp_path: Path):
    repo = JobRepository(tmp_path / "t.db")
    repo.init_schema()
    repo.create_job("j", "slug", "2026-07-01", ["en"])
    with pytest.raises(InvalidTransition):
        transition(repo, "j", JobState.PUBLISHED)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_statemachine.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ev_factory.statemachine'`

- [ ] **Step 3: Write minimal implementation**

`ev_factory/statemachine.py`:
```python
from __future__ import annotations

from ev_factory.db import JobRepository
from ev_factory.models import JobState

HAPPY_PATH: list[JobState] = [
    JobState.NEW,
    JobState.INGESTED,
    JobState.SCRIPTED,
    JobState.LOCALIZED,
    JobState.RENDERED,
    JobState.IN_REVIEW,
    JobState.APPROVED,
    JobState.PUBLISHED,
]

_TERMINAL = {JobState.PUBLISHED, JobState.FAILED}

ALLOWED_TRANSITIONS: dict[JobState, set[JobState]] = {}
for _i, _state in enumerate(HAPPY_PATH):
    _targets: set[JobState] = set()
    if _i + 1 < len(HAPPY_PATH):
        _targets.add(HAPPY_PATH[_i + 1])
    if _state not in _TERMINAL:
        _targets.add(JobState.FAILED)
    ALLOWED_TRANSITIONS[_state] = _targets
ALLOWED_TRANSITIONS[JobState.FAILED] = set()


class InvalidTransition(Exception):
    pass


def can_transition(src: JobState, dst: JobState) -> bool:
    return dst in ALLOWED_TRANSITIONS.get(src, set())


def next_state(src: JobState) -> JobState | None:
    if src in _TERMINAL:
        return None
    idx = HAPPY_PATH.index(src)
    if idx + 1 < len(HAPPY_PATH):
        return HAPPY_PATH[idx + 1]
    return None


def transition(repo: JobRepository, job_id: str, dst: JobState) -> None:
    job = repo.get_job(job_id)
    if job is None:
        raise InvalidTransition(f"unknown job {job_id}")
    src = JobState(job["state"])
    if not can_transition(src, dst):
        raise InvalidTransition(f"{src.value} -> {dst.value} not allowed")
    repo.set_state(job_id, dst)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_statemachine.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add ev_factory/statemachine.py tests/test_statemachine.py
git commit -m "feat: job state machine with legal transition enforcement"
```

---

### Task 7: Stage interface and context

**Files:**
- Create: `ev_factory/stages/__init__.py`
- Create: `ev_factory/stages/base.py`
- Test: `tests/test_stage_base.py`

**Interfaces:**
- Consumes: `Config` (Task 2), `JobFolder` (Task 4), `JobRepository` (Task 5), `StageResult`/`JobState` (Task 3).
- Produces:
  - `@dataclass StageContext`: `job_id: str`, `folder: JobFolder`, `config: Config`, `repo: JobRepository`. Property `dry_run -> bool` (delegates to `config.dry_run`).
  - `class Stage(ABC)` with class attrs `name: str` and `produces_state: JobState`, and abstract `run(self, ctx: StageContext) -> StageResult`. Concrete subclasses must set both class attrs (enforced by `__init_subclass__` raising `TypeError` if unset).

- [ ] **Step 1: Write the failing test**

`tests/test_stage_base.py`:
```python
from pathlib import Path

import pytest

from ev_factory.config import load_config
from ev_factory.db import JobRepository
from ev_factory.jobfolder import JobFolder
from ev_factory.models import JobState, StageResult
from ev_factory.stages.base import Stage, StageContext


def test_context_dry_run_delegates(tmp_config: Path):
    cfg = load_config(tmp_config)
    ctx = StageContext(job_id="j", folder=JobFolder(Path("x")), config=cfg,
                       repo=JobRepository(cfg.db_path))
    assert ctx.dry_run is True


def test_concrete_stage_runs():
    class DummyStage(Stage):
        name = "dummy"
        produces_state = JobState.INGESTED

        def run(self, ctx: StageContext) -> StageResult:
            return StageResult.ok(self.name)

    assert DummyStage().run(ctx=None).stage == "dummy"


def test_stage_without_attrs_rejected():
    with pytest.raises(TypeError):
        class Bad(Stage):
            def run(self, ctx):
                return None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_stage_base.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ev_factory.stages'`

- [ ] **Step 3: Write minimal implementation**

`ev_factory/stages/__init__.py`: (empty file)

`ev_factory/stages/base.py`:
```python
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ev_factory.config import Config
from ev_factory.db import JobRepository
from ev_factory.jobfolder import JobFolder
from ev_factory.models import JobState, StageResult


@dataclass
class StageContext:
    job_id: str
    folder: JobFolder
    config: Config
    repo: JobRepository

    @property
    def dry_run(self) -> bool:
        return self.config.dry_run


class Stage(ABC):
    name: str = ""
    produces_state: JobState | None = None

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if not cls.name or cls.produces_state is None:
            raise TypeError(
                f"{cls.__name__} must set class attrs 'name' and 'produces_state'"
            )

    @abstractmethod
    def run(self, ctx: StageContext) -> StageResult:
        ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_stage_base.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add ev_factory/stages/__init__.py ev_factory/stages/base.py tests/test_stage_base.py
git commit -m "feat: Stage interface and StageContext"
```

---

### Task 8: Orchestrator

**Files:**
- Create: `ev_factory/orchestrator.py`
- Test: `tests/test_orchestrator.py`

**Interfaces:**
- Consumes: `Stage`/`StageContext` (Task 7), `JobRepository` (Task 5), `JobFolder` (Task 4), `Config` (Task 2), `statemachine.transition`/`next_state` (Task 6), `StageResult`/`StageStatus`/`JobState` (Task 3).
- Produces:
  - `class Orchestrator(config: Config, repo: JobRepository, stages: list[Stage])`.
    - `run_job(job_id: str, until: JobState = JobState.IN_REVIEW) -> JobState` — resolves the `JobFolder` from `config.jobs_dir` + job_id, then for each stage whose `produces_state` is still ahead of the job's current state and at/before `until`, builds a `StageContext`, calls `stage.run`, and on `DONE` transitions the job to `stage.produces_state`. On a `FAILED` result or raised exception, calls `repo.set_error` and stops. Returns the final job state.
    - Idempotent: stages already passed (job state ≥ their `produces_state` on HAPPY_PATH) are skipped.

- [ ] **Step 1: Write the failing test**

`tests/test_orchestrator.py`:
```python
from pathlib import Path

from ev_factory.config import load_config
from ev_factory.db import JobRepository
from ev_factory.jobfolder import JobFolder
from ev_factory.models import JobState, StageResult
from ev_factory.orchestrator import Orchestrator
from ev_factory.stages.base import Stage, StageContext


class RecordingStage(Stage):
    name = "ingest"
    produces_state = JobState.INGESTED

    def __init__(self):
        self.calls = 0

    def run(self, ctx: StageContext) -> StageResult:
        self.calls += 1
        return StageResult.ok(self.name)


class ScriptStage(Stage):
    name = "script"
    produces_state = JobState.SCRIPTED

    def run(self, ctx: StageContext) -> StageResult:
        return StageResult.ok(self.name)


class BoomStage(Stage):
    name = "script"
    produces_state = JobState.SCRIPTED

    def run(self, ctx: StageContext) -> StageResult:
        return StageResult.fail(self.name, "kaboom")


def _setup(tmp_config: Path):
    cfg = load_config(tmp_config)
    repo = JobRepository(cfg.db_path)
    repo.init_schema()
    JobFolder.create(cfg.jobs_dir, "2026-07-01", "slug")
    repo.create_job("2026-07-01-slug", "slug", "2026-07-01", ["en"])
    return cfg, repo


def test_run_job_advances_states(tmp_config: Path):
    cfg, repo = _setup(tmp_config)
    orch = Orchestrator(cfg, repo, [RecordingStage(), ScriptStage()])
    final = orch.run_job("2026-07-01-slug")
    assert final == JobState.SCRIPTED
    assert repo.get_job("2026-07-01-slug")["state"] == JobState.SCRIPTED


def test_run_job_stops_at_until(tmp_config: Path):
    cfg, repo = _setup(tmp_config)
    orch = Orchestrator(cfg, repo, [RecordingStage(), ScriptStage()])
    final = orch.run_job("2026-07-01-slug", until=JobState.INGESTED)
    assert final == JobState.INGESTED


def test_failed_stage_marks_job_failed(tmp_config: Path):
    cfg, repo = _setup(tmp_config)
    orch = Orchestrator(cfg, repo, [RecordingStage(), BoomStage()])
    final = orch.run_job("2026-07-01-slug")
    assert final == JobState.FAILED
    assert repo.get_job("2026-07-01-slug")["error"] == "kaboom"


def test_rerun_skips_completed_stages(tmp_config: Path):
    cfg, repo = _setup(tmp_config)
    ingest = RecordingStage()
    orch = Orchestrator(cfg, repo, [ingest, ScriptStage()])
    orch.run_job("2026-07-01-slug")
    orch.run_job("2026-07-01-slug")  # second run
    assert ingest.calls == 1  # not re-run
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_orchestrator.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ev_factory.orchestrator'`

- [ ] **Step 3: Write minimal implementation**

`ev_factory/orchestrator.py`:
```python
from __future__ import annotations

from ev_factory.config import Config
from ev_factory.db import JobRepository
from ev_factory.jobfolder import JobFolder
from ev_factory.models import JobState, StageStatus
from ev_factory.stages.base import Stage, StageContext
from ev_factory.statemachine import HAPPY_PATH, transition


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
            # Skip stages already passed (idempotent re-run).
            if HAPPY_PATH.index(stage.produces_state) <= HAPPY_PATH.index(current):
                continue
            # Respect the 'until' ceiling.
            if HAPPY_PATH.index(stage.produces_state) > HAPPY_PATH.index(until):
                break
            try:
                result = stage.run(ctx)
            except Exception as exc:  # noqa: BLE001 - convert to job failure
                self.repo.set_error(job_id, f"{stage.name}: {exc}")
                return JobState.FAILED
            if result.status is not StageStatus.DONE:
                self.repo.set_error(job_id, result.message or f"{stage.name} failed")
                return JobState.FAILED
            transition(self.repo, job_id, stage.produces_state)
        return JobState(self.repo.get_job(job_id)["state"])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_orchestrator.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add ev_factory/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: orchestrator runs injected stages with skip/until/fail handling"
```

---

### Task 9: CLI entry point

**Files:**
- Create: `ev_factory/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `load_config` (Task 2), `JobRepository` (Task 5), `JobFolder` (Task 4), `make_slug`/`JobState` (Task 3).
- Produces:
  - `def build_parser() -> argparse.ArgumentParser` with subcommands:
    - `create --title TEXT --date YYYY-MM-DD [--config PATH]` — makes the folder, DB row (state NEW, all config languages), writes a minimal `story.json` (`{"title": ..., "date": ...}`), prints the `job_id`.
    - `status [--job-id ID] [--config PATH]` — prints one job's state + language statuses, or lists all jobs.
  - `def main(argv: list[str] | None = None) -> int` — dispatches; returns process exit code.
  - Note: `run` and `retry` subcommands are intentionally deferred to the plan that adds real stages, since the orchestrator needs a concrete stage list; `create` and `status` are sufficient to prove the chassis end-to-end.

- [ ] **Step 1: Write the failing test**

`tests/test_cli.py`:
```python
from pathlib import Path

from ev_factory.cli import main
from ev_factory.config import load_config
from ev_factory.db import JobRepository
from ev_factory.models import JobState


def test_create_makes_job_and_folder(tmp_config: Path, capsys):
    rc = main(["create", "--title", "Tesla Cuts Price!", "--date", "2026-07-01",
               "--config", str(tmp_config)])
    assert rc == 0
    job_id = capsys.readouterr().out.strip()
    assert job_id == "2026-07-01-tesla-cuts-price"

    cfg = load_config(tmp_config)
    assert (cfg.jobs_dir / job_id / "story.json").exists()
    repo = JobRepository(cfg.db_path)
    assert repo.get_job(job_id)["state"] == JobState.NEW
    assert set(repo.get_language_statuses(job_id)) == {"en", "ru", "tr"}


def test_status_lists_jobs(tmp_config: Path, capsys):
    main(["create", "--title", "A", "--date", "2026-07-01", "--config", str(tmp_config)])
    capsys.readouterr()
    rc = main(["status", "--config", str(tmp_config)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "2026-07-01-a" in out
    assert "new" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ev_factory.cli'`

- [ ] **Step 3: Write minimal implementation**

`ev_factory/cli.py`:
```python
from __future__ import annotations

import argparse

from ev_factory.config import load_config
from ev_factory.db import JobRepository
from ev_factory.jobfolder import JobFolder
from ev_factory.models import make_slug


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ev-factory")
    parser.add_argument("--config", default="config.toml")
    sub = parser.add_subparsers(dest="command", required=True)

    p_create = sub.add_parser("create", help="create a new story job")
    p_create.add_argument("--title", required=True)
    p_create.add_argument("--date", required=True)

    sub.add_parser("status", help="show job status").add_argument(
        "--job-id", default=None
    )
    return parser


def _cmd_create(args) -> int:
    cfg = load_config(args.config)
    slug = make_slug(args.title)
    job_id = f"{args.date}-{slug}"
    folder = JobFolder.create(cfg.jobs_dir, args.date, slug)
    folder.write_json(folder.story_json, {"title": args.title, "date": args.date})
    repo = JobRepository(cfg.db_path)
    repo.init_schema()
    repo.create_job(job_id, slug, args.date, cfg.all_languages)
    print(job_id)
    return 0


def _cmd_status(args) -> int:
    cfg = load_config(args.config)
    repo = JobRepository(cfg.db_path)
    repo.init_schema()
    if args.job_id:
        job = repo.get_job(args.job_id)
        if job is None:
            print(f"no such job: {args.job_id}")
            return 1
        print(f"{job['id']}  {job['state']}")
        for lang, status in repo.get_language_statuses(args.job_id).items():
            print(f"  {lang}: {status}")
    else:
        for job in repo.list_jobs():
            print(f"{job['id']}  {job['state']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "create":
        return _cmd_create(args)
    if args.command == "status":
        return _cmd_status(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cli.py -v`
Expected: PASS (both tests)

- [ ] **Step 5: Run the full suite and commit**

Run: `pytest -v`
Expected: ALL tests pass across every test file.

```bash
git add ev_factory/cli.py tests/test_cli.py
git commit -m "feat: CLI create and status commands"
```

---

## Self-Review

**Spec coverage (foundation scope):**
- Job folder per story per day (spec §7) → Task 4. ✅
- SQLite DB with state, per-language status, per-platform post IDs, cost logging (spec §7, §8) → Task 5. ✅
- State machine with legal transitions (spec §7) → Task 6. ✅
- Idempotent stages + retry-in-isolation contract (spec §7, §8) → Task 7 (interface) + Task 8 (skip-completed logic). ✅
- Dry-run threaded end-to-end (spec §8) → Task 2 (`Config.dry_run`) + Task 7 (`StageContext.dry_run`). ✅
- Monthly spend cap primitive (spec §8) → Task 5 (`spend_this_month`). ✅
- Publish idempotency (no double-post) primitive (spec §8) → Task 5 (`get_post`/`record_post`). ✅
- Orchestrator parks at `IN_REVIEW`, marks `FAILED` on error, continues later plans' per-language work (spec §7, §8) → Task 8. ✅
- **Deferred to later plans (intentionally, not gaps):** ingest/curate/script/localize stages (Plan 2), voice/avatar/assemble (Plan 3), review web UI (Plan 4), publishing + scheduler (Plan 5), compliance scoring logic (Plan 2 — the `ComplianceCheck` model is defined here in Task 3).

**Placeholder scan:** No TBD/TODO/"handle edge cases" placeholders; every code step contains complete, runnable code. ✅

**Type consistency:** `JobState`, `StageStatus`, `StageResult`, `ComplianceCheck`, `make_slug` (Task 3) are used with identical signatures in Tasks 4–9. `JobRepository` method names (`create_job`, `get_job`, `set_state`, `set_error`, `set_language_status`, `get_language_statuses`, `list_jobs`, `record_cost`, `spend_this_month`, `record_post`, `get_post`) are consistent between Task 5 definition and Tasks 6/8/9 usage. `StageContext`/`Stage` (Task 7) match orchestrator usage (Task 8). `Config` fields match loader (Task 2) and consumers. ✅
