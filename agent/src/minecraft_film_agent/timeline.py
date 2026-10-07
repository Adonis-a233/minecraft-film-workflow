"""TimelinePlan compilation and validation.

The timeline is the deterministic heartbeat of a take (architecture spec §1):
the bridge executes it on the Minecraft main thread, tick by tick. Python
never sleeps its way through a recording; it hands this plan to the bridge
and then only polls status.
"""

from __future__ import annotations

from .production_models import ShotPlan, TimelineEvent, TimelinePlan

FLASHBACK_START = "flashback.start_recording"
FLASHBACK_STOP = "flashback.stop_recording"
MOCAP_SCENE_CREATE = "mocap.scene_create"
MOCAP_SCENE_ADD = "mocap.scene_add"
MOCAP_SCENE_PLAY = "mocap.scene_play"
MOCAP_SCENE_STOP = "mocap.scene_stop"
ASSERT_STATE = "assert_state"


class TimelineError(ValueError):
    pass


def compile_shot_timeline(
    shot: ShotPlan,
    *,
    world_name: str,
    mocap_scene: str,
    actor_offsets: dict[str, "tuple[int, int, int]"] | None = None,
    include_flashback: bool = True,
) -> TimelinePlan:
    """Derive the tick schedule for one shot.

    Layout: tick 0 asserts the world and composes the (stopped) Mocap scene;
    ``pre_roll`` starts Flashback and plays the scene; ``pre_roll + duration``
    stops the scene; ``total`` stops Flashback so the replay covers the whole
    shot plus rolls.

    ``include_flashback=False`` compiles a Mocap-only take for bridges whose
    flashback automation is license-gated off: the replay events are omitted
    and the Mocap scene is the only scheduled playback.
    """

    pre = shot.recording.pre_roll_ticks
    post = shot.recording.post_roll_ticks
    total = pre + shot.duration_ticks + post
    if total > 24_000:
        raise TimelineError(
            f"shot {shot.shot_id} needs {total} ticks including rolls; limit is 24000"
        )

    events: list[TimelineEvent] = [
        TimelineEvent(tick=0, type=ASSERT_STATE, payload={"world": world_name}),
        TimelineEvent(
            tick=0, type=MOCAP_SCENE_CREATE, payload={"scene": mocap_scene}
        ),
    ]
    offsets = actor_offsets or {}
    for actor in shot.actors:
        offset = offsets.get(actor.actor_id, actor.position or (0, 0, 0))
        events.append(
            TimelineEvent(
                tick=0,
                type=MOCAP_SCENE_ADD,
                payload={
                    "scene": mocap_scene,
                    "recording": actor.action_ref,
                    "delay_ticks": actor.start_tick,
                    "offset": {"x": offset[0], "y": offset[1], "z": offset[2]},
                    "player_name": actor.actor_id,
                    **({"skin_file": actor.skin_file} if actor.skin_file is not None else {}),
                },
            )
        )
    playback = [TimelineEvent(tick=pre, type=MOCAP_SCENE_PLAY, payload={"scene": mocap_scene})]
    closing: list[TimelineEvent] = [
        TimelineEvent(
            tick=pre + shot.duration_ticks,
            type=MOCAP_SCENE_STOP,
            payload={"scene": mocap_scene},
        )
    ]
    if include_flashback:
        playback = [TimelineEvent(tick=pre, type=FLASHBACK_START, payload={}), *playback]
        closing.append(TimelineEvent(tick=total, type=FLASHBACK_STOP, payload={}))
    events.extend([*playback, *closing])
    timeline = TimelinePlan(
        timeline_id=f"{shot.shot_id}-take-001",
        shot_id=shot.shot_id,
        world_name=world_name,
        total_ticks=total,
        events=events,
    )
    issues = validate_timeline(timeline)
    if issues:
        raise TimelineError("; ".join(issues))
    return timeline


def validate_timeline(timeline: TimelinePlan) -> list[str]:
    issues: list[str] = []
    ticks = [event.tick for event in timeline.events]
    if any(later < earlier for earlier, later in zip(ticks, ticks[1:])):
        issues.append("timeline events are not in ascending tick order")
    if ticks[0] != 0 or timeline.events[0].type != ASSERT_STATE:
        issues.append("timeline must open with assert_state at tick 0")

    starts = [event for event in timeline.events if event.type == FLASHBACK_START]
    stops = [event for event in timeline.events if event.type == FLASHBACK_STOP]
    if len(starts) != len(stops):
        issues.append("timeline must pair flashback start and stop")
    elif len(starts) == 1:
        if starts[0].tick >= stops[0].tick:
            issues.append("flashback recording window is empty or inverted")

    for event in timeline.events:
        if event.tick > timeline.total_ticks:
            issues.append(
                f"event {event.type} at tick {event.tick} exceeds total_ticks {timeline.total_ticks}"
            )
    return issues


def recording_window(timeline: TimelinePlan) -> "tuple[int, int] | None":
    """The flashback window, or None on a Mocap-only (flashback-free) timeline."""

    starts = [event for event in timeline.events if event.type == FLASHBACK_START]
    stops = [event for event in timeline.events if event.type == FLASHBACK_STOP]
    if not starts and not stops:
        return None
    if len(starts) != 1 or len(stops) != 1:
        raise TimelineError("timeline has no well-defined recording window")
    return (starts[0].tick, stops[0].tick)
