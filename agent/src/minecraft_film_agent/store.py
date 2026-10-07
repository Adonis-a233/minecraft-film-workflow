"""SQLite-backed production store: runs, stage records, and output registry.

Why SQLite (plan §10.1): the controller must survive process restarts and
prove what already happened. Stage records are append-only; the latest record
for a stage decides its status; a run whose plan hash was seen before is
returned unchanged instead of being re-prepared (idempotent submission).

The database lives under ``work/runs/_production/`` so it can never collide
with a per-run directory id.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from .production_models import (
    ErrorClass,
    StageName,
    StageRecord,
    StageStatus,
)

RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    production_id TEXT NOT NULL,
    plan_hash TEXT NOT NULL UNIQUE,
    state TEXT NOT NULL,
    approved_by TEXT,
    approved_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS stage_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    attempt INTEGER NOT NULL,
    status TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    output_path TEXT,
    output_sha256 TEXT,
    evidence TEXT NOT NULL DEFAULT '{}',
    error_class TEXT,
    message TEXT,
    recorded_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_stage_run ON stage_records(run_id, stage, id);
CREATE TABLE IF NOT EXISTS artifacts (
    path TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


class DuplicateArtifactError(RuntimeError):
    pass


class ProductionStore:
    def __init__(self, workspace_root: Path):
        self.workspace_root = workspace_root.resolve()
        self.runs_root = self.workspace_root / "work" / "runs"
        self.runs_root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.runs_root / "_production" / "production.sqlite3"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.db_path)
        self._connection.row_factory = sqlite3.Row
        self._connection.executescript(_SCHEMA)
        self._connection.commit()

    # -- runs ----------------------------------------------------------------

    def create_run(self, run_id: str, production_id: str, plan_hash: str) -> "tuple[str, bool]":
        """Register a run; returns (run_id, created).

        Same plan hash ⇒ the existing run is returned untouched, so resubmitting
        an identical plan can never create duplicate side effects.
        """

        if not RUN_ID_PATTERN.fullmatch(run_id):
            raise ValueError("invalid run id")
        now = _now()
        try:
            with self._connection:
                self._connection.execute(
                    "INSERT INTO runs (run_id, production_id, plan_hash, state, created_at, updated_at)"
                    " VALUES (?, ?, ?, 'open', ?, ?)",
                    (run_id, production_id, plan_hash, now, now),
                )
        except sqlite3.IntegrityError as error:
            row = self._connection.execute(
                "SELECT run_id, plan_hash FROM runs WHERE plan_hash = ? OR run_id = ?",
                (plan_hash, run_id),
            ).fetchone()
            if row is not None and row["plan_hash"] == plan_hash:
                return row["run_id"], False
            raise ValueError(f"run id already in use: {run_id}") from error
        return run_id, True

    def run_exists(self, run_id: str) -> bool:
        row = self._connection.execute(
            "SELECT 1 FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        return row is not None

    def get_run(self, run_id: str) -> dict[str, object]:
        row = self._connection.execute(
            "SELECT * FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"unknown run: {run_id}")
        return dict(row)

    def set_approval(self, run_id: str, approved_by: str) -> None:
        if not approved_by.strip():
            raise ValueError("approved_by is required")
        with self._connection:
            updated = self._connection.execute(
                "UPDATE runs SET approved_by = ?, approved_at = ?, updated_at = ?"
                " WHERE run_id = ? AND approved_by IS NULL",
                (approved_by.strip(), _now(), _now(), run_id),
            )
            if updated.rowcount != 1:
                row = self.get_run(run_id)
                if row.get("approved_by") is None:
                    raise ValueError(f"unknown run: {run_id}")
                raise ValueError(f"run {run_id} was already approved by {row['approved_by']}")

    def approval(self, run_id: str) -> str | None:
        return self.get_run(run_id).get("approved_by")  # type: ignore[return-value]

    # -- stage records -------------------------------------------------------

    def record_stage(self, record: StageRecord) -> None:
        with self._connection:
            self._connection.execute(
                "INSERT INTO stage_records"
                " (run_id, stage, attempt, status, input_hash, output_path, output_sha256,"
                "  evidence, error_class, message, recorded_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record.run_id,
                    record.stage.value,
                    record.attempt,
                    record.status.value,
                    record.input_hash,
                    record.output_path,
                    record.output_sha256,
                    json_dumps(record.evidence),
                    record.error_class.value if record.error_class else None,
                    record.message,
                    record.recorded_at.isoformat(),
                ),
            )

    def next_attempt(self, run_id: str, stage: StageName) -> int:
        row = self._connection.execute(
            "SELECT COUNT(*) AS n FROM stage_records WHERE run_id = ? AND stage = ?",
            (run_id, stage.value),
        ).fetchone()
        return int(row["n"]) + 1

    def latest_stage(self, run_id: str, stage: StageName) -> StageRecord | None:
        row = self._connection.execute(
            "SELECT * FROM stage_records WHERE run_id = ? AND stage = ?"
            " ORDER BY id DESC LIMIT 1",
            (run_id, stage.value),
        ).fetchone()
        return _record_from_row(row) if row else None

    def succeeded_stage(self, run_id: str, stage: StageName, input_hash: str) -> StageRecord | None:
        """A prior success for the exact same input makes the stage a no-op."""

        row = self._connection.execute(
            "SELECT * FROM stage_records WHERE run_id = ? AND stage = ?"
            " AND status = 'succeeded' AND input_hash = ? ORDER BY id DESC LIMIT 1",
            (run_id, stage.value, input_hash),
        ).fetchone()
        return _record_from_row(row) if row else None

    def stages(self, run_id: str) -> list[StageRecord]:
        rows = self._connection.execute(
            "SELECT * FROM stage_records WHERE run_id = ? ORDER BY id", (run_id,)
        ).fetchall()
        return [record for row in rows if (record := _record_from_row(row)) is not None]

    # -- artifact registry ---------------------------------------------------

    def register_artifact(self, path: str, run_id: str) -> None:
        try:
            with self._connection:
                self._connection.execute(
                    "INSERT INTO artifacts (path, run_id, created_at) VALUES (?, ?, ?)",
                    (path, run_id, _now()),
                )
        except sqlite3.IntegrityError as error:
            raise DuplicateArtifactError(f"artifact already registered: {path}") from error

    def artifact_taken(self, path: str) -> bool:
        row = self._connection.execute(
            "SELECT 1 FROM artifacts WHERE path = ?", (path,)
        ).fetchone()
        return row is not None

    def next_output_version(self, shot_id: str, also_taken=None) -> str:
        """First free `assets/renders/<shot>-v<N>.mp4`. Existing outputs are never overwritten.

        ``also_taken(rel)`` lets the controller add filesystem evidence to the
        registry check: a failed export may have left a partial file on disk,
        and that version is dead even though it was never registered.
        """

        version = 1
        while True:
            relative = f"assets/renders/{shot_id}-v{version}.mp4"
            if self.artifact_taken(relative):
                version += 1
                continue
            if also_taken is not None and also_taken(relative):
                version += 1
                continue
            return relative

    def close(self) -> None:
        self._connection.close()


def _record_from_row(row: sqlite3.Row) -> StageRecord | None:
    """Rows written by a retired stage vocabulary (e.g. v1 ``record_take``)
    stay in the database as history but never re-enter the live chain."""

    import json

    try:
        stage = StageName(row["stage"])
    except ValueError:
        return None
    return StageRecord(
        run_id=row["run_id"],
        stage=stage,
        attempt=row["attempt"],
        status=StageStatus(row["status"]),
        input_hash=row["input_hash"],
        output_path=row["output_path"],
        output_sha256=row["output_sha256"],
        evidence=json.loads(row["evidence"]),
        error_class=ErrorClass(row["error_class"]) if row["error_class"] else None,
        message=row["message"],
        recorded_at=datetime.fromisoformat(row["recorded_at"]),
    )


def _now() -> str:
    return datetime.now(UTC).isoformat()


def json_dumps(payload: object) -> str:
    import json

    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
