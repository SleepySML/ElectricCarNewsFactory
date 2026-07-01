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
