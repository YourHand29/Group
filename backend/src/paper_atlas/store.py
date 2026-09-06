"""Small, local persistence layer for completed Paper Atlas runs."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any

from .schemas import AnalysisResponse


class RunStore:
    """Persist response-shaped run records without storing the full paper."""

    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS analysis_runs (
                    run_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    response_json TEXT NOT NULL
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def save(self, response: AnalysisResponse) -> None:
        payload = json.dumps(response.model_dump(mode="json"), ensure_ascii=False)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO analysis_runs(run_id, created_at, response_json)
                VALUES (?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    created_at=excluded.created_at,
                    response_json=excluded.response_json
                """,
                (response.run_id, datetime.now(timezone.utc).isoformat(), payload),
            )

    def get(self, run_id: str) -> AnalysisResponse | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT response_json FROM analysis_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        return AnalysisResponse.model_validate(json.loads(row["response_json"]))

    def list_recent(self, limit: int = 20) -> list[AnalysisResponse]:
        safe_limit = max(1, min(limit, 100))
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT response_json FROM analysis_runs ORDER BY created_at DESC LIMIT ?",
                (safe_limit,),
            ).fetchall()
        return [AnalysisResponse.model_validate(json.loads(row["response_json"])) for row in rows]


def safe_save(store: RunStore, response: AnalysisResponse) -> str | None:
    """Save a run without hiding an otherwise successful analysis."""

    try:
        store.save(response)
    except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
        return f"Run persistence was unavailable: {exc}"
    return None


def safe_save_path(path: str, response: AnalysisResponse) -> str | None:
    try:
        return safe_save(RunStore(path), response)
    except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
        return f"Run persistence was unavailable: {exc}"
