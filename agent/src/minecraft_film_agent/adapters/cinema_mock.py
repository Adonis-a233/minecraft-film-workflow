"""Offline simulation of the Cinematic Bridge (plan P1 mock set).

Simulates, deterministically and in-process:

- tick timeline submission with idempotent replays;
- replay file creation after the flashback stop event;
- camera track replacement against an opened replay;
- export job producing a syntactically valid MP4 (parsed by ``video.py``);
- failure injection: lost responses (unknown outcomes), export failures,
  camera failures, and version mismatches for the fail-closed gate.

It never touches Minecraft. Its MP4s are minimal containers crafted for the
probe — they are not real video, and nothing downstream may treat them as
aesthetic evidence.
"""

from __future__ import annotations

import hashlib
import struct
from pathlib import Path

from ..contracts import canonical_json
from ..mocap_live import MocapFeedbackClass
from ..production_models import (
    CameraTrack,
    ErrorClass,
    MocapPhase,
    OperationRequest,
    OperationResult,
    RuntimeVersions,
    TimelinePlan,
)


def _box(box_type: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", 8 + len(payload)) + box_type + payload


def synth_mp4(*, width: int, height: int, duration_ticks: int, fps: int) -> bytes:
    """Minimal MP4: ftyp + moov(mvhd, trak(mdia(minf(stbl(stsd(avc1 w h))))))."""

    seconds = duration_ticks / 20.0
    timescale = fps * 1000
    duration = int(seconds * timescale)

    ftyp = _box(b"ftyp", b"isom\x00\x00\x02\x00isomiso2")

    mvhd_payload = (
        b"\x00" * 4  # version 0 + flags
        + b"\x00" * 8  # creation + modification time
        + struct.pack(">II", timescale, duration)
        + b"\x00" * 80  # rate/volume/matrix/next-id fields
    )
    stsd_entry = (
        struct.pack(">I", 78)
        + b"avc1"
        + b"\x00" * 24
        + struct.pack(">HH", width, height)
        + b"\x00" * 40
    )
    stsd_payload = b"\x00" * 4 + struct.pack(">I", 1) + stsd_entry
    stbl = _box(b"stbl", _box(b"stsd", stsd_payload))
    mdia = _box(b"mdia", _box(b"minf", stbl))
    trak = _box(b"trak", mdia)
    moov = _box(b"moov", _box(b"mvhd", mvhd_payload) + trak)
    return ftyp + moov


class MockCinemaBridge:
    """In-memory bridge implementing the BridgePort surface.

    An idempotency key that was already executed never executes again: a
    retry of a lost response returns ``applied`` (the recorded outcome), and
    ``timeline_status`` can always resolve an ``unknown`` without re-running.
    """

    name = "cinematic-bridge-sim"
    dry_run = True  # simulation only

    def __init__(
        self,
        workspace_root: Path,
        *,
        versions: RuntimeVersions | None = None,
        lose_first_response: "set[str] | None" = None,
        fail_export: bool = False,
        fail_camera: bool = False,
        expected_world: str | None = None,
    ):
        self.workspace_root = workspace_root.resolve()
        self.replays_dir = self.workspace_root / "work" / "cinema-sim" / "replays"
        self.recordings_dir = self.workspace_root / "work" / "cinema-sim" / "recordings"
        self.versions = versions or RuntimeVersions(
            minecraft="1.21.1",
            fabric_loader="0.19.3",
            flashback="0.39.8",
            mocap="1.3.10",
            bridge="0.1.0-sim",
            contract=1,
        )
        self._lose = set(lose_first_response or ())
        self.fail_export = fail_export
        self.fail_camera = fail_camera
        self.expected_world = expected_world
        self._results: dict[str, OperationResult] = {}
        self._timelines: dict[str, TimelinePlan] = {}
        self._cameras: dict[str, CameraTrack] = {}
        self.executed_operations: list[str] = []
        # two-step Mocap recorder simulation (failure F6 made testable offline)
        self._mocap_phase = MocapPhase.IDLE
        self._mocap_feedback: list[MocapFeedbackClass] = []
        self._mocap_name: str | None = None

    # -- evidence paths ------------------------------------------------------

    def replay_path(self, timeline_id: str) -> Path:
        return self.replays_dir / f"{timeline_id}.flashback_replay"

    def render_path(self, relative_output: str) -> Path:
        return self.workspace_root / relative_output

    # -- BridgePort ----------------------------------------------------------

    def handshake(self) -> RuntimeVersions:
        return self.versions.model_copy()

    def _result(
        self,
        request: OperationRequest,
        status: str,
        message: str,
        *,
        error_class: ErrorClass | None = None,
        result: dict[str, object] | None = None,
        remember: bool = True,
    ) -> OperationResult:
        payload = OperationResult(
            schema_version=1,
            operation_id=request.operation_id,
            idempotency_key=request.idempotency_key,
            status=status,  # type: ignore[arg-type]
            message=message,
            error_class=error_class,
            result=result or {},
        )
        if remember:
            self._results.setdefault(request.idempotency_key, payload)
        return payload

    def submit_timeline(
        self, request: OperationRequest, timeline: TimelinePlan
    ) -> OperationResult:
        cached = self._results.get(request.idempotency_key)
        if cached is not None:
            if cached.status == "unknown":
                # The write landed the first time; the retry observes that.
                return cached.model_copy(
                    update={
                        "status": "applied",
                        "message": cached.message + " (idempotent retry: already applied)",
                    }
                )
            return cached.model_copy()

        world = next(
            (
                event.payload.get("world")
                for event in timeline.events
                if event.type == "assert_state"
            ),
            None,
        )
        if self.expected_world is not None and world != self.expected_world:
            return self._result(
                request,
                "rejected",
                f"world is {world!r}, expected {self.expected_world!r}",
                error_class=ErrorClass.WORLD_MISMATCH,
            )

        self._timelines[request.operation_id] = timeline
        payload = b"CINEMATIC-BRIDGE-SIM-REPLAY v1\n" + canonical_json(
            timeline.model_dump(mode="json")
        ).encode("utf-8")
        self.replays_dir.mkdir(parents=True, exist_ok=True)
        self.replay_path(timeline.timeline_id).write_bytes(payload)
        message = "timeline executed on the simulated main thread"
        if request.idempotency_key in self._lose:
            # Write lands, response is lost: the first reply is `unknown`.
            return self._result(request, "unknown", message + " (response lost)")
        return self._result(
            request,
            "applied",
            message,
            result={"replay": self.replay_path(timeline.timeline_id).name},
        )

    def timeline_status(self, request: OperationRequest) -> OperationResult:
        timeline = self._timelines.get(request.operation_id)
        if timeline is None:
            return self._result(
                request,
                "unknown",
                "no such operation on the bridge",
                error_class=ErrorClass.OPERATION_TIMEOUT_UNKNOWN,
                remember=False,
            )
        return self._result(
            request,
            "applied",
            "timeline executed on the simulated main thread",
            result={"replay": self.replay_path(timeline.timeline_id).name},
            remember=False,
        )

    def await_replay_saved(self, request: OperationRequest, timeline_id: str) -> OperationResult:
        path = self.replay_path(timeline_id)
        if not path.is_file():
            return self._result(
                request,
                "failed",
                f"replay never appeared: {path.name}",
                error_class=ErrorClass.REPLAY_NOT_CREATED,
                remember=False,
            )
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return self._result(
            request,
            "applied",
            "replay saved",
            result={"replay": path.name, "sha256": f"sha256:{digest}", "bytes": path.stat().st_size},
            remember=False,
        )

    def replace_camera_track(
        self, request: OperationRequest, timeline_id: str, camera: CameraTrack
    ) -> OperationResult:
        if not self.replay_path(timeline_id).is_file():
            return self._result(
                request,
                "rejected",
                f"replay {timeline_id} is not open in the simulated editor",
                error_class=ErrorClass.EDITOR_NOT_READY,
            )
        if self.fail_camera:
            return self._result(
                request,
                "failed",
                "simulated editor rejected the camera track",
                error_class=ErrorClass.EDITOR_NOT_READY,
            )
        self._cameras[timeline_id] = camera
        return self._result(
            request,
            "applied",
            "camera track replaced",
            result={"keyframes": len(camera.keyframes)},
        )

    def start_export(
        self,
        request: OperationRequest,
        *,
        timeline_id: str,
        range_ticks: "tuple[int, int]",
        output_relative: str,
        width: int,
        height: int,
        fps: int,
    ) -> OperationResult:
        self.executed_operations.append(request.idempotency_key)
        if self.fail_export:
            return self._result(
                request,
                "failed",
                "simulated encoder failure",
                error_class=ErrorClass.EXPORT_FAILED,
            )
        target = self.render_path(output_relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(
            synth_mp4(
                width=width,
                height=height,
                duration_ticks=range_ticks[1] - range_ticks[0],
                fps=fps,
            )
        )
        return self._result(
            request,
            "applied",
            "export completed",
            result={"output": output_relative, "bytes": target.stat().st_size},
        )

    def export_status(self, request: OperationRequest) -> OperationResult:
        return self._result(
            request,
            "applied",
            "no export in flight (simulation completes inline)",
            remember=False,
        )

    # -- Mocap state machine simulation (two-step start; failure F6) ----------

    def recording_path(self, name: str) -> Path:
        return self.recordings_dir / f"{name}.mcmocap_rec"

    def _mocap_result(
        self, request: OperationRequest, phase: MocapPhase, feedback: MocapFeedbackClass
    ) -> OperationResult:
        self._mocap_phase = phase
        self._mocap_feedback.append(feedback)
        return self._result(
            request,
            "applied",
            f"simulated mocap feedback: {feedback.value}",
            result={"state": phase.value, "feedback": feedback.value},
        )

    def mocap_prepare(self, request: OperationRequest) -> OperationResult:
        if self._mocap_phase not in (MocapPhase.IDLE, MocapPhase.SAVED,
                                     MocapPhase.DISCARDED, MocapPhase.REJECTED):
            return self._result(
                request, "rejected",
                f"recorder is {self._mocap_phase.value}; prepare needs an idle recorder",
                error_class=ErrorClass.OPERATION_REJECTED,
            )
        return self._mocap_result(request, MocapPhase.WAITING_FOR_SELECTION,
                                  MocapFeedbackClass.WAITING_FOR_SELECTION)

    def mocap_confirm(self, request: OperationRequest) -> OperationResult:
        if self._mocap_phase is not MocapPhase.WAITING_FOR_SELECTION:
            return self._result(
                request, "rejected",
                "confirm requires waiting_for_selection (the live two-step start)",
                error_class=ErrorClass.OPERATION_REJECTED,
            )
        return self._mocap_result(request, MocapPhase.RECORDING,
                                  MocapFeedbackClass.RECORDING_STARTED)

    def mocap_stop(self, request: OperationRequest) -> OperationResult:
        if self._mocap_phase is MocapPhase.RECORDING:
            return self._mocap_result(request, MocapPhase.RECORDED_UNSAVED,
                                      MocapFeedbackClass.RECORDING_STOPPED)
        if self._mocap_phase is MocapPhase.WAITING_FOR_SELECTION:
            return self._mocap_result(request, MocapPhase.IDLE,
                                      MocapFeedbackClass.WAITING_CANCELLED)
        return self._result(request, "rejected", "nothing to stop",
                            error_class=ErrorClass.OPERATION_REJECTED)

    def mocap_save(self, request: OperationRequest, name: str) -> OperationResult:
        if self._mocap_phase is not MocapPhase.RECORDED_UNSAVED:
            return self._result(
                request, "rejected",
                "save requires recorded_unsaved (the live run proved empty saves are rejected)",
                error_class=ErrorClass.OPERATION_REJECTED,
            )
        target = self.recording_path(name)
        if target.exists():
            return self._result(
                request, "rejected",
                f"recording already exists; never overwrite: {target.name}",
                error_class=ErrorClass.OPERATION_REJECTED,
            )
        self.recordings_dir.mkdir(parents=True, exist_ok=True)
        target.write_bytes(
            b"CINEMATIC-BRIDGE-SIM-MOCAP v1\n"
            + canonical_json({"name": name}).encode("utf-8")
        )
        result = self._mocap_result(request, MocapPhase.SAVED, MocapFeedbackClass.SAVE_SUCCESS)
        self._mocap_name = name
        return result

    def mocap_status(self, request: OperationRequest) -> OperationResult:
        return self._result(
            request,
            "applied",
            "simulated recorder state",
            result={"state": self._mocap_phase.value},
            remember=False,
        )

    # -- introspection for tests ---------------------------------------------

    def camera_for(self, timeline_id: str) -> CameraTrack | None:
        return self._cameras.get(timeline_id)
