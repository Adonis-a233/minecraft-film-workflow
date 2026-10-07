from __future__ import annotations

from datetime import UTC, datetime

from ..models import CommandResult, CompiledCommand


class DryRunMinecraftAdapter:
    """Offline adapter that records intent and never contacts Minecraft."""

    name = "dry-run"
    dry_run = True

    def get_status(self) -> dict[str, object]:
        return {
            "connected": False,
            "mode": "offline",
            "message": "No game connection is attempted by the dry-run adapter",
        }

    def execute(self, command: CompiledCommand) -> CommandResult:
        return CommandResult(
            command_index=command.index,
            status="skipped",
            message=f"dry-run only: {command.command}",
            observed_at=datetime.now(UTC),
            idempotency_key=command.idempotency_key,
        )

    def read_state(self, command: CompiledCommand) -> dict[str, object]:
        return {
            "command_index": command.index,
            "mode": "offline",
            "message": "the dry-run adapter reads no game state",
        }

