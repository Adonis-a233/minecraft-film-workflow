from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


RESOURCE_PATTERN = r"^[a-z0-9_.-]+:[a-z0-9_./-]+$"
SAFE_NAME_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"

# A scene must declare the volume it may change; per-fill caps stay lower.
MAX_REGION_BLOCKS = 262_144


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Position(StrictModel):
    x: int = Field(ge=-30_000_000, le=30_000_000)
    y: int = Field(ge=-64, le=319)
    z: int = Field(ge=-30_000_000, le=30_000_000)


class Region(StrictModel):
    """Closed axis-aligned box every world write of a scene must stay inside."""

    start: Position
    end: Position

    @staticmethod
    def _bounds(start: Position, end: Position) -> "tuple[int, int, int, int, int, int]":
        return (
            min(start.x, end.x),
            max(start.x, end.x),
            min(start.y, end.y),
            max(start.y, end.y),
            min(start.z, end.z),
            max(start.z, end.z),
        )

    @property
    def bounds(self) -> "tuple[int, int, int, int, int, int]":
        return self._bounds(self.start, self.end)

    @property
    def block_count(self) -> int:
        min_x, max_x, min_y, max_y, min_z, max_z = self.bounds
        return (max_x - min_x + 1) * (max_y - min_y + 1) * (max_z - min_z + 1)

    def contains(self, position: Position) -> bool:
        min_x, max_x, min_y, max_y, min_z, max_z = self.bounds
        return (
            min_x <= position.x <= max_x
            and min_y <= position.y <= max_y
            and min_z <= position.z <= max_z
        )

    def contains_box(self, start: Position, end: Position) -> bool:
        min_x, max_x, min_y, max_y, min_z, max_z = self.bounds
        other = self._bounds(start, end)
        return (
            other[0] >= min_x
            and other[1] <= max_x
            and other[2] >= min_y
            and other[3] <= max_y
            and other[4] >= min_z
            and other[5] <= max_z
        )


class Offset(StrictModel):
    x: int = Field(ge=-2048, le=2048)
    y: int = Field(ge=-2048, le=2048)
    z: int = Field(ge=-2048, le=2048)


class SetTimeAction(StrictModel):
    type: Literal["set_time"]
    value: int = Field(ge=0, le=24_000)


class SetWeatherAction(StrictModel):
    type: Literal["set_weather"]
    weather: Literal["clear", "rain", "thunder"]
    duration_seconds: int = Field(default=300, ge=1, le=86_400)


class SetBlockAction(StrictModel):
    type: Literal["set_block"]
    position: Position
    block: str = Field(pattern=RESOURCE_PATTERN)
    placement: Literal["keep", "replace"] = "keep"


class FillAction(StrictModel):
    type: Literal["fill"]
    start: Position
    end: Position
    block: str = Field(pattern=RESOURCE_PATTERN)
    placement: Literal["keep", "replace"] = "keep"

    @property
    def block_count(self) -> int:
        return (
            (abs(self.end.x - self.start.x) + 1)
            * (abs(self.end.y - self.start.y) + 1)
            * (abs(self.end.z - self.start.z) + 1)
        )


class SummonAction(StrictModel):
    type: Literal["summon"]
    entity: str = Field(pattern=RESOURCE_PATTERN)
    position: Position


class MocapRecordingStartAction(StrictModel):
    type: Literal["mocap_recording_start"]


class MocapRecordingStopAction(StrictModel):
    type: Literal["mocap_recording_stop"]


class MocapRecordingSaveAction(StrictModel):
    type: Literal["mocap_recording_save"]
    name: str = Field(pattern=SAFE_NAME_PATTERN)


class MocapPlaybackStartAction(StrictModel):
    type: Literal["mocap_playback_start"]
    name: str = Field(pattern=SAFE_NAME_PATTERN)


class MocapSceneCreateAction(StrictModel):
    type: Literal["mocap_scene_create"]
    scene: str = Field(pattern=SAFE_NAME_PATTERN)


class MocapSceneAddAction(StrictModel):
    type: Literal["mocap_scene_add"]
    scene: str = Field(pattern=SAFE_NAME_PATTERN)
    recording: str = Field(pattern=SAFE_NAME_PATTERN)
    delay_ticks: int = Field(default=0, ge=0, le=72_000)
    offset: Offset = Field(default_factory=lambda: Offset(x=0, y=0, z=0))
    player_name: str = Field(pattern=SAFE_NAME_PATTERN)


class MocapScenePlayAction(StrictModel):
    type: Literal["mocap_scene_play"]
    scene: str = Field(pattern=SAFE_NAME_PATTERN)


