"""LiveMinecraftAdapter: strict parsing, typed contract-v3 RPC, pre-write gate.

The adapter must never forward ``CompiledCommand.command`` text; it parses
compiler-owned formats into contract-v3 params and lets the bridge revalidate
independently. World writes ride the async pipeline (submit → poll), the
compiler's idempotency key travels unchanged, and an unknown outcome is only
resolved through the journal plus an expected-target state read. All bridge
calls here go to a recording fake.
"""

from __future__ import annotations

import pytest

from minecraft_film_agent.adapters.live import (
    LiveAdapterError,
    LiveMinecraftAdapter,
    expected_target_state,
    parse_world_command,
)
from minecraft_film_agent.models import CompiledCommand
from minecraft_film_agent.production_models import (
    ErrorClass,
    OperationResultV2,
    OperationResultV3,
    SessionPhase,
    GameStateV2,
)

REGION = {"start": {"x": 0, "y": 60, "z": 0}, "end": {"x": 16, "y": 72, "z": 16}}


def _command(action_type: str, text: str, index: int = 0) -> CompiledCommand:
    return CompiledCommand(
        index=index, action_type=action_type, command=text,
        side_effect="world_write", idempotency_key=f"plan-a{index:03d}",
    )


def _result(request_key: str, status: str, result: dict | None = None) -> OperationResultV2:
    return OperationResultV2(
        operation_id="op", idempotency_key=request_key, status=status,
        journal_state="observed" if status in ("applied", "failed") else "rejected",
        result=result or {},
    )


def _v3(key: str, status: str, result: dict | None = None,
        journal_state: str | None = None) -> OperationResultV3:
    state = journal_state or {
        "accepted": "queued", "pending": "running", "succeeded": "succeeded",
        "failed": "failed", "rejected": None, "unknown": "unknown",
    }[status]
    return OperationResultV3(
        schema_version=3, operation_id=key.replace("/", "-"),
        idempotency_key=key, status=status, journal_state=state,
        result=result or {},
    )


class RecordingClient:
    name = "recording-fake"
    recording_root = None

    def __init__(self, *, game_state: dict | None = None):
        self.calls: list[tuple[str, dict]] = []
        self.state_payload = game_state or GameStateV2(
            session_phase=SessionPhase.IN_WORLD, save_name="Marx Video Test",
            dimension="minecraft:overworld", player_name="CineProbe",
            paused=False, client_tick=1, blocking_screen=False,
        ).model_dump(mode="json")
        self.mocap = "idle"
        self.replies: dict[str, dict] = {}
        # contract-3 recording
        self.v3_calls: list[tuple[str, str, dict]] = []  # (method, key, params)
        self.v3_keys: list[str] = []  # keys seen by the status query
        self.v3_submit_status = "accepted"
        self.v3_final_status = "succeeded"
        self.v3_final_result: dict = {"proof": {"ok": True}}
        self.status_answers: list[str] = []  # queued answers, then v3_final_status
        self.reads: dict[str, dict] = {}

    def game_state(self, run_id: str) -> GameStateV2:
        return GameStateV2.model_validate(self.state_payload)

    # -- contract 3 ------------------------------------------------------------

    def submit_world_op_v3(self, run_id: str, operation: str, params: dict, *,
                           idempotency_key: str, plan_hash: str | None = None
                           ) -> OperationResultV3:
        self.v3_calls.append((f"world.{operation}", idempotency_key, params))
        return _v3(idempotency_key, self.v3_submit_status,
                   {"idempotency_key": idempotency_key})

    def operation_status_v3(self, run_id: str, idempotency_key: str) -> OperationResultV3:
        self.v3_keys.append(idempotency_key)
        status = (self.status_answers.pop(0) if self.status_answers
                  else self.v3_final_status)
        result = (self.v3_final_result
                  if status in ("succeeded", "failed") else {})
        return _v3(idempotency_key, status, result)

    def await_world_op_v3(self, run_id: str, idempotency_key: str, submitted, *,
                          timeout_seconds: float = 30.0,
                          poll_interval_seconds: float = 0.4, poll=...):
        # Mirrors the real client: a non-positive budget returns the submitted
        # (still intermediate) result; otherwise poll to a terminal answer.
        if timeout_seconds <= 0:
            return submitted
        result = submitted
        polls = 0
        while result.status in ("accepted", "pending"):
            polls += 1
            if polls > 8:
                return result  # give up as pending; adapter must not claim success
            result = self.operation_status_v3(run_id, idempotency_key)
        return result

    # -- reads ------------------------------------------------------------------

    def world_read(self, run_id: str, operation: str, label: str, params: dict) -> dict:
        self.calls.append((f"world.{operation}", params))
        return self.reads.get(f"world.{operation}",
                              {"block": "minecraft:stone", "time_of_day": 6000,
                               "raining": False, "thundering": False, "count": 1})

    def mocap_state(self, run_id: str):
        from minecraft_film_agent.production_models import MocapStateV2

        return MocapStateV2.model_validate({"state": self.mocap})

    def mocap_transition(self, run_id: str, action: str, *, name: str | None = None):
        self.calls.append((f"mocap.{action}", {"name": name}))
        return _result(f"mocap-{action}", "applied", {"state": action})

    def operation_status(self, run_id: str, label: str, idempotency_key: str):
        return _result(label, "unknown")


