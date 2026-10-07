from __future__ import annotations

import hashlib

from .models import (
    CompiledCommand,
    FillAction,
    MocapPlaybackStartAction,
    MocapRecordingSaveAction,
    MocapRecordingStartAction,
    MocapRecordingStopAction,
    MocapSceneAddAction,
    MocapSceneCreateAction,
    MocapScenePlayAction,
    ScenePlan,
    SetBlockAction,
    SetTimeAction,
    SetWeatherAction,
    SummonAction,
    ValidatedPlan,
)


class PlanValidationError(ValueError):
    def __init__(self, issues: list[str]):
        self.issues = issues
        super().__init__("; ".join(issues))


def _position(position: object) -> str:
    return f"{position.x} {position.y} {position.z}"  # type: ignore[attr-defined]


def _compile_action(index: int, action: object, *, plan_id: str) -> CompiledCommand:
    if isinstance(action, SetTimeAction):
        command = f"time set {action.value}"
        side_effect = "world_write"
    elif isinstance(action, SetWeatherAction):
        command = f"weather {action.weather} {action.duration_seconds}s"
        side_effect = "world_write"
    elif isinstance(action, SetBlockAction):
        command = f"setblock {_position(action.position)} {action.block} {action.placement}"
        side_effect = "world_write"
    elif isinstance(action, FillAction):
        command = (
            f"fill {_position(action.start)} {_position(action.end)} "
            f"{action.block} {action.placement}"
        )
        side_effect = "world_write"
    elif isinstance(action, SummonAction):
        command = f"summon {action.entity} {_position(action.position)}"
        side_effect = "world_write"
    elif isinstance(action, MocapRecordingStartAction):
        command = "mocap recording start"
        side_effect = "runtime_control"
    elif isinstance(action, MocapRecordingStopAction):
        command = "mocap recording stop"
        side_effect = "runtime_control"
    elif isinstance(action, MocapRecordingSaveAction):
        command = f"mocap recording save {action.name}"
        side_effect = "artifact_write"
    elif isinstance(action, MocapPlaybackStartAction):
        command = f"mocap playing start {action.name}"
        side_effect = "runtime_control"
    elif isinstance(action, MocapSceneCreateAction):
        command = f"mocap scenes add {action.scene}"
        side_effect = "artifact_write"
    elif isinstance(action, MocapSceneAddAction):
        command = (
            f"mocap scenes addTo {action.scene} {action.recording} "
            f"{action.delay_ticks} {action.offset.x} {action.offset.y} "
            f"{action.offset.z} {action.player_name}"
        )
        side_effect = "artifact_write"
    elif isinstance(action, MocapScenePlayAction):
        command = f"mocap playing start .{action.scene}"
        side_effect = "runtime_control"
    else:
        raise TypeError(f"Unsupported action: {type(action).__name__}")

    return CompiledCommand(
        index=index,
        action_type=action.type,  # type: ignore[attr-defined]
        command=command,
        side_effect=side_effect,
        idempotency_key=f"{plan_id}-a{index:03d}",
    )


def validate_and_compile(
    plan: ScenePlan,
    *,
    max_fill_blocks: int = 32_768,
    allow_replace: bool = False,
) -> ValidatedPlan:
    issues: list[str] = []
    warnings: list[str] = []

    for index, action in enumerate(plan.actions):
        if isinstance(action, FillAction) and action.block_count > max_fill_blocks:
            issues.append(
                f"actions[{index}] fills {action.block_count} blocks; "
                f"limit is {max_fill_blocks}"
            )
        if isinstance(action, (FillAction, SetBlockAction)):
            if action.placement == "replace" and not allow_replace:
                issues.append(
                    f"actions[{index}] requests block replacement, but replacement is disabled"
                )

    if any(isinstance(action, MocapRecordingSaveAction) for action in plan.actions):
        warnings.append(
            "Mocap save operations require the live adapter to prove the target name is unused"
        )

    if issues:
        raise PlanValidationError(issues)

    commands = [
        _compile_action(index, action, plan_id=plan.plan_id)
        for index, action in enumerate(plan.actions)
    ]
    canonical = plan.model_dump_json(exclude_none=True)
    plan_sha256 = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return ValidatedPlan(
        plan=plan,
        plan_sha256=plan_sha256,
        commands=commands,
        warnings=warnings,
    )

