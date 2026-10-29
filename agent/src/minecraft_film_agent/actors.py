"""Strict, deterministic actor-take plans and loopback bridge execution."""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Literal, Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .bridge_client import CinematicBridgeClient, BridgeTransportError
from .contracts import validate_against_contract_v3
from .production_models import ErrorClass, OperationRequestV3


class Point(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    x: float
    y: float
    z: float

    @model_validator(mode="after")
    def finite(self):
        if not all(map(lambda v: abs(v) < 30_000_000, (self.x, self.y, self.z))):
            raise ValueError("coordinates must be finite and inside Minecraft world bounds")
        return self


class Region(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    min: Point
    max: Point


class ActorStep(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    start_tick: int = Field(ge=0)
    duration_ticks: int = Field(ge=1, le=3600)
    action: Literal["idle", "walk_to", "look_at", "sneak", "hold_item", "recoil_to", "swing_arm", "fall_down", "stand_up", "drop_material", "prepare_board", "drop_board", "phone", "phone_sit", "phone_call", "phone_call_sit", "sit", "explain", "reach", "down", "scatter_groceries", "pickup_groceries", "support_actor", "rise_supported", "push_actor", "phone_stop", "phone_place_sit", "phone_putaway", "phone_putaway_sit", "pack_bag_sit", "pack_bag_stand", "pickup_coat", "hold_coat"]
    target: Point | None = None
    timeout_ticks: int | None = Field(default=None, ge=1, le=1200)
    item_ref: Literal["minecraft:book"] | None = None
    actor_ref: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_.-]{1,48}$")

    @model_validator(mode="after")
    def required_fields(self):
        if (self.action in ("support_actor", "push_actor")) != (self.actor_ref is not None):
            raise ValueError("actor_ref is required only for actor contact actions")
        if self.action in ("walk_to", "look_at", "recoil_to", "drop_material", "prepare_board", "scatter_groceries", "pickup_groceries", "phone_place_sit", "pickup_coat") and self.target is None:
            raise ValueError(f"{self.action} requires target")
        if self.action in ("walk_to", "recoil_to") and self.timeout_ticks is None:
            raise ValueError("walk_to requires timeout_ticks")
        if (self.action in ("walk_to", "look_at", "recoil_to", "drop_material", "prepare_board", "scatter_groceries", "pickup_groceries", "phone_place_sit", "pickup_coat")) != (self.target is not None):
            raise ValueError("target only applies to walk_to or look_at")
        if self.action not in ("walk_to", "recoil_to") and self.timeout_ticks is not None:
            raise ValueError("timeout_ticks only applies to walk_to")
        if (self.action == "hold_item") != (self.item_ref is not None):
            raise ValueError("hold_item requires the registered book item; other actions cannot specify item_ref")
        return self


class ActorCue(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    actor_id: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,48}$")
    player_name: str = Field(pattern=r"^[A-Za-z0-9_]{1,16}$")
    start: Point
    yaw: float = Field(ge=-360, le=360)
    pitch: float = Field(ge=-90, le=90)
    skin_ref: Literal["classmate:a", "classmate:zhou", "classmate:teacher", "classmate:chen", "classmate:elder", "classmate:filmer", "classmate:safety"] | None = None
    steps: list[ActorStep] = Field(min_length=1, max_length=64)
    mouth_frames: list[Annotated[int, Field(ge=0, le=2)]] | None = Field(default=None, min_length=40, max_length=3600)

    @model_validator(mode="after")
    def contiguous_timeline(self):
        cursor = 0
        if self.mouth_frames is not None and self.skin_ref is None:
            raise ValueError("mouth frames require a registered model")
        if self.skin_ref is None and any(s.action in ("phone","phone_sit","phone_call","phone_call_sit","sit","explain","reach","down","scatter_groceries","pickup_groceries") for s in self.steps):
            raise ValueError("a registered model is required for character poses")
        if any(s.action in ("phone_call","phone_call_sit") for s in self.steps) and self.skin_ref not in ("classmate:a","classmate:zhou","classmate:chen","classmate:filmer","classmate:safety"):
            raise ValueError("phone calls require a registered phone-bearing role")
        placements = [i for i,s in enumerate(self.steps) if s.action == "phone_place_sit"]
        packing = [i for i,s in enumerate(self.steps) if s.action == "pack_bag_sit"]
        coats = [i for i,s in enumerate(self.steps) if s.action == "pickup_coat"]
        if coats or any(s.action == "hold_coat" for s in self.steps):
            import math
            if len(coats) != 1 or self.skin_ref != "classmate:a":
                raise ValueError("one registered A coat pickup required before holding")
            i=coats[0];step=self.steps[i]
            if not 60<=step.duration_ticks<=100 or i==0 or i==len(self.steps)-1 or any(s.action!="phone" for s in self.steps[:i]) or any(s.action!="hold_coat" for s in self.steps[i+1:]):
                raise ValueError("coat pickup60..100ticks between standing phone and coat holding only")
            x,z=step.target.x-self.start.x,step.target.z-self.start.z
            angle=math.radians(self.yaw);local_x=math.cos(angle)*x+math.sin(angle)*z;local_z=-math.sin(angle)*x+math.cos(angle)*z
            y=step.target.y-self.start.y
            if not .9<=y<=1.2 or not .2<=local_x<=.65 or not .25<=local_z<=.65 or math.sqrt((local_x-.375)**2+(y-1.4375)**2+local_z**2)>.73:
                raise ValueError("coat collar outside bounded right-hand/tabletop reach")
        standing = [i for i,s in enumerate(self.steps) if s.action == "pack_bag_stand"]
        if standing:
            i=standing[0]
            if len(standing)!=1 or self.skin_ref!="classmate:chen" or self.steps[i].duration_ticks!=160 or i==0 or i==len(self.steps)-1 or any(s.action!="idle" for j,s in enumerate(self.steps) if j!=i):
                raise ValueError("one160tick Chen standing packing action between idle rests only")
        if packing:
            i = packing[0]
            if len(packing) != 1 or self.skin_ref not in ("classmate:a", "classmate:zhou") or not 80 <= self.steps[i].duration_ticks <= 120 or i == 0 or i == len(self.steps)-1 or any(s.action != "sit" for j,s in enumerate(self.steps) if j != i):
                raise ValueError("one80..120tick student packing action between seated rests only")
        if len(placements)>1:
            raise ValueError("one tabletop phone placement per actor")
        for index, step in enumerate(self.steps):
            if step.action == "phone_place_sit":
                if self.skin_ref != "classmate:chen" or not 40 <= step.duration_ticks <= 80 or index==0 or self.steps[index-1].action != "phone_call_sit" or any(s.action != "sit" for s in self.steps[index+1:]):
                    raise ValueError("phone placement requires chen,40..80ticks,preceding seated call and remaining sit")
                import math
                if math.hypot(step.target.x-self.start.x,step.target.z-self.start.z)>1 or not .7<=step.target.y-self.start.y<=1.3:
                    raise ValueError("tabletop phone target outside seated reach envelope")
            if step.action == "phone_stop" and (self.skin_ref != "classmate:filmer" or not 30 <= step.duration_ticks <= 60 or index == 0 or self.steps[index-1].action != "phone"):
                raise ValueError("phone stop requires filmer,30..60ticks and immediately preceding standing phone action")
            if step.action in ("phone_putaway", "phone_putaway_sit"):
                seated = step.action.endswith("_sit")
                previous = "phone_sit" if seated else "phone"
                following = "sit" if seated else "idle"
                if self.skin_ref not in ("classmate:a", "classmate:zhou") or not 30 <= step.duration_ticks <= 60 or index == 0 or self.steps[index-1].action != previous:
                    raise ValueError("phone put-away requires student model,30..60ticks and matching preceding phone pose")
                if index+1 >= len(self.steps) or self.steps[index+1].action != following:
                    raise ValueError("phone put-away requires matching following rest pose")
            if step.start_tick != cursor:
                raise ValueError("actor steps must be contiguous and start at tick 0")
            cursor += step.duration_ticks
        return self


class ActorTakePlan(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal[1] = 1
    run_id: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,80}$")
    take_id: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,80}$")
    world: str = Field(min_length=1, max_length=64)
    dimension: Literal["minecraft:overworld"]
    build_region: Region
    duration_ticks: int = Field(ge=40, le=3600)
    actors: list[ActorCue] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def bounded_unique_plan(self):
        region = self.build_region
        lows, highs = (region.min.x, region.min.y, region.min.z), (region.max.x, region.max.y, region.max.z)
        if any(lo >= hi for lo, hi in zip(lows, highs)):
            raise ValueError("build_region min must be below max on every axis")
        if any(hi - lo > 64 for lo, hi in zip(lows, highs)):
            raise ValueError("actor work region may span at most 64 blocks per axis")
        ids, names = set(), set()
        by_id = {a.actor_id: a for a in self.actors}
        for actor in self.actors:
            if any(s.action=="pickup_coat" for s in actor.steps) and (actor.start.x-1<region.min.x or actor.start.x+1>region.max.x or actor.start.z-1<region.min.z or actor.start.z+1>region.max.z or actor.start.y+1.9>region.max.y):
                raise ValueError("coat prop/hand footprint escapes work region")
            if any(s.action in ("pack_bag_sit", "pack_bag_stand") for s in actor.steps) and (actor.start.x-.9 < region.min.x or actor.start.x+.9 > region.max.x or actor.start.z-.9 < region.min.z or actor.start.z+.9 > region.max.z or actor.start.y+1.7 > region.max.y):
                raise ValueError("packing props and arm reach must fit inside the work region")
            if actor.mouth_frames is not None and len(actor.mouth_frames) != self.duration_ticks:
                raise ValueError("mouth frames must cover every take tick exactly")
            for step in actor.steps:
                if step.action == "push_actor":
                    target_actor=by_id.get(step.actor_ref)
                    end=step.start_tick+step.duration_ticks
                    if actor.skin_ref!="classmate:chen" or not 6<=step.duration_ticks<=20 or target_actor is None or target_actor is actor or target_actor.skin_ref!="classmate:elder":
                        raise ValueError("push requires worker, another elder and6..20ticks")
                    if not any(s.action=="idle" and s.start_tick<=step.start_tick and s.start_tick+s.duration_ticks>=end for s in target_actor.steps) or not any(s.action=="recoil_to" and s.start_tick==end for s in target_actor.steps):
                        raise ValueError("push contact requires standing elder followed immediately by scripted recoil")
                if step.action == "support_actor":
                    target_actor=by_id.get(step.actor_ref)
                    if actor.skin_ref not in ("classmate:chen","classmate:safety") or step.duration_ticks<20 or target_actor is None or target_actor is actor or target_actor.skin_ref!="classmate:elder":
                        raise ValueError("support requires worker/safety, another registered elder and20ticks")
                if step.action == "rise_supported":
                    if actor.skin_ref!="classmate:elder" or not 40<=step.duration_ticks<=100 or not any(s.action=="support_actor" and s.actor_ref==actor.actor_id and s.start_tick<=step.start_tick and s.start_tick+s.duration_ticks>=step.start_tick+step.duration_ticks for a in self.actors for s in a.steps):
                        raise ValueError("elder rise40..100ticks requires support for its entire interval")
        groceries_scatter = groceries_pickup = None
        for actor in self.actors:
            if actor.actor_id in ids or actor.player_name in names:
                raise ValueError("actor_id and player_name must be unique within a take")
            ids.add(actor.actor_id); names.add(actor.player_name)
            cursor = actor.start
            drops = 0
            board_prepared = board_dropped = False
            for step in actor.steps:
                if step.action == "scatter_groceries":
                    import math
                    if actor.skin_ref != "classmate:elder" or groceries_scatter is not None or math.hypot(step.target.x-cursor.x,step.target.z-cursor.z)>.35 or abs(step.target.y-cursor.y)>.001:
                        raise ValueError("one elder grocery scatter at the actor floor")
                    if not (region.min.x+2.2<=step.target.x<=region.max.x-2.2 and region.min.z+1.3<=step.target.z<=region.max.z-1.3 and step.target.y+2.1<=region.max.y):
                        raise ValueError("grocery footprint escapes region")
                    groceries_scatter=step
                if step.action == "pickup_groceries":
                    import math
                    if actor.skin_ref != "classmate:filmer" or groceries_pickup is not None or abs(step.target.x-cursor.x)>.025 or abs(cursor.z-(step.target.z-.4))>.025 or abs(step.target.y-cursor.y)>.001 or step.duration_ticks not in (3040,1520):
                        raise ValueError("one filmer grocery pickup, 3040 legacy or1520 compact ticks at the initial center.x/center.z-.4 anchor")
                    groceries_pickup=step
                    cursor=Point(x=step.target.x-.8,y=step.target.y,z=step.target.z+.3)
                if step.action == "recoil_to":
                    import math
                    if abs(step.target.y-cursor.y)>0.001 or math.hypot(step.target.x-cursor.x,step.target.z-cursor.z)>2.5:
                        raise ValueError("recoil_to must stay on one floor and within 2.5 blocks")
                if step.action in ("walk_to", "recoil_to"):
                    cursor = step.target
                if step.action == "prepare_board":
                    if board_prepared or not 2 <= step.target.y-cursor.y <= 12:
                        raise ValueError("one prepared board, 2..12 blocks above actor floor")
                    if not (region.min.x+.5 <= step.target.x <= region.max.x-.5 and region.min.z+1 <= step.target.z <= region.max.z-1 and step.target.y+.3 <= region.max.y):
                        raise ValueError("entire board footprint must stay inside build_region")
                    board_prepared=True
                if step.action == "drop_board":
                    if not board_prepared or board_dropped:raise ValueError("drop_board requires one previously prepared board")
                    board_dropped=True
                if step.action == "drop_material":
                    drops += 1
                    if drops > 1 or not 2 <= step.target.y-cursor.y <= 12:
                        raise ValueError("one material drop per actor, 2..12 blocks above actor floor")
            if board_prepared and not board_dropped:raise ValueError("prepared board must be released in this take")
            if actor.steps[-1].start_tick + actor.steps[-1].duration_ticks != self.duration_ticks:
                raise ValueError("each actor timeline must cover duration_ticks exactly")
            points = [actor.start, *(step.target for step in actor.steps if step.target)]
            for point in points:
                if not all(lo <= value <= hi for lo, value, hi in zip(lows, (point.x, point.y, point.z), highs)):
                    raise ValueError("actor positions and targets must stay inside build_region")
        if self.duration_ticks>1200 and groceries_pickup is None:
            raise ValueError("takes over1200ticks require the registered owned grocery pickup")
        if (groceries_scatter is None) != (groceries_pickup is None):
            raise ValueError("grocery scatter requires one later pickup")
        if groceries_scatter is not None:
            import math
            a,b=groceries_scatter,groceries_pickup
            if b.start_tick<a.start_tick+18 or math.hypot(a.target.x-b.target.x,a.target.z-b.target.z)>.001 or abs(a.target.y-b.target.y)>.001:
                raise ValueError("pickup must follow scatter at the same grocery center")
        return self


def canonical_plan(plan: ActorTakePlan) -> tuple[dict, str]:
    payload = plan.model_dump(mode="json", exclude_none=True)
    validate_against_contract_v3(payload, "actor-plan")
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return payload, "sha256:" + hashlib.sha256(encoded).hexdigest()


def start_take(client: CinematicBridgeClient, plan: ActorTakePlan, key: str):
    payload, digest = canonical_plan(plan)
    req = OperationRequestV3(run_id=plan.run_id, operation_id=re.sub(r"[^A-Za-z0-9_.-]", "-", key)[:80],
                             idempotency_key=key, plan_hash=digest, method="actor.start_take", params=payload)
    return client.call_v3(req)


def take_status(client: CinematicBridgeClient, run_id: str, take_id: str):
    request = OperationRequestV3(run_id=run_id, operation_id=f"status-{take_id}"[:80],
                                 idempotency_key=f"{run_id}/status/{take_id}", method="actor.get_take_status",
                                 params={"take_id": take_id})
    return client.call_v3(request)


def wait_for_take(client: CinematicBridgeClient, run_id: str, take_id: str, timeout: float = 30.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        result = take_status(client, run_id, take_id)
        state = result.result.get("take_state") if result.result else None
        if state in {"succeeded", "failed", "cancelled", "unknown"}:
            return result
        time.sleep(0.2)
    raise BridgeTransportError(ErrorClass.OPERATION_TIMEOUT_UNKNOWN,
                               f"take {take_id} still running; query status, never resend")


def load_plan(path: Path) -> ActorTakePlan:
    return ActorTakePlan.model_validate_json(path.read_text(encoding="utf-8"))
