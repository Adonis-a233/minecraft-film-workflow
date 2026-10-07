from __future__ import annotations

from typing import Protocol

from .models import CommandResult, CompiledCommand, EnvironmentSnapshot


class MinecraftAdapter(Protocol):
    name: str
    dry_run: bool

    def get_status(self) -> dict[str, object]: ...

    def execute(self, command: CompiledCommand) -> CommandResult: ...

    def read_state(self, command: CompiledCommand) -> dict[str, object]: ...
    """Resolve the actual game state after a write, notably an uncertain one."""


class GameInspector(Protocol):
    """Read-only access to the running game; no write capability exists."""

    name: str
    read_only: bool

    def probe(self) -> dict[str, object]: ...

    def inspect_environment(self) -> EnvironmentSnapshot: ...


class BridgePort(Protocol):
    """Cinematic Bridge surface used by the production controller.

    Implementations: `CinematicBridgeClient` (real, loopback HTTP, contract
    v2) and `MockCinemaBridge` (offline simulation). Every method is
    deterministic per idempotency key: a retried write must never execute
    twice, and an unproven outcome is `unknown` — never `applied`.
    """

    name: str

    def handshake(self): ...
    """Return RuntimeVersions; the controller fail-closes on any mismatch."""

    def submit_timeline(self, request, timeline): ...

    def timeline_status(self, request): ...
    """Resolve an uncertain submission without re-executing it."""

    def await_replay_saved(self, request, timeline_id): ...

    def replace_camera_track(self, request, timeline_id, camera): ...

    def start_export(self, request, **kwargs): ...

    def export_status(self, request): ...

    # -- two-step Mocap state machine (plan v2 §Phase D/E) -------------------

    def mocap_prepare(self, request): ...
    """idle → waiting_for_selection; the FIRST start records nothing."""

    def mocap_confirm(self, request): ...
    """waiting_for_selection → recording; the SECOND start records."""

    def mocap_stop(self, request): ...

    def mocap_save(self, request, name): ...

    def mocap_status(self, request): ...

    def recording_path(self, name): ...
    """Where the saved `.mcmocap_rec` artifact lives for artifact proof."""


# -- backend-neutral photography chain (workflow v3 §5/§8) --------------------
#
# The controller plans against these protocols, never against a mod brand.
# A backend named 'none' in ProductionBackends means the port is unavailable:
# the stage must fail closed (SKIPPED/StageFailure), never simulate.


class RecorderPort(Protocol):
    """Records a take. Implementation today: the Mocap two-step machine
    (BridgePort.mocap_*); later: a ReplayMod recording binding."""

    def start_recording(self, request, run_id: str): ...

    def stop_recording(self, request, run_id: str): ...

    def save(self, request, name: str): ...

    def artifact_path(self, name): ...
    """Existing, complete artifact file for save proof — or None, which the
    controller treats as a failed stage (never a skipped proof)."""


class ReplayPort(Protocol):
    """Closes, stores and re-opens a recorded master (event master file).

    One master serves every camera: C1/C2 views reference the SAME replay
    artifact and event ticks (v3 §6) — no per-camera re-enactment.
    """

    def await_master_saved(self, request, master_id: str): ...

    def open_master(self, request, master_id: str): ...


class CameraPort(Protocol):
    """Applies one camera track to an OPEN master (no re-recording)."""

    def apply_track(self, request, master_id: str, camera): ...


class RendererPort(Protocol):
    """Renders the open master with the applied camera to a media file.
    Long-running: submit → poll → cancel; success requires a real,
    decodable artifact (media.py verification), never a skipped export."""

    def start_render(self, request, **kwargs): ...

    def render_status(self, request): ...

    def cancel_render(self, request): ...

