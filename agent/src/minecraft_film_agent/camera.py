"""Deterministic camera preflight (plan §12.3, offline subset).

These checks run before any camera data reaches the bridge. They are pure
arithmetic — no rendering, no screenshots, no aesthetic judgement: the visual
review that needs eyes is a separate later stage.
"""

from __future__ import annotations

from dataclasses import dataclass

from .production_models import CameraTrack, ShotPlan


@dataclass(frozen=True)
class CameraLimits:
    max_blocks_per_tick: float = 10.0
    max_degrees_per_tick: float = 20.0
    max_fov: float = 110.0
    min_y: int = -64
    max_y: int = 319


class CameraPreflightError(ValueError):
    def __init__(self, issues: list[str]):
        self.issues = issues
        super().__init__("; ".join(issues))


def preflight_camera(
    track: CameraTrack,
    shot: ShotPlan,
    *,
    limits: CameraLimits | None = None,
) -> list[str]:
    """Raise CameraPreflightError on any hard violation; return warnings."""

    limits = limits or CameraLimits()
    issues: list[str] = []
    warnings: list[str] = []

    ticks = [keyframe.tick for keyframe in track.keyframes]
    if any(later <= earlier for earlier, later in zip(ticks, ticks[1:])):
        issues.append("camera keyframe ticks must be strictly increasing")

    pre = shot.recording.pre_roll_ticks
    end = pre + shot.duration_ticks
    if ticks and ticks[0] > pre:
        issues.append(
            f"camera starts at tick {ticks[0]}, after the recording window opens at {pre}"
        )
    if ticks and ticks[-1] < end:
        issues.append(
            f"camera ends at tick {ticks[-1]}, before the shot closes at {end}"
        )

    for index, keyframe in enumerate(track.keyframes):
        if keyframe.fov > limits.max_fov:
            issues.append(f"keyframes[{index}] fov {keyframe.fov} exceeds {limits.max_fov}")
        if not limits.min_y <= keyframe.position[1] <= limits.max_y:
            issues.append(f"keyframes[{index}] y {keyframe.position[1]} outside buildable range")
        if index:
            previous = track.keyframes[index - 1]
            dtick = keyframe.tick - previous.tick
            if dtick > 0:
                distance = (
                    (keyframe.position[0] - previous.position[0]) ** 2
                    + (keyframe.position[1] - previous.position[1]) ** 2
                    + (keyframe.position[2] - previous.position[2]) ** 2
                ) ** 0.5
                speed = distance / dtick
                if speed > limits.max_blocks_per_tick:
                    issues.append(
                        f"keyframes[{index - 1}]->[{index}] move {speed:.2f} blocks/tick,"
                        f" limit is {limits.max_blocks_per_tick}"
                    )
                yaw_delta = abs(keyframe.yaw - previous.yaw)
                if yaw_delta / dtick > limits.max_degrees_per_tick:
                    warnings.append(
                        f"keyframes[{index - 1}]->[{index}] yaw rate {yaw_delta / dtick:.2f} deg/tick"
                        " — verify the turn is intentional"
                    )

    if issues:
        raise CameraPreflightError(issues)
    return warnings