def build_adapter(client: RecordingClient) -> LiveMinecraftAdapter:
    return LiveMinecraftAdapter(
        client, run_id="run-live", build_region=REGION,
        expected_save="Marx Video Test", expected_player="CineProbe",
        poll=lambda _seconds: None,
    )


# -- strict parsing -------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("time set 6000", ("set_time", {"value": 6000})),
        ("weather thunder 300", ("set_weather", {"weather": "thunder", "duration_seconds": 300})),
        ("weather thunder 300s", ("set_weather", {"weather": "thunder", "duration_seconds": 300})),
        ("setblock 1 64 2 minecraft:stone keep",
         ("set_block_keep", {"x": 1, "y": 64, "z": 2, "block": "minecraft:stone"})),
        ("summon minecraft:villager 3 64 4",
         ("summon", {"entity": "minecraft:villager", "x": 3, "y": 64, "z": 4})),
    ],
)
def test_compiler_owned_commands_parse(text: str, expected) -> None:
    assert parse_world_command(text) == expected


def test_fill_keep_parses() -> None:
    operation, params = parse_world_command(
        "fill 0 60 0 8 60 8 minecraft:stone keep")
    assert operation == "fill_keep"
    assert params["start"] == {"x": 0, "y": 60, "z": 0}
    assert params["end"] == {"x": 8, "y": 60, "z": 8}


def test_replace_placement_refused() -> None:
    assert parse_world_command("setblock 1 64 2 minecraft:stone replace") is None
    assert parse_world_command("fill 0 60 0 8 60 8 minecraft:stone replace") is None


def test_arbitrary_text_never_parses() -> None:
    assert parse_world_command("say injected free text") is None
    assert parse_world_command("tp @s 0 64 0") is None
    assert parse_world_command("setblock 1 64") is None


# -- expected target states (v3 weak-proof hole) ----------------------------------


def test_expected_target_state_parses_goals() -> None:
    assert expected_target_state(_command("set_time", "time set 6000")) == {
        "time_of_day": 6000}
    assert expected_target_state(_command("set_weather", "weather thunder 300")) == {
        "raining": True, "thundering": True}
    assert expected_target_state(_command("set_weather", "weather clear 300")) == {
        "raining": False, "thundering": False}
    assert expected_target_state(
        _command("set_block", "setblock 1 64 2 minecraft:stone keep")) == {
        "block": "minecraft:stone"}
    # fill/summon rely on the journaled proof, not a client-side read
    assert expected_target_state(
        _command("fill", "fill 0 60 0 8 60 8 minecraft:stone keep")) == {}
    assert expected_target_state(
        _command("summon", "summon minecraft:villager 3 64 4")) == {}


