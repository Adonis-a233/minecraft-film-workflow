"""Domain models for the whole-film production chain (implementation plan P1).

These extend — never replace — the scene-level models in ``models.py``.
Everything here mirrors a JSON Schema in ``contracts/v1/``; the schema files
are the cross-language source of truth, and ``contracts.py`` re-validates the
pydantic output against them so the two cannot drift silently.

All timing is expressed in Minecraft ticks. Wall-clock durations and Python
``sleep()`` scheduling are deliberately unrepresentable in these models.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .models import StrictModel

SAFE_NAME = r"^[A-Za-z0-9_-]{1,64}$"


class StageName(StrEnum):
    """Chain stages. RECORD_TAKE (v1) was split (plan v2 §Phase E) so an
    unsaved Mocap take and a missing Flashback replay can never collapse
    into one ambiguous failure; checkpoints reflect real boundaries."""

    VALIDATE_PLAN = "validate_plan"
    PREPARE_SCENE = "prepare_scene"
    RESOLVE_ACTIONS = "resolve_actions"
    COMPOSE_TAKE = "compose_take"
    PREPARE_RECORDING = "prepare_recording"
    START_RECORDING = "start_recording"
    RUN_TIMELINE = "run_timeline"
    STOP_RECORDING = "stop_recording"
    SAVE_MOCAP = "save_mocap"
    AWAIT_REPLAY = "await_replay"
    APPLY_CAMERA = "apply_camera"
    EXPORT_SHOT = "export_shot"
    INSPECT_MEDIA = "inspect_media"
    APPROVE_FINAL = "approve_final"


STAGE_ORDER: list[StageName] = [
    StageName.VALIDATE_PLAN,
    StageName.PREPARE_SCENE,
    StageName.RESOLVE_ACTIONS,
    StageName.COMPOSE_TAKE,
    StageName.PREPARE_RECORDING,
    StageName.START_RECORDING,
    StageName.RUN_TIMELINE,
    StageName.STOP_RECORDING,
    StageName.SAVE_MOCAP,
    StageName.AWAIT_REPLAY,
    StageName.APPLY_CAMERA,
    StageName.EXPORT_SHOT,
    StageName.INSPECT_MEDIA,
    StageName.APPROVE_FINAL,
]


class StageStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class ErrorClass(StrEnum):
    """Failure taxonomy (architecture spec §8). A bare `failed` is never recorded."""

    VALIDATION_FAILED = "validation_failed"
    APPROVAL_REQUIRED = "approval_required"
    ENVIRONMENT_MISMATCH = "environment_mismatch"
    BRIDGE_UNAVAILABLE = "bridge_unavailable"
    AUTHENTICATION_FAILED = "authentication_failed"
    WORLD_MISMATCH = "world_mismatch"
    ASSET_MISSING = "asset_missing"
    OPERATION_REJECTED = "operation_rejected"
    OPERATION_TIMEOUT_UNKNOWN = "operation_timeout_unknown"
    GAME_CRASHED = "game_crashed"
    REPLAY_NOT_CREATED = "replay_not_created"
    EDITOR_NOT_READY = "editor_not_ready"
    EXPORT_FAILED = "export_failed"
    MEDIA_VALIDATION_FAILED = "media_validation_failed"
    MANUAL_INTERVENTION_REQUIRED = "manual_intervention_required"
    MOCAP_FEEDBACK_UNKNOWN = "mocap_feedback_unknown"
    OPERATION_CONFLICT = "operation_conflict"
    OPERATION_FAILED = "operation_failed"


class RetryScope(StrEnum):
    NONE = "none"  # never retried automatically
    STAGE = "stage"  # bounded backoff, same stage
    EXPORT_ONLY = "export_only"  # re-export; replay and world state untouched


class RetryPolicy(StrictModel):
    scope: RetryScope
    max_attempts: int = Field(ge=1, le=16)
    backoff_seconds: float = Field(ge=0, le=300)


RETRY_POLICIES: dict[ErrorClass, RetryPolicy] = {
    # Transient/unknown: bounded backoff; timeout-unknown resolution happens
    # through state reads before any resend, per architecture spec §9.
    ErrorClass.BRIDGE_UNAVAILABLE: RetryPolicy(scope=RetryScope.STAGE, max_attempts=5, backoff_seconds=1.0),
    ErrorClass.OPERATION_TIMEOUT_UNKNOWN: RetryPolicy(scope=RetryScope.STAGE, max_attempts=5, backoff_seconds=1.0),
    ErrorClass.GAME_CRASHED: RetryPolicy(scope=RetryScope.STAGE, max_attempts=1, backoff_seconds=0),
    # Media problems: only the export node may be retried, never the recording.
    ErrorClass.MEDIA_VALIDATION_FAILED: RetryPolicy(scope=RetryScope.EXPORT_ONLY, max_attempts=3, backoff_seconds=0),
    ErrorClass.EXPORT_FAILED: RetryPolicy(scope=RetryScope.EXPORT_ONLY, max_attempts=3, backoff_seconds=0),
    # A missing replay means the recording itself failed: re-record the take.
    ErrorClass.REPLAY_NOT_CREATED: RetryPolicy(scope=RetryScope.STAGE, max_attempts=2, backoff_seconds=0),
    # Everything else requires human or planner intervention.
    ErrorClass.VALIDATION_FAILED: RetryPolicy(scope=RetryScope.NONE, max_attempts=1, backoff_seconds=0),
    ErrorClass.APPROVAL_REQUIRED: RetryPolicy(scope=RetryScope.NONE, max_attempts=1, backoff_seconds=0),
    ErrorClass.ENVIRONMENT_MISMATCH: RetryPolicy(scope=RetryScope.NONE, max_attempts=1, backoff_seconds=0),
    ErrorClass.AUTHENTICATION_FAILED: RetryPolicy(scope=RetryScope.NONE, max_attempts=1, backoff_seconds=0),
    ErrorClass.WORLD_MISMATCH: RetryPolicy(scope=RetryScope.NONE, max_attempts=1, backoff_seconds=0),
    ErrorClass.ASSET_MISSING: RetryPolicy(scope=RetryScope.NONE, max_attempts=1, backoff_seconds=0),
    ErrorClass.OPERATION_REJECTED: RetryPolicy(scope=RetryScope.NONE, max_attempts=1, backoff_seconds=0),
    ErrorClass.EDITOR_NOT_READY: RetryPolicy(scope=RetryScope.NONE, max_attempts=1, backoff_seconds=0),
    ErrorClass.MANUAL_INTERVENTION_REQUIRED: RetryPolicy(scope=RetryScope.NONE, max_attempts=1, backoff_seconds=0),
    # Unrecognized game feedback must be investigated by a human, never retried.
    ErrorClass.MOCAP_FEEDBACK_UNKNOWN: RetryPolicy(scope=RetryScope.NONE, max_attempts=1, backoff_seconds=0),
}


class StageRecord(StrictModel):
    schema_version: Literal[1] = 1
    run_id: str
    stage: StageName
    attempt: int = Field(ge=1, le=16)
    status: StageStatus
    input_hash: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    output_path: str | None = None
    output_sha256: str | None = None
    evidence: dict[str, object] = Field(default_factory=dict)
    error_class: ErrorClass | None = None
    message: str | None = None
    recorded_at: datetime


class Vector3F(StrictModel):
    x: float
    y: float
    z: float


class TargetSpec(StrictModel):
    width: Literal[1280, 1920]
    height: Literal[720, 1080]
    fps: Literal[30, 60]
    codec: Literal["h264"]


class ActorCue(StrictModel):
    actor_id: str = Field(pattern=SAFE_NAME)
    skin_file: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,64}$")
    action_ref: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,64}$")
    start_tick: int = Field(ge=0, le=24_000)
    position: "tuple[int, int, int] | None" = None
    yaw: float | None = Field(default=None, ge=-180, le=180)


class RecordingRolls(StrictModel):
    pre_roll_ticks: int = Field(ge=0, le=600)
    post_roll_ticks: int = Field(ge=0, le=600)


class ShotPlan(StrictModel):
    shot_id: str = Field(pattern=SAFE_NAME)
    scene_id: str = Field(pattern=SAFE_NAME)
    title: str | None = Field(default=None, min_length=1, max_length=160)
    duration_ticks: int = Field(ge=1, le=24_000)
    actors: list[ActorCue] = Field(default_factory=list, max_length=32)
    camera_ref: str | None = Field(default=None, pattern=SAFE_NAME)
    recording: RecordingRolls


class ProductionScene(StrictModel):
    scene_id: str = Field(pattern=SAFE_NAME)
    world_ref: str = Field(min_length=1, max_length=128)
    blueprint_ref: str | None = Field(
        default=None, pattern=r"^assets/blueprints/[A-Za-z0-9_./-]+\.json$"
    )
    shots: list[ShotPlan] = Field(min_length=1, max_length=128)


class ProductionPlan(StrictModel):
    """Whole-film plan. References validated sub-plans; no free-text actions."""

    schema_version: Literal[1] = 1
    production_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    title: str | None = Field(default=None, min_length=1, max_length=160)
    minecraft_version: Literal["1.21.1"] = "1.21.1"
    fabric_loader: Literal["0.19.3"] = "0.19.3"
    target: TargetSpec
    scenes: list[ProductionScene] = Field(min_length=1, max_length=64)

    @property
    def shots(self) -> list[ShotPlan]:
        return [shot for scene in self.scenes for shot in scene.shots]


class TimelineEvent(StrictModel):
    tick: int = Field(ge=0, le=24_000)
    type: str
    payload: dict[str, object] = Field(default_factory=dict)
    note: str | None = Field(default=None, max_length=200)


class TimelinePlan(StrictModel):
    schema_version: Literal[1] = 1
    timeline_id: str = Field(pattern=SAFE_NAME)
    shot_id: str | None = Field(default=None, pattern=SAFE_NAME)
    world_name: str | None = Field(default=None, min_length=1, max_length=128)
    total_ticks: int = Field(ge=1, le=24_000)
    events: list[TimelineEvent] = Field(min_length=2, max_length=512)


class CameraKeyframe(StrictModel):
    tick: int = Field(ge=0, le=24_000)
    position: "tuple[float, float, float]"
    yaw: float = Field(ge=-180, le=180)
    pitch: float = Field(ge=-90, le=90)
    roll: float = Field(default=0.0, ge=-180, le=180)
    fov: float = Field(ge=1, le=150)


class CameraTrack(StrictModel):
    schema_version: Literal[1] = 1
    camera_track_id: str = Field(pattern=SAFE_NAME)
    shot_id: str | None = Field(default=None, pattern=SAFE_NAME)
    coordinate_space: Literal["world"] = "world"
    interpolation: Literal["linear", "smooth"] = "smooth"
    keyframes: list[CameraKeyframe] = Field(min_length=2, max_length=512)


class TickRange(StrictModel):
    start_tick: int = Field(ge=0, le=24_000)
    end_tick: int = Field(ge=1, le=24_001)


class ExportPlan(StrictModel):
    schema_version: Literal[1] = 1
    export_id: str = Field(pattern=SAFE_NAME)
    shot_id: str = Field(pattern=SAFE_NAME)
    timeline_id: str = Field(pattern=SAFE_NAME)
    replay_ref: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,64}$")
    range: TickRange
    output: TargetSpec
    output_path: str = Field(pattern=r"^assets/renders/[A-Za-z0-9_./-]+\.mp4$")

    @property
    def duration_ticks(self) -> int:
        return self.range.end_tick - self.range.start_tick


class ActionInteraction(StrictModel):
    tick: int = Field(ge=0)
    type: str = Field(min_length=1, max_length=64)


class ActionMetadata(StrictModel):
    recording_id: str = Field(pattern=SAFE_NAME)
    title: str | None = Field(default=None, max_length=160)
    source_file: str = Field(pattern=r"^(assets|work)/[A-Za-z0-9_./ -]+$")
    duration_ticks: int = Field(ge=1, le=24_000)
    start_pose: str = Field(default="unknown", max_length=64)
    end_pose: str = Field(default="unknown", max_length=64)
    translation: Vector3F | None = None
    mirrorable: bool = False
    loopable: bool = False
    interactions: list[ActionInteraction] = Field(default_factory=list, max_length=64)
    source: Literal["human_recorded", "programmatic", "imported"]
    verified: bool


class ActionResolution(StrictModel):
    action_ref: str
    recording_id: str
    source_file: str
    verified: bool


class MissingAssetReport(StrictModel):
    """`missing` is blocking: the run stops at asset_missing, no improvisation."""

    resolved: list[ActionResolution] = Field(default_factory=list)
    unverified: list[ActionResolution] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.missing


class OperationRequest(StrictModel):
    schema_version: Literal[1] = 1
    run_id: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,80}$")
    operation_id: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,80}$")
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9_./:-]+$")
    plan_hash: str | None = Field(default=None, pattern=r"^sha256:[a-f0-9]{64}$")
    method: str
    params: dict[str, object] = Field(default_factory=dict)


class OperationResult(StrictModel):
    schema_version: Literal[1] = 1
    operation_id: str
    idempotency_key: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_./:-]+$")
    status: Literal["applied", "rejected", "running", "unknown", "failed"]
    message: str | None = Field(default=None, max_length=1000)
    error_class: ErrorClass | None = None
    result: dict[str, object] = Field(default_factory=dict)


class RuntimeVersions(StrictModel):
    minecraft: str
    fabric_loader: str
    flashback: str
    mocap: str
    bridge: str
    contract: int = Field(ge=1)


PINNED_VERSIONS = {
    "minecraft": "1.21.1",
    "fabric_loader": "0.19.3",
    "flashback": "0.39.8",
    "mocap": "1.3.10",
}


# -- contract v2 domain models (plan v2 §Phases A–D) -------------------------


class SessionPhase(StrEnum):
    MAIN_MENU = "main_menu"
    LOADING_WORLD = "loading_world"
    IN_WORLD = "in_world"
    REPLAY_EDITOR = "replay_editor"
    EXPORTING = "exporting"


class GameStateV2(StrictModel):
    """Truthful client state; mirrors contracts/v2/game-state.schema.json.

    ``save_name`` is the integrated-save name — never a dimension registry
    key. ``None`` means not applicable or not proven in the current phase.
    """

    schema_version: Literal[2] = 2
    session_phase: SessionPhase
    save_name: str | None = Field(default=None, max_length=128)
    dimension: str | None = Field(default=None, max_length=128)
    player_name: str | None = Field(default=None, max_length=64)
    paused: bool
    client_tick: int | None = Field(default=None, ge=0)
    blocking_screen: bool | None = None
    screen_class: str | None = Field(default=None, max_length=200)

    def pre_write_gate(
        self,
        *,
        expected_save: str,
        expected_dimension: str,
        expected_player: str,
    ) -> str | None:
        """Return a refusal reason, or None when writes are provably safe."""

        if self.session_phase is not SessionPhase.IN_WORLD:
            return f"session_phase is {self.session_phase.value}, expected in_world"
        if self.save_name != expected_save:
            return f"save_name is {self.save_name!r}, expected {expected_save!r}"
        if self.dimension != expected_dimension:
            return f"dimension is {self.dimension!r}, expected {expected_dimension!r}"
        if self.player_name != expected_player:
            return f"player_name is {self.player_name!r}, expected {expected_player!r}"
        if self.paused:
            return "game is paused"
        if self.blocking_screen:
            return "blocking screen is active"
        return None


class MocapPhase(StrEnum):
    IDLE = "idle"
    WAITING_FOR_SELECTION = "waiting_for_selection"
    RECORDING = "recording"
    RECORDED_UNSAVED = "recorded_unsaved"
    SAVED = "saved"
    DISCARDED = "discarded"
    REJECTED = "rejected"
    UNKNOWN = "unknown"


class MocapArtifact(StrictModel):
    name: str = Field(pattern=SAFE_NAME)
    bytes: int = Field(ge=0)
    sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class MocapStateV2(StrictModel):
    """Observed Mocap recorder state; mirrors contracts/v2/mocap-state.schema.json."""

    schema_version: Literal[2] = 2
    state: MocapPhase
    recording_name: str | None = Field(default=None, max_length=64)
    last_feedback: str | None = Field(default=None, max_length=500)
    last_feedback_key: str | None = Field(default=None, max_length=200)
    artifact: MocapArtifact | None = None


class JournalState(StrEnum):
    """Producer-side operation journal lifecycle (plan v2 §Phase B)."""

    ACCEPTED = "accepted"
    QUEUED = "queued"
    DISPATCHED = "dispatched"
    OBSERVED = "observed"
    REJECTED = "rejected"
    UNKNOWN = "unknown"


class JournalStateV3(StrEnum):
    """Persistent journal lifecycle (workflow v3 §4): accepted → queued →
    running → succeeded | failed | unknown. Terminal states survive process
    restarts; UNKNOWN (including restart-recovered work) blocks dependents."""

    ACCEPTED = "accepted"
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNKNOWN = "unknown"


class OperationRequestV3(StrictModel):
    """Contract-3 envelope. The idempotency_key is generated ONCE upstream and
    travels unchanged; world writes return `accepted` before game execution."""

    schema_version: Literal[3] = 3
    run_id: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,80}$")
    operation_id: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,80}$")
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9_./:-]+$")
    plan_hash: str | None = Field(default=None, pattern=r"^sha256:[a-f0-9]{64}$")
    method: str
    params: dict[str, object] = Field(default_factory=dict)


class OperationResultV3(StrictModel):
    """Contract-3 reply. `accepted` is durable-journal + queued, NOT a
    completion; resolve world writes through status polling to
    succeeded/failed/unknown."""

    schema_version: Literal[3] = 3
    operation_id: str
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9_./:-]+$")
    status: Literal[
        "accepted", "pending", "succeeded", "failed", "rejected", "unknown", "applied"
    ]
    journal_state: JournalStateV3 | None = None
    message: str | None = Field(default=None, max_length=1000)
    error_class: ErrorClass | None = None
    result: dict[str, object] = Field(default_factory=dict)


class OperationRequestV2(StrictModel):
    """Contract-2 envelope. Write retries must repeat the same key."""

    schema_version: Literal[2] = 2
    run_id: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,80}$")
    operation_id: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,80}$")
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9_./:-]+$")
    plan_hash: str | None = Field(default=None, pattern=r"^sha256:[a-f0-9]{64}$")
    method: str
    params: dict[str, object] = Field(default_factory=dict)


class OperationResultV2(StrictModel):
    """Contract-2 reply: idempotency_key is REQUIRED (failure F1)."""

    schema_version: Literal[2] = 2
    operation_id: str
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9_./:-]+$")
    status: Literal[
        "applied", "rejected", "queued", "running", "observed", "unknown", "failed"
    ]
    journal_state: JournalState | None = None
    message: str | None = Field(default=None, max_length=1000)
    error_class: ErrorClass | None = None
    result: dict[str, object] = Field(default_factory=dict)


class WorldWriteLimits(StrictModel):
    max_per_fill: int = Field(ge=1)
    max_region_blocks: int = Field(ge=1)


class CapabilitiesV2(StrictModel):
    """Runtime capability advertisement; the pre-write preflight reads this."""

    contract: Literal[2] = 2
    minecraft: str
    fabric_loader: str
    flashback: str
    mocap: str
    bridge: str
    typed_world_ops: bool
    world_reads: bool
    mocap_state_machine: bool
    tick_scheduler: bool
    flashback_automation: bool
    pause_gated_scheduler: bool = False
    flashback_disabled_reason: str = ""
    world_write_limits: WorldWriteLimits | None = None

    def runtime_mismatches(self) -> list[str]:
        issues: list[str] = []
        actual = {
            "minecraft": self.minecraft,
            "fabric_loader": self.fabric_loader,
            "flashback": self.flashback,
            "mocap": self.mocap,
        }
        for field, expected in PINNED_VERSIONS.items():
            if actual[field] != expected:
                issues.append(f"{field}: expected {expected!r}, bridge reports {actual[field]!r}")
        return issues

    def missing_for_mocap_only(self) -> list[str]:
        missing: list[str] = []
        for flag in ("typed_world_ops", "world_reads", "mocap_state_machine", "tick_scheduler"):
            if not getattr(self, flag):
                missing.append(flag)
        return missing


class ShotBundle(StrictModel):
    """Everything the deterministic chain needs to produce one shot."""

    shot: ShotPlan
    world_name: str
    timeline: TimelinePlan
    camera: CameraTrack | None = None
    export_plan: ExportPlan | None = None

    @model_validator(mode="after")
    def export_matches_shot(self) -> "ShotBundle":
        if self.export_plan is not None:
            if self.export_plan.timeline_id != self.timeline.timeline_id:
                raise ValueError("export_plan.timeline_id does not match the timeline")
            end = self.timeline.total_ticks
            if self.export_plan.range.start_tick < 0 or self.export_plan.range.end_tick > end:
                raise ValueError("export range escapes the recorded timeline")
        return self


# -- backend-neutral photography chain (workflow v3 §5/§8) --------------------


BackendName = Literal["mocap", "replaymod", "flashback", "none"]


class CapabilitiesV3(StrictModel):
    """Contract-3 capability advertisement: adds the backend-neutral
    photography names on top of the v2 capability set (see
    contracts/v3/capabilities.schema.json). The controller plans against
    these names, never against a mod brand."""

    contract: Literal[3] = 3
    minecraft: str
    fabric_loader: str
    flashback: str
    mocap: str
    bridge: str
    typed_world_ops: bool
    world_reads: bool
    mocap_state_machine: bool
    tick_scheduler: bool
    flashback_automation: bool
    pause_gated_scheduler: bool = False
    flashback_disabled_reason: str = ""
    world_write_limits: WorldWriteLimits | None = None
    recorder_backend: Literal["mocap", "none"]
    replay_backend: Literal["replaymod", "flashback", "none"]
    camera_backend: Literal["replaymod", "flashback", "none"]
    render_backend: Literal["replaymod", "none"]
    actor_backend: Literal["carpet", "none"] = "none"
    async_world_writes: bool = False
    persistent_journal: bool = False

    @classmethod
    def from_v2(cls, v2: "CapabilitiesV2") -> "CapabilitiesV3":
        """Derives the v3 view from a v2 advertisement: Mocap recording is
        the only recorder; replay/camera/render stay closed unless a backend
        explicitly advertises itself (today: never — Flashback is license-
        gated off and ReplayMod has no bridge binding yet)."""

        return cls(
            minecraft=v2.minecraft,
            fabric_loader=v2.fabric_loader,
            flashback=v2.flashback,
            mocap=v2.mocap,
            bridge=v2.bridge,
            typed_world_ops=v2.typed_world_ops,
            world_reads=v2.world_reads,
            mocap_state_machine=v2.mocap_state_machine,
            tick_scheduler=v2.tick_scheduler,
            flashback_automation=v2.flashback_automation,
            pause_gated_scheduler=v2.pause_gated_scheduler,
            flashback_disabled_reason=v2.flashback_disabled_reason,
            world_write_limits=v2.world_write_limits,
            recorder_backend="mocap" if v2.mocap_state_machine else "none",
            replay_backend="flashback" if v2.flashback_automation else "none",
            camera_backend="flashback" if v2.flashback_automation else "none",
            render_backend="none",
            async_world_writes=True,
            persistent_journal=True,
        )

    def runtime_mismatches(self) -> list[str]:
        issues: list[str] = []
        actual = {
            "minecraft": self.minecraft,
            "fabric_loader": self.fabric_loader,
            "flashback": self.flashback,
            "mocap": self.mocap,
        }
        for field, expected in PINNED_VERSIONS.items():
            if actual[field] != expected:
                issues.append(f"{field}: expected {expected!r}, bridge reports {actual[field]!r}")
        return issues

    def missing_for_mocap_only(self) -> list[str]:
        missing: list[str] = []
        for flag in ("typed_world_ops", "world_reads", "mocap_state_machine", "tick_scheduler"):
            if not getattr(self, flag):
                missing.append(flag)
        return missing


class ProductionBackends(StrictModel):
    """The four photography capabilities the controller needs, named without
    a brand (workflow v3 §8: 摄影能力与 flashback 专属名称解耦). 'none'
    means the stage MUST fail closed — there is no fallback to simulation."""

    recorder: BackendName = "none"
    replay: BackendName = "none"
    camera: BackendName = "none"
    renderer: BackendName = "none"

    @classmethod
    def from_capabilities(cls, capabilities) -> "ProductionBackends":
        if hasattr(capabilities, "replay_backend"):  # CapabilitiesV3
            return cls(
                recorder=capabilities.recorder_backend,
                replay=capabilities.replay_backend,
                camera=capabilities.camera_backend,
                renderer=capabilities.render_backend,
            )
        return cls.from_v2_capabilities(capabilities)

    @classmethod
    def from_v2_capabilities(cls, v2: "CapabilitiesV2") -> "ProductionBackends":
        return cls(
            recorder="mocap" if v2.mocap_state_machine else "none",
            replay="flashback" if v2.flashback_automation else "none",
            camera="flashback" if v2.flashback_automation else "none",
            renderer="none",
        )

    def unavailable(self) -> list[str]:
        return [
            name for name in ("recorder", "replay", "camera", "renderer")
            if getattr(self, name) == "none"
        ]
