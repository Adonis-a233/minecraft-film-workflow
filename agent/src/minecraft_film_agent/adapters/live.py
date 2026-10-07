"""Live Minecraft adapter: compiler-owned actions → typed contract-v3 RPC.

Safety properties (workflow v3 §4):

- ``CompiledCommand.command`` text is NEVER forwarded to the bridge. It is
  parsed with a strict grammar of compiler-owned formats; anything else fails
  closed — a free-form ``run_command`` surface does not exist.
- Every write is gated on the truthful game state first: ``in_world``, exact
  save name, exact dimension, non-null player, not paused.
- World writes ride contract 3: submit (accepted = durably journaled) then
  poll to succeeded/failed/unknown. The idempotency_key is the compiler's key
  END TO END — never regenerated, never transformed (the v2 label transform
  made status queries miss their own operations).
- ``succeeded`` means the bridge journaled a proof with ok=true. A residual
  ``unknown`` is resolved through the operation status AND a typed state read
  against the EXPECTED target values parsed from the command text — reading
  *a* state is never mistaken for having reached the goal state.
- ``replace`` placement does not exist here; mocap scene-playback actions are
  timeline-event territory and are refused at adapter level.
- Mocap transitions stay on contract 2 (client-feedback semantics).
"""

from __future__ import annotations

from datetime import UTC, datetime
import time as _time

from ..bridge_client import BridgeTransportError, CinematicBridgeClient
from ..models import CommandResult, CompiledCommand
from ..production_models import (
    ErrorClass,
    GameStateV2,
    MocapPhase,
    OperationResultV3,
)


class LiveAdapterError(RuntimeError):
    def __init__(self, error_class: ErrorClass, message: str):
        self.error_class = error_class
        super().__init__(message)


_WORLD_WRITE_COMMAND_PREFIXES = ("time set ", "weather ", "setblock ", "fill ", "summon ")


def parse_world_command(command: str) -> "tuple[str, dict[str, object]] | None":
    """Strict parse of compiler-owned world-write command text.

    Returns ``(operation, params)`` or None when the text is not a recognized
    world write (mocap commands are handled separately). Raises nothing.
    """

    parts = command.split(" ")
    try:
        if command.startswith("time set ") and len(parts) == 3:
            return "set_time", {"value": int(parts[2])}
        if command.startswith("weather ") and len(parts) == 3:
            return "set_weather", {
                "weather": parts[1],
                "duration_seconds": int(parts[2][:-1] if parts[2].endswith("s") else parts[2]),
            }
        if command.startswith("setblock ") and len(parts) == 6:
            if parts[5] != "keep":
                return None  # replace is disabled; refuse rather than adapt
            return "set_block_keep", {
                "x": int(parts[1]), "y": int(parts[2]), "z": int(parts[3]),
                "block": parts[4],
            }
        if command.startswith("fill ") and len(parts) == 9:
            if parts[8] != "keep":
                return None
            return "fill_keep", {
                "start": {"x": int(parts[1]), "y": int(parts[2]), "z": int(parts[3])},
                "end": {"x": int(parts[4]), "y": int(parts[5]), "z": int(parts[6])},
                "block": parts[7],
            }
        if command.startswith("summon ") and len(parts) == 5:
            return "summon", {
                "entity": parts[1],
                "x": int(parts[2]), "y": int(parts[3]), "z": int(parts[4]),
            }
    except ValueError:
        return None
    return None


def expected_target_state(command: CompiledCommand) -> dict[str, object]:
    """The goal values this command must produce, parsed from its own text.

    ``confirmed`` may only be true when the observed world equals these —
    "time is readable" proved nothing (v3 §2: the weak-proof hole).
    """

    parsed = parse_world_command(command.command)
    if not parsed:
        return {}
    operation, params = parsed
    if operation == "set_time":
        return {"time_of_day": params["value"]}
    if operation == "set_weather":
        weather = str(params["weather"])
        return {
            "raining": weather != "clear",
            "thundering": weather == "thunder",
        }
    if operation == "set_block_keep":
        return {"block": params["block"]}
    # fill_keep / summon: the journaled proof (exact change set / entity
    # identity) is the verification; no cheap client-side read can replace it.
    return {}


def _observed_matches(observed: dict[str, object], expected: dict[str, object]) -> bool:
    if not expected:
        return False
    return all(observed.get(key) == value for key, value in expected.items())