SceneAction = Annotated[
    SetTimeAction
    | SetWeatherAction
    | SetBlockAction
    | FillAction
    | SummonAction
    | MocapRecordingStartAction
    | MocapRecordingStopAction
    | MocapRecordingSaveAction
    | MocapPlaybackStartAction
    | MocapSceneCreateAction
    | MocapSceneAddAction
    | MocapScenePlayAction,
    Field(discriminator="type"),
]


class ScenePlan(StrictModel):
    schema_version: Literal[1] = 1
    plan_id: str = Field(pattern=SAFE_NAME_PATTERN)
    title: str = Field(min_length=1, max_length=120)
    world_name: str = Field(min_length=1, max_length=128)
    dimension: Literal["minecraft:overworld"] = "minecraft:overworld"
    objective: str = Field(min_length=1, max_length=1000)
    build_region: Region
    actions: list[SceneAction] = Field(min_length=1, max_length=200)
    expected_artifacts: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("world_name")
    @classmethod
    def world_name_must_not_be_a_path(cls, value: str) -> str:
        if any(token in value for token in ("/", "\\", "..")):
            raise ValueError("world_name must be a name, not a filesystem path")
        return value

    @field_validator("expected_artifacts")
    @classmethod
    def artifacts_must_be_relative(cls, values: list[str]) -> list[str]:
        for value in values:
            normalized = value.replace("\\", "/")
            if not normalized or normalized.startswith("/") or ":" in normalized:
                raise ValueError("expected artifact paths must be workspace-relative")
            if ".." in normalized.split("/"):
                raise ValueError("expected artifact paths may not traverse parents")
        return values

    @model_validator(mode="after")
    def build_region_must_be_bounded(self) -> "ScenePlan":
        if self.build_region.block_count > MAX_REGION_BLOCKS:
            raise ValueError(
                f"build_region covers {self.build_region.block_count} blocks; "
                f"limit is {MAX_REGION_BLOCKS}"
            )
        return self

    @model_validator(mode="after")
    def world_writes_stay_inside_build_region(self) -> "ScenePlan":
        for index, action in enumerate(self.actions):
            points: list[Position] = []
            box: tuple[Position, Position] | None = None
            if isinstance(action, SetBlockAction):
                points = [action.position]
            elif isinstance(action, FillAction):
                box = (action.start, action.end)
            elif isinstance(action, SummonAction):
                points = [action.position]
            else:
                continue
            if box is not None and not self.build_region.contains_box(*box):
                raise ValueError(
                    f"actions[{index}] {action.type} extends outside the declared "
                    "build_region"
                )
            for position in points:
                if not self.build_region.contains(position):
                    raise ValueError(
                        f"actions[{index}] {action.type} targets {position.model_dump_json()} "
                        "outside the declared build_region"
                    )
        return self

    @model_validator(mode="after")
    def mocap_save_names_must_be_unique(self) -> "ScenePlan":
        names = [
            action.name
            for action in self.actions
            if isinstance(action, MocapRecordingSaveAction)
        ]
        if len(names) != len(set(names)):
            raise ValueError("a plan may not save the same Mocap recording name twice")
        return self


class CompiledCommand(StrictModel):
    index: int = Field(ge=0)
    action_type: str
    command: str
    side_effect: Literal["world_write", "artifact_write", "runtime_control"]
    idempotency_key: str = Field(min_length=1, max_length=128)


class ValidatedPlan(StrictModel):
    plan: ScenePlan
    plan_sha256: str
    commands: list[CompiledCommand]
    warnings: list[str] = Field(default_factory=list)
    requires_human_approval: Literal[True] = True


class RunState(StrEnum):
    VALIDATED = "validated"
    APPROVED = "approved"
    DISPATCHING = "dispatching"
    COMPLETED = "completed"
    FAILED = "failed"


class RunManifest(StrictModel):
    run_id: str
    plan_id: str
    plan_sha256: str
    state: RunState
    created_at: datetime
    updated_at: datetime
    plan_file: str
    commands_file: str
    results_file: str
    approved_by: str | None = None
    approved_at: datetime | None = None
    adapter_name: str | None = None
    dry_run: bool = True
    error: str | None = None


class CommandResult(StrictModel):
    command_index: int
    status: Literal["applied", "rejected", "skipped", "failed", "uncertain"]
    message: str
    observed_at: datetime
    idempotency_key: str | None = None
    observed_state: dict[str, object] | None = None


class EnvironmentSnapshot(StrictModel):
    """Read-only evidence captured from the in-game bridge.

    Raw bridge payloads are kept verbatim so the snapshot remains reviewable
    even before the bridge schema is pinned by a live observation.
    """

    captured_at: datetime
    endpoint: str
    bridge_probe: dict[str, object]
    game_status: dict[str, object]
    entity_metrics: dict[str, object] | None = None
    warnings: list[str] = Field(default_factory=list)

