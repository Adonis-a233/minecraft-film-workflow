from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path

from .locking import replace_evidence
from .models import CommandResult, RunManifest, RunState, ValidatedPlan


RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,80}$")


class ManifestStore:
    def __init__(self, workspace_root: Path):
        self.workspace_root = workspace_root.resolve()
        self.runs_root = self.workspace_root / "work" / "runs"

    def _run_dir(self, run_id: str) -> Path:
        if not RUN_ID_PATTERN.fullmatch(run_id):
            raise ValueError("invalid run id")
        path = (self.runs_root / run_id).resolve()
        if self.runs_root.resolve() not in path.parents:
            raise ValueError("run directory escaped workspace")
        return path

    @staticmethod
    def _write_new(path: Path, payload: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, default=str)
            stream.write("\n")

    @staticmethod
    def _write_atomic(path: Path, payload: object) -> None:
        temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        with temp.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, default=str)
            stream.write("\n")
        replace_evidence(temp, path)

    def create(self, validated: ValidatedPlan, run_id: str) -> RunManifest:
        run_dir = self._run_dir(run_id)
        run_dir.mkdir(parents=True, exist_ok=False)
        now = datetime.now(UTC)
        plan_path = run_dir / "scene-plan.json"
        commands_path = run_dir / "commands.json"
        results_path = run_dir / "results.jsonl"
        manifest_path = run_dir / "manifest.json"

        self._write_new(plan_path, validated.plan.model_dump(mode="json"))
        self._write_new(
            commands_path,
            [command.model_dump(mode="json") for command in validated.commands],
        )
        results_path.touch(exist_ok=False)

        manifest = RunManifest(
            run_id=run_id,
            plan_id=validated.plan.plan_id,
            plan_sha256=validated.plan_sha256,
            state=RunState.VALIDATED,
            created_at=now,
            updated_at=now,
            plan_file=str(plan_path.relative_to(self.workspace_root)).replace("\\", "/"),
            commands_file=str(commands_path.relative_to(self.workspace_root)).replace("\\", "/"),
            results_file=str(results_path.relative_to(self.workspace_root)).replace("\\", "/"),
        )
        self._write_new(manifest_path, manifest.model_dump(mode="json"))
        return manifest

    def load(self, run_id: str) -> RunManifest:
        path = self._run_dir(run_id) / "manifest.json"
        return RunManifest.model_validate_json(path.read_text(encoding="utf-8"))

    def save(self, manifest: RunManifest) -> None:
        path = self._run_dir(manifest.run_id) / "manifest.json"
        self._write_atomic(path, manifest.model_dump(mode="json"))

    def load_commands(self, manifest: RunManifest) -> list[dict[str, object]]:
        path = (self.workspace_root / manifest.commands_file).resolve()
        if self.workspace_root not in path.parents:
            raise ValueError("commands file escaped workspace")
        return json.loads(path.read_text(encoding="utf-8"))

    def append_result(self, manifest: RunManifest, result: CommandResult) -> None:
        path = (self.workspace_root / manifest.results_file).resolve()
        if self.workspace_root not in path.parents:
            raise ValueError("results file escaped workspace")
        with path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(result.model_dump_json())
            stream.write("\n")