# -- typed dispatch ---------------------------------------------------------------


def test_execute_sends_typed_params_with_region_never_raw_text() -> None:
    client = RecordingClient()
    adapter = build_adapter(client)
    result = adapter.execute(_command("set_block", "setblock 1 64 2 minecraft:stone keep"))
    assert result.status == "applied"
    method, key, params = client.v3_calls[0]
    assert method == "world.set_block_keep"
    assert key == "plan-a000"  # the compiler's key travels unchanged
    assert params["x"] == 1 and params["block"] == "minecraft:stone"
    assert params["build_region"] == REGION
    # the raw text appears nowhere in the RPC params
    assert "setblock" not in str(params)
    # the status query used the SAME key
    assert client.v3_keys == ["plan-a000"]


def test_unparseable_command_is_rejected_not_forwarded() -> None:
    client = RecordingClient()
    adapter = build_adapter(client)
    result = adapter.execute(_command("runtime_control", "say something else"))
    assert result.status == "rejected"
    assert client.calls == [] and client.v3_calls == []


def test_succeeded_requires_the_journaled_proof() -> None:
    client = RecordingClient()
    adapter = build_adapter(client)
    client.v3_final_status = "succeeded"
    result = adapter.execute(_command("set_time", "time set 6000"))
    assert result.status == "applied"
    assert result.observed_state["proof"]["ok"] is True


def test_failed_journal_answer_stays_failed() -> None:
    client = RecordingClient()
    adapter = build_adapter(client)
    client.v3_final_status = "failed"
    client.v3_final_result = {"proof": {"ok": False, "reason": "mismatch"}}
    result = adapter.execute(_command("set_time", "time set 6000"))
    assert result.status == "failed"
    assert result.observed_state["proof"]["reason"] == "mismatch"


def test_conflict_is_not_reported_as_success() -> None:
    client = RecordingClient()
    adapter = build_adapter(client)
    client.v3_submit_status = "rejected"
    client.v3_final_status = "rejected"
    result = adapter.execute(_command("set_time", "time set 6000"))
    assert result.status == "rejected"


def test_accepted_then_succeeded_polls_to_terminal() -> None:
    client = RecordingClient()
    adapter = build_adapter(client)
    client.status_answers = ["pending", "succeeded"]
    client.v3_final_result = {"proof": {"ok": True, "time_of_day": 6000}}
    result = adapter.execute(_command("set_time", "time set 6000"))
    assert result.status == "applied"
    assert client.v3_keys == ["plan-a000", "plan-a000"]


def test_accepted_timeout_is_uncertain_never_applied() -> None:
    client = RecordingClient()
    adapter = LiveMinecraftAdapter(
        client, run_id="run-live", build_region=REGION,
        expected_save="Marx Video Test", expected_player="CineProbe",
        await_timeout_seconds=0.0, poll=lambda _seconds: None,
    )
    result = adapter.execute(_command("set_time", "time set 6000"))
    assert result.status == "uncertain"
    assert "operation status" in result.message


def test_unknown_with_matching_target_state_resolves_applied() -> None:
    client = RecordingClient()
    adapter = build_adapter(client)
    client.v3_final_status = "unknown"
    client.reads["world.get_time"] = {"time_of_day": 6000}  # matches "time set 6000"
    result = adapter.execute(_command("set_time", "time set 6000"))
    assert result.status == "applied"
    assert "target-state" in result.message


def test_unknown_with_wrong_world_state_stays_uncertain() -> None:
    """A readable world is NOT the goal state: time 8000 ≠ 6000 → uncertain."""

    client = RecordingClient()
    adapter = build_adapter(client)
    client.v3_final_status = "unknown"
    client.reads["world.get_time"] = {"time_of_day": 8000}
    result = adapter.execute(_command("set_time", "time set 6000"))
    assert result.status == "uncertain"
    assert result.observed_state["confirmed"] is False
    assert result.observed_state["expected"] == {"time_of_day": 6000}


