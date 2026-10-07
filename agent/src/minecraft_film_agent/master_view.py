"""Event-master dual-view export planning (workflow v3 §6/§7-P3).

One recorded master serves every camera. This module validates a
``MasterViewExportPlan`` (contracts/v3/master-view.schema.json) beyond the
schema — strict ranges, keyframes inside the range, unique view ids — and
turns each view into the exact contract-3 requests the bridge expects
(replay.replace_camera_track + replay.start_render). Because a view carries
ONLY a camera track and a range, re-enacting the event per camera is
unrepresentable: C1/C2 divergence can only come from different cameras, not
from different events.
"""

from __future__ import annotations

from .contracts import ContractError, validate_against_contract_v3


class MasterViewError(ValueError):
    pass


def load_master_view(plan: dict) -> dict:
    """Schema + invariant validation; returns the plan unchanged on success."""

    try:
        validate_against_contract_v3(plan, "master-view")
    except ContractError as error:
        raise MasterViewError(f"master-view plan rejected: {error}") from error

    master_id = plan["master_id"]
    seen_views: set[str] = set()
    for view in plan["views"]:
        view_id = view["view_id"]
        if view_id in seen_views:
            raise MasterViewError(f"duplicate view_id: {view_id}")
        seen_views.add(view_id)
        start = view["range"]["start_tick"]
        end = view["range"]["end_tick"]
        if end <= start:
            raise MasterViewError(
                f"view {view_id}: range {start}..{end} must satisfy end > start")
        for keyframe in view["keyframes"]:
            tick = keyframe["tick"]
            if not start <= tick <= end:
                raise MasterViewError(
                    f"view {view_id}: keyframe tick {tick} escapes the render range "
                    f"{start}..{end}")
        ticks = [keyframe["tick"] for keyframe in view["keyframes"]]
        if ticks != sorted(ticks) or len(ticks) != len(set(ticks)):
            raise MasterViewError(f"view {view_id}: keyframes must be tick-ordered")
        if ticks[0] != start or ticks[-1] != end:
            raise MasterViewError(f"view {view_id}: camera must explicitly cover both range boundaries")
    event_ticks = [entry["tick"] for entry in plan["event_ticks"]]
    if event_ticks != sorted(event_ticks):
        raise MasterViewError("event_ticks must be tick-ordered")
    return plan


def event_tick(plan: dict, event_id: str) -> int:
    for entry in plan["event_ticks"]:
        if entry["event_id"] == event_id:
            return entry["tick"]
    raise MasterViewError(f"no event tick named {event_id!r} on master {plan['master_id']}")


def render_requests(plan: dict, view_id: str) -> dict:
    """The contract-3 request payloads for one view: camera track first, then
    the render. Both carry the same master_id; the hash travels in the
    controller's records, the bridge refuses mismatched masters itself."""

    try:
        plan = load_master_view(plan)
    except MasterViewError:
        raise
    view = next((view for view in plan["views"] if view["view_id"] == view_id), None)
    if view is None:
        raise MasterViewError(f"no view {view_id!r} on master {plan['master_id']}")
    camera_request = {
        "method": "replay.replace_camera_track",
        "params": {
            "timeline_id": plan["master_id"],
            "master_hash": plan["master_hash"],
            "keyframes": [
                {
                    "tick": keyframe["tick"],
                    "position": keyframe["position"],
                    "rotation": keyframe["rotation"],
                    **({"fov": keyframe["fov"]} if "fov" in keyframe else {}),
                }
                for keyframe in view["keyframes"]
            ],
            "interpolation": view.get("interpolation", "smooth"),
        },
    }
    render_request = {
        "method": "replay.start_render",
        "params": {
            "timeline_id": plan["master_id"],
            "master_hash": plan["master_hash"],
            "range": {"start_tick": view["range"]["start_tick"],
                      "end_tick": view["range"]["end_tick"]},
            "width": view.get("width", 1280),
            "height": view.get("height", 720),
            "fps": view.get("fps", 30),
            "output_path": view["output"],
        },
    }
    return {"view_id": view_id, "camera": camera_request, "render": render_request}


def all_view_requests(plan: dict) -> list[dict]:
    return [render_requests(plan, view["view_id"]) for view in plan["views"]]


__all__ = [
    "MasterViewError",
    "all_view_requests",
    "event_tick",
    "load_master_view",
    "render_requests",
]
