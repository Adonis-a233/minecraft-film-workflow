"""In-memory world simulator implementing the full adapter protocol.

The mock applies compiled commands to a dict-backed world with vanilla
`keep` semantics, so workflow code and contract tests can run end-to-end
without Minecraft. It is a deterministic simulation, not a vanilla-accurate
emulator: `keep` on an occupied cell reports `changed_blocks: 0` instead of
reproducing vanilla's command failure.

Failure injection for contract tests:

- `uncertain_applied`: the write lands, then the response is lost — the
  command reports `uncertain` and `read_state` confirms it;
- `uncertain_lost`: the write never lands — `uncertain` and `read_state`
  disproves it.
"""

from __future__ import annotations

from datetime import UTC, datetime

from ..models import CommandResult, CompiledCommand


def _coords(text: str) -> "tuple[int, int, int]":
    x, y, z = (int(part) for part in text.split())
    return (x, y, z)


class MockMinecraftAdapter:
    name = "mock"
    dry_run = True  # simulation only; it never contacts a real game

    def __init__(
        self,
        *,
        uncertain_applied: "frozenset[int] | set[int]" = frozenset(),
        uncertain_lost: "frozenset[int] | set[int]" = frozenset(),
    ):
        self.blocks: "dict[tuple[int, int, int], str]" = {}
        self.entities: "list[tuple[str, tuple[int, int, int]]]" = []
        self.time: int | None = None
        self.weather: str | None = None
        self.executed: list[str] = []
        self._uncertain_applied = set(uncertain_applied)
        self._uncertain_lost = set(uncertain_lost)
        self._confirmed: set[int] = set()

    # -- protocol -----------------------------------------------------------

    def get_status(self) -> dict[str, object]:
        return {
            "connected": True,
            "mode": "simulation",
            "message": "In-memory world simulation; no game process involved",
        }

    def execute(self, command: CompiledCommand) -> CommandResult:
        self.executed.append(command.command)

        def result(status: str, message: str) -> CommandResult:
            return CommandResult(
                command_index=command.index,
                status=status,  # type: ignore[arg-type]
                message=message,
                observed_at=datetime.now(UTC),
                idempotency_key=command.idempotency_key,
            )

        if command.index in self._uncertain_lost:
            return result("uncertain", f"outcome unknown (simulated): {command.command}")
        if command.index in self._uncertain_applied:
            self._apply(command)
            self._confirmed.add(command.index)
            return result("uncertain", f"outcome unknown (simulated): {command.command}")

        self._apply(command)
        return result("applied", f"applied: {command.command}")

    def read_state(self, command: CompiledCommand) -> dict[str, object]:
        return {
            "command_index": command.index,
            "confirmed": command.index in self._confirmed,
            "time": self.time,
            "weather": self.weather,
            "block_count": len(self.blocks),
            "entity_count": len(self.entities),
        }

    # -- simulation ---------------------------------------------------------

    def _apply(self, command: CompiledCommand) -> None:
        parts = command.command.split()
        action = command.action_type
        if action == "set_time":
            self.time = int(parts[2])
        elif action == "set_weather":
            self.weather = parts[1]
        elif action == "set_block":
            position = _coords(" ".join(parts[1:4]))
            block = parts[4]
            if parts[5] == "keep" and position in self.blocks:
                return
            self.blocks[position] = block
        elif action == "fill":
            start = _coords(" ".join(parts[1:4]))
            end = _coords(" ".join(parts[4:7]))
            block = parts[7]
            placement = parts[8] if len(parts) > 8 else "replace"
            min_x, max_x = sorted((start[0], end[0]))
            min_y, max_y = sorted((start[1], end[1]))
            min_z, max_z = sorted((start[2], end[2]))
            for x in range(min_x, max_x + 1):
                for y in range(min_y, max_y + 1):
                    for z in range(min_z, max_z + 1):
                        if placement == "keep" and (x, y, z) in self.blocks:
                            continue
                        self.blocks[(x, y, z)] = block
        elif action == "summon":
            self.entities.append((parts[1], _coords(" ".join(parts[2:5]))))
        else:
            # Mocap and runtime commands are journaled without world effect.
            return