def test_unknown_weather_confirmed_only_on_exact_match() -> None:
    client = RecordingClient()
    adapter = build_adapter(client)
    client.v3_final_status = "unknown"
    client.reads["world.get_weather"] = {"raining": False, "thundering": False}
    result = adapter.execute(_command("set_weather", "weather thunder 300"))
    assert result.status == "uncertain"  # readable ≠ thundering
    client.reads["world.get_weather"] = {"raining": True, "thundering": True}
    client.status_answers = ["unknown"]
    result = adapter.read_state(_command("set_weather", "weather thunder 300"))
    assert result["confirmed"] is True


# -- mocap (still contract 2) ------------------------------------------------------


def test_mocap_start_follows_the_two_step_live_machine() -> None:
    client = RecordingClient()
    adapter = build_adapter(client)

    client.mocap = "idle"
    adapter.execute(_command("mocap_recording_start", "mocap recording start"))
    assert client.calls[-1][0] == "mocap.prepare_recording"

    client.mocap = "waiting_for_selection"
    adapter.execute(_command("mocap_recording_start", "mocap recording start", index=1))
    assert client.calls[-1][0] == "mocap.confirm_recording_start"

    client.mocap = "recording"
    result = adapter.execute(_command("mocap_recording_start", "mocap recording start", index=2))
    assert result.status == "rejected"  # a third start is refused, never guessed


def test_save_carries_the_name() -> None:
    client = RecordingClient()
    client.mocap = "recorded_unsaved"
    adapter = build_adapter(client)
    adapter.execute(_command("mocap_recording_save", "mocap recording save take_01"))
    assert client.calls[-1] == ("mocap.save_recording", {"name": "take_01"})


# -- pre-write gate -----------------------------------------------------------------


def test_wrong_world_refuses_before_any_call() -> None:
    client = RecordingClient()
    client.state_payload = GameStateV2(
        session_phase=SessionPhase.IN_WORLD, save_name="Some Other Save",
        dimension="minecraft:overworld", player_name="CineProbe", paused=False,
    ).model_dump(mode="json")
    adapter = build_adapter(client)
    with pytest.raises(LiveAdapterError) as error:
        adapter.execute(_command("set_block", "setblock 1 64 2 minecraft:stone keep"))
    assert error.value.error_class is ErrorClass.WORLD_MISMATCH
    assert client.calls == [] and client.v3_calls == []  # nothing reached the bridge


def test_paused_game_refuses_writes() -> None:
    client = RecordingClient()
    client.state_payload = GameStateV2(
        session_phase=SessionPhase.IN_WORLD, save_name="Marx Video Test",
        dimension="minecraft:overworld", player_name="CineProbe", paused=True,
    ).model_dump(mode="json")
    adapter = build_adapter(client)
    with pytest.raises(LiveAdapterError, match="paused"):
        adapter.execute(_command("set_time", "time set 6000"))


def test_visual_weather_waits_for_gradient_without_rewriting():
    client=RecordingClient()
    adapter=build_adapter(client)
    client.reads['world.get_weather']={'raining':False,'thundering':False,'rain_gradient':.5,'thunder_gradient':0.}
    def settle(_): client.reads['world.get_weather']['rain_gradient']=0.
    adapter._poll=settle
    assert adapter.await_scene_weather(_command('set_weather','weather clear 60s'))['rain_gradient']==0.
    assert client.v3_calls==[]


def test_visual_weather_missing_gradient_fails_closed():
    client=RecordingClient();adapter=build_adapter(client)
    client.reads['world.get_weather']={'raining':False,'thundering':False}
    with pytest.raises(LiveAdapterError,match='visual weather read is unavailable'):
        adapter.await_scene_weather(_command('set_weather','weather clear 60s'))
