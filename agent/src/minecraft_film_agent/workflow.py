from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

from .compiler import validate_and_compile
from .manifest import ManifestStore
from .models import (
    CommandResult,
    CompiledCommand,
    RunManifest,
    RunState,
    ScenePlan,
    ValidatedPlan,
)
from .ports import MinecraftAdapter


class InvalidStateTransition(RuntimeError):
    pass


class ProductionWorkflow:
    def __init__(self, workspace_root: Path):
        self.workspace_root = workspace_root.resolve()
        self.store = ManifestStore(self.workspace_root)

    def validate(self, plan: ScenePlan) -> ValidatedPlan:
        return validate_and_compile(plan)

    def prepare(self, plan: ScenePlan, run_id: str | None = None) -> RunManifest:
        validated = self.validate(plan)
        resolved_run_id = run_id or (
            datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
        )
        return self.store.create(validated, resolved_run_id)

    def approve(self, run_id: str, approved_by: str) -> RunManifest:
        if not approved_by.strip():
            raise ValueError("approved_by is required")
        manifest = self.store.load(run_id)
        if manifest.state is not RunState.VALIDATED:
            raise InvalidStateTransition(
                f"approval requires validated state; current state is {manifest.state}"
            )
        now = datetime.now(UTC)
        updated = manifest.model_copy(
            update={
                "state": RunState.APPROVED,
                "approved_by": approved_by.strip(),
                "approved_at": now,
                "updated_at": now,
            }
        )
        self.store.save(updated)
        return updated

    def execute(self, run_id: str, adapter: MinecraftAdapter) -> RunManifest:
        manifest = self.store.load(run_id)
        if manifest.state is not RunState.APPROVED:
            raise InvalidStateTransition(
                f"execution requires approved state; current state is {manifest.state}"
            )

        now = datetime.now(UTC)
        dispatching = manifest.model_copy(
            update={
                "state": RunState.DISPATCHING,
                "updated_at": now,
                "adapter_name": adapter.name,
                "dry_run": adapter.dry_run,
            }
        )
        self.store.save(dispatching)

        try:
            adapter.get_status()
            for raw_command in self.store.load_commands(dispatching):
                command = CompiledCommand.model_validate(raw_command)
                result = adapter.execute(command)
                result = self._resolve_result(adapter, command, result)
                self.store.append_result(dispatching, result)
                if result.status in {"rejected", "failed"}:
                    raise RuntimeError(
                        f"command {result.command_index} {result.status}: {result.message}"
                    )
        except Exception as error:
            failed = dispatching.model_copy(
                update={
                    "state": RunState.FAILED,
                    "updated_at": datetime.now(UTC),
                    "error": str(error),
                }
            )
            self.store.save(failed)
            raise

        completed = dispatching.model_copy(
            update={
                "state": RunState.COMPLETED,
                "updated_at": datetime.now(UTC),
            }
        )
        self.store.save(completed)
        return completed

    @staticmethod
    def _resolve_result(
        adapter: MinecraftAdapter, command: CompiledCommand, result: CommandResult
    ) -> CommandResult:
        """Never report an uncertain outcome as success without reading state.

        An `uncertain` result means the response was lost; the actual game
        state decides. Applied writes are also followed by a state read so
        the audit trail records what the world actually looks like.
        """
        if result.status == "uncertain":
            observed = adapter.read_state(command)
            if observed.get("confirmed") is True:
                return result.model_copy(
                    update={
                        "status": "applied",
                        "observed_state": observed,
                        "message": f"{result.message} (resolved applied via state read)",
                    }
                )
            return result.model_copy(
                update={
                    "status": "failed",
                    "observed_state": observed,
                    "message": f"{result.message} (state read shows not applied)",
                }
            )
        if result.status == "applied":
            return result.model_copy(
                update={"observed_state": adapter.read_state(command)}
            )
        return result

    def get_run(self, run_id: str) -> RunManifest:
        return self.store.load(run_id)