class LiveMinecraftAdapter:
    """MinecraftAdapter implementation over the real cinematic bridge."""

    name = "cinematic-bridge-live"
    dry_run = False

    def __init__(
        self,
        client: CinematicBridgeClient,
        *,
        run_id: str,
        build_region: dict[str, object],
        expected_save: str,
        expected_dimension: str = "minecraft:overworld",
        expected_player: str,
        dispatch_timeout_seconds: float = 5.0,
        await_timeout_seconds: float = 30.0,
        poll_interval_seconds: float = 0.4,
        poll=None,
    ):
        self.client = client
        self.run_id = run_id
        self.build_region = build_region
        self.expected_save = expected_save
        self.expected_dimension = expected_dimension
        self.expected_player = expected_player
        self.timeout = dispatch_timeout_seconds
        self.await_timeout = await_timeout_seconds
        self.poll_interval = poll_interval_seconds
        self._poll = poll  # injectable sleep for offline tests; None → time.sleep

    # -- protocol ------------------------------------------------------------

    def get_status(self) -> dict[str, object]:
        state = self.client.game_state(self.run_id)
        return state.model_dump(mode="json")

    def execute(self, command: CompiledCommand) -> CommandResult:
        if command.action_type.startswith("mocap_"):
            return self._execute_mocap(command)
        parsed = parse_world_command(command.command)
        if parsed is None:
            return self._result(command, "rejected",
                                f"command text is not a compiler-owned world write: "
                                f"{command.action_type}")
        operation, params = parsed
        params = {**params, "build_region": self.build_region}
        self._assert_writable()
        try:
            submitted = self.client.submit_world_op_v3(
                self.run_id, operation, params,
                idempotency_key=command.idempotency_key,
            )
        except BridgeTransportError as error:
            if error.kind is ErrorClass.OPERATION_TIMEOUT_UNKNOWN:
                return self._resolve_unknown(command, error)
            return self._result(command, "failed", f"{error.kind.value}: {error}")
        return self._await_v3(command, submitted)

    def await_scene_weather(self, command: CompiledCommand) -> dict:
        """A correct instant flag is distinct from a visually settled scene."""
        parsed=parse_world_command(command.command)
        if parsed is None or parsed[0]!='set_weather': raise ValueError('not a weather command')
        expected=expected_target_state(command)
        deadline=_time.monotonic()+30
        while True:
            self._assert_writable()
            observed=dict(self.client.world_read(self.run_id,'get_weather',f'visual-{command.index}',{}))
            gradients=[observed.get('rain_gradient'),observed.get('thunder_gradient')]
            if any(type(g) not in (int,float) or not 0<=g<=1 for g in gradients):
                raise LiveAdapterError(ErrorClass.VALIDATION_FAILED,'visual weather read is unavailable')
            flags=[expected['raining'],expected['thundering']]
            if all(observed.get(k)==expected[k] for k in ('raining','thundering')) and all(
                g>=.99 if flag else g<=.01 for g,flag in zip(gradients,flags)):
                return observed
            if _time.monotonic()>=deadline:
                raise LiveAdapterError(ErrorClass.VALIDATION_FAILED,'weather did not visually settle within 30 seconds')
            (self._poll or _time.sleep)(.1)

    def read_state(self, command: CompiledCommand) -> dict[str, object]:
        """Operation-specific observation used to resolve an unknown write.

        The journal answer decides "did this operation land"; for
        set_time/set_weather/set_block_keep the CURRENT world must also match
        the expected target values before anything may claim confirmed.
        """

        expected = expected_target_state(command)
        proof: dict[str, object] = {"expected": expected}
        if command.action_type.startswith("mocap_"):
            status = self.client.operation_status(
                self.run_id, f"status-{command.idempotency_key.replace('/', '-')}",
                command.idempotency_key,
            )
            proof["journal_status"] = status.status
            if status.result:
                proof["journal"] = status.result
            proof["confirmed"] = status.status in ("applied", "observed")
            return proof
        status = self.client.operation_status_v3(self.run_id, command.idempotency_key)
        proof["journal_status"] = status.status
        if status.result:
            proof["journal"] = status.result
        if status.status == "succeeded":
            # The journaled proof with ok=true IS the completion evidence.
            proof["confirmed"] = True
            return proof
        if status.status == "failed":
            proof["confirmed"] = False
            return proof
        # pending/unknown: check the CURRENT world against the expected goal.
        try:
            observed = self._observe(command)
            proof.update(observed)
            proof["confirmed"] = _observed_matches(observed, expected)
        except BridgeTransportError as error:
            proof["confirmed"] = False
            proof["read_error"] = str(error)
        return proof

    def _observe(self, command: CompiledCommand) -> dict[str, object]:
        """Typed read of the value this command targets (label for the proof)."""

        label = f"proof-{command.index}"
        if command.action_type == "set_time":
            return dict(self.client.world_read(self.run_id, "get_time", label, {}))
        if command.action_type == "set_weather":
            return dict(self.client.world_read(self.run_id, "get_weather", label, {}))
        if command.action_type == "set_block_keep":
            parsed = parse_world_command(command.command)
            if parsed:
                params = parsed[1]
                return dict(self.client.world_read(
                    self.run_id, "get_block", label,
                    {"x": params["x"], "y": params["y"], "z": params["z"]}))
        return {}

    # -- contract-3 completion -------------------------------------------------

    def _await_v3(self, command: CompiledCommand, submitted: OperationResultV3) -> CommandResult:
        try:
            result = self.client.await_world_op_v3(
                self.run_id, command.idempotency_key, submitted,
                timeout_seconds=self.await_timeout,
                poll_interval_seconds=self.poll_interval,
                poll=self._poll,
            )
        except BridgeTransportError as error:
            if error.kind is ErrorClass.OPERATION_TIMEOUT_UNKNOWN:
                return self._resolve_unknown(command, error)
            return self._result(command, "failed", f"{error.kind.value}: {error}")
        return self._to_command_result_v3(command, result)

    def _to_command_result_v3(
        self, command: CompiledCommand, result: OperationResultV3
    ) -> CommandResult:
        if result.status == "succeeded":
            return self._result(command, "applied",
                                result.message or "journaled proof ok",
                                observed_state=result.result)
        if result.status in ("accepted", "pending"):
            # The job is durably queued; the answer is just not in yet.
            return self._result(command, "uncertain",
                                result.message or f"write still {result.status} "
                                f"after {self.await_timeout}s; resolve via "
                                "operation status before retrying",
                                observed_state=result.result)
        if result.status == "unknown":
            return self._resolve_unknown(
                command,
                BridgeTransportError(ErrorClass.OPERATION_TIMEOUT_UNKNOWN,
                                     result.message or "bridge reported unknown"),
            )
        if result.status == "failed":
            return self._result(command, "failed",
                                result.message or "journaled proof failed",
                                observed_state=result.result)
        if result.status == "applied":
            return self._result(command, "applied",
                                result.message or "applied",
                                observed_state=result.result)
        return self._result(command, "rejected",
                            result.message or "bridge rejected the operation",
                            observed_state=result.result)

    # -- mocap actions through the state machine ------------------------------

    def _execute_mocap(self, command: CompiledCommand) -> CommandResult:
        self._assert_writable()
        try:
            state = self.client.mocap_state(self.run_id)
            if command.action_type == "mocap_recording_start":
                # The live-proven two-step start (F6): the state decides
                # whether this dispatch is prepare or confirm.
                if state.state is MocapPhase.IDLE:
                    result = self.client.mocap_transition(self.run_id, "prepare_recording")
                elif state.state is MocapPhase.WAITING_FOR_SELECTION:
                    result = self.client.mocap_transition(self.run_id, "confirm_recording_start")
                else:
                    return self._result(command, "rejected",
                                        f"recorder is {state.state.value}; cannot start from there")
            elif command.action_type == "mocap_recording_stop":
                result = self.client.mocap_transition(self.run_id, "stop_recording")
            elif command.action_type == "mocap_recording_save":
                name = command.command.removeprefix("mocap recording save ").strip()
                result = self.client.mocap_transition(self.run_id, "save_recording", name=name)
            else:
                return self._result(command, "rejected",
                                    f"{command.action_type} is a timeline-event action, "
                                    "not a live adapter command")
        except BridgeTransportError as error:
            if error.kind is ErrorClass.OPERATION_TIMEOUT_UNKNOWN:
                return self._resolve_unknown(command, error)
            return self._result(command, "failed", f"{error.kind.value}: {error}")
        return self._to_command_result(command, result)

    # -- helpers ---------------------------------------------------------------

    def _assert_writable(self) -> None:
        state = self.client.game_state(self.run_id)
        refusal = state.pre_write_gate(
            expected_save=self.expected_save,
            expected_dimension=self.expected_dimension,
            expected_player=self.expected_player,
        )
        if refusal:
            raise LiveAdapterError(ErrorClass.WORLD_MISMATCH, f"pre-write gate: {refusal}")

    def _resolve_unknown(self, command: CompiledCommand, error: BridgeTransportError) -> CommandResult:
        try:
            proof = self.read_state(command)
        except BridgeTransportError as read_error:
            return self._result(command, "uncertain",
                                f"{error}; state read also failed: {read_error}")
        if proof.get("confirmed") is True:
            return self._result(
                command, "applied",
                f"{error} (resolved applied via journal/target-state read)",
                observed_state=proof,
            )
        return self._result(
            command, "uncertain",
            f"{error} (journal/target-state read shows not reached)",
            observed_state=proof,
        )

    def _to_command_result(
        self, command: CompiledCommand, result
    ) -> CommandResult:
        if result.status in ("applied", "observed"):
            return self._result(command, "applied", result.message or "applied",
                                observed_state=result.result)
        if result.status == "queued" or result.status == "running":
            return self._result(command, "uncertain",
                                result.message or f"dispatch {result.status}")
        if result.status == "unknown":
            return self._resolve_unknown(
                command,
                BridgeTransportError(ErrorClass.OPERATION_TIMEOUT_UNKNOWN,
                                     result.message or "bridge reported unknown"),
            )
        if result.status == "failed":
            return self._result(command, "failed",
                                result.message or "bridge reported failure",
                                observed_state=result.result)
        return self._result(command, "rejected",
                            result.message or "bridge rejected the operation",
                            observed_state=result.result)

    @staticmethod
    def _result(
        command: CompiledCommand,
        status: str,
        message: str,
        observed_state: dict[str, object] | None = None,
    ) -> CommandResult:
        return CommandResult(
            command_index=command.index,
            status=status,  # type: ignore[arg-type]
            message=message,
            observed_at=datetime.now(UTC),
            idempotency_key=command.idempotency_key,
            observed_state=observed_state,
        )


__all__ = [
    "LiveMinecraftAdapter",
    "LiveAdapterError",
    "parse_world_command",
    "expected_target_state",
]
