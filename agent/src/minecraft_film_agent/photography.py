"""One production ReplayMod adapter for the controller and unattended acceptance.

Submission acknowledgement, replay readiness, rendered bytes and accepted media
are separate checkpoints. Unknown writes are never automatically resubmitted.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Callable

from .bridge_client import BridgeTransportError, CinematicBridgeClient
from .media import verify_render
from .production_models import OperationRequestV3, OperationResultV3
from .locking import RunLease, replace_evidence


def file_hash(path: Path) -> str:
    with path.open("rb") as source:
        return "sha256:" + hashlib.file_digest(source, "sha256").hexdigest()


def publish_file(source: Path, target: Path) -> None:
    """Publish complete bytes atomically without replacing an existing target."""
    import os
    import shutil
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".publishing")
    with source.open("rb") as input_file, temporary.open("xb") as output_file:
        shutil.copyfileobj(input_file, output_file)
        output_file.flush()
        os.fsync(output_file.fileno())
    if file_hash(source) != file_hash(temporary):
        raise PhotographyError("source changed during publication")
    os.link(temporary, target)  # both paths are in the same directory; no replace
    temporary.unlink()


class PhotographyError(RuntimeError):
    pass


class ReplayPhotography:
    def __init__(self, client: CinematicBridgeClient, run_id: str, *,
                 timeout: float = 900, sleeper: Callable = time.sleep, health_check: Callable | None = None):
        self.client, self.run_id, self.timeout, self.sleep = client, run_id, timeout, sleeper
        self.health_check = health_check

    def call(self, stage: str, method: str, params: dict) -> OperationResultV3:
        key = f"{self.run_id}/{stage}"
        return self.client.call_v3(OperationRequestV3(
            run_id=self.run_id, operation_id=hashlib.sha256(key.encode()).hexdigest(),
            idempotency_key=key, method=method, params=params))

    def require(self, stage: str, method: str, params: dict) -> OperationResultV3:
        result = self.call(stage, method, params)
        if result.status not in ("applied", "succeeded"):
            raise PhotographyError(f"{method}: {result.status}: {result.message}")
        return result

    def poll(self, stage: str, method: str, params: dict, predicate: Callable) -> OperationResultV3:
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            if self.health_check is not None:
                self.health_check()
            try:
                result = self.call(stage, method, params)
            except BridgeTransportError:
                self.sleep(0.5)
                continue
            state = result.result.get("state")
            if isinstance(state,str): state=state.lower()
            if result.status in ("failed", "rejected") or state in ("failed", "cancelled"):
                raise PhotographyError(f"{method} failed: {result.message or result.result}")
            if predicate(result):
                return result
            self.sleep(0.5)
        raise PhotographyError(f"{method}: timeout; operation remains unresolved, do not resend")

    def await_master(self, master_id: str) -> OperationResultV3:
        return self.poll("master-await", "replay.await_master_saved", {"timeline_id": master_id},
                         lambda result: result.status == "applied" and bool(result.result.get("master_hash")))

    def open_master(self, master_id: str, master_hash: str, *, stage: str = "master-open") -> OperationResultV3:
        current = self.poll(stage + "-current", "replay.get_master_status", {},
                            lambda r: r.status == "applied" and r.result.get("resources_ready", True))
        state = current.result.get("state")
        same = current.result.get("master_id") == master_id
        if state == "ready" and same:
            if current.result.get("master_hash") != master_hash:
                raise PhotographyError("loaded master hash mismatch")
            return current
        if state == "loading" and not same:
            raise PhotographyError("another master is loading")
        if state != "loading":
            # A new session open is permitted only after observing no active load.
            import uuid
            self.require(stage + "-" + uuid.uuid4().hex[:12], "replay.open_master",
                         {"timeline_id": master_id, "master_hash": master_hash})
        return self.poll(stage + "-status", "replay.get_master_status", {},
            lambda result: result.result.get("state") == "ready" and result.result.get("master_id") == master_id
                and result.result.get("master_hash") == master_hash)

    def render(self, master_id: str, master_hash: str, view_id: str, camera: dict,
               output: Path, start: int, end: int, width: int, height: int, fps: int) -> OperationResultV3:
        self.require(f"camera-{view_id}", "replay.replace_camera_track", {
            "timeline_id": master_id, "master_hash": master_hash, **camera})
        submitted = self.require(f"render-{view_id}", "replay.start_render", {
            "timeline_id": master_id, "master_hash": master_hash,
            "range": {"start_tick": start, "end_tick": end}, "width": width,
            "height": height, "fps": fps, "output_path": str(output.resolve())})
        job_id = submitted.result["job_id"]
        return self.poll(f"render-status-{view_id}", "replay.get_render_status", {},
            lambda result: result.result.get("job_id") == job_id and result.result.get("state") == "rendered")


class PhotographyRun:
    """Persisted single-take entry point. Resuming an interrupted mutation fails closed."""
    def __init__(self, photo: ReplayPhotography, instance: Path, evidence_dir: Path,
                 *, ffmpeg: Path, ffprobe: Path):
        self.photo, self.instance = photo, instance.resolve()
        self.root = evidence_dir.resolve()
        self.ffmpeg, self.ffprobe = ffmpeg.resolve(), ffprobe.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.manifest = self.root / "photography.json"
        if self.manifest.exists():
            self.data = json.loads(self.manifest.read_text(encoding="utf-8"))
            if self.data["run_id"] != photo.run_id or self.data["instance"] != str(self.instance):
                raise PhotographyError("run identity mismatch")
        else:
            self.data = {"run_id": photo.run_id, "instance": str(self.instance), "stages": {}, "status": "running"}
            with self.manifest.open("x", encoding="utf-8") as file:
                json.dump(self.data, file, indent=2)

    def save(self):
        tmp = self.manifest.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as file:
            json.dump(self.data, file, indent=2, ensure_ascii=False)
            file.flush()
            import os
            os.fsync(file.fileno())
        replace_evidence(tmp,self.manifest)

    def stage(self, name: str, action: Callable):
        previous = self.data["stages"].get(name)
        if previous:
            if previous["status"] == "succeeded": return previous["result"]
            raise PhotographyError(f"{name} has an unresolved previous attempt; inspect before resuming")
        self.data["stages"][name] = {"status": "running"}
        self.save()
        result = action()
        if isinstance(result, OperationResultV3): result = result.model_dump(mode="json")
        self.data["stages"][name] = {"status": "succeeded", "result": result}
        self.save()
        return result

    def execute(self, **kwargs):
        lock = self.root / "run.lock"
        with RunLease(lock):
            return self._execute(**kwargs)

    def _execute(self, *, world: str, player: str, record_ticks: int = 260,
                start: int = 20, end: int = 220, width: int = 1280, height: int = 720, fps: int = 30,
                camera: dict):
        master_id = f"{self.photo.run_id}-master"
        import re
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", self.photo.run_id) or self.photo.run_id in (".", ".."):
            raise PhotographyError("invalid run id")
        if not (0 <= start < end <= record_ticks and (end-start)*fps % 20 == 0):
            raise PhotographyError("invalid or non-integral-frame render range")
        spec = {"world": world, "player": player, "record_ticks": record_ticks, "start": start,
                "end": end, "width": width, "height": height, "fps": fps, "camera": camera}
        if self.data.get("spec") and self.data["spec"] != spec: raise PhotographyError("run specification changed")
        self.data["spec"] = spec
        self.save()
        output = self.instance / "bridge-renders" / self.photo.run_id / "c1-v1.mp4"
        final = self.root / "c1-v1.mp4"
        try:
            if "record" not in self.data["stages"]:
                if output.exists() or final.exists(): raise PhotographyError("output already exists")
                caps = self.photo.require("capabilities", "bridge.capabilities", {}).result
                if any(caps.get(name) != "replaymod" for name in ("replay_backend", "camera_backend", "render_backend")):
                    raise PhotographyError("pinned ReplayMod photography unavailable")
                def record():
                    state = self.photo.require("state", "bridge.get_game_state", {}).result
                    if state.get("session_phase") != "in_world" or state.get("dimension") != "minecraft:overworld" \
                            or state.get("save_name") != world or state.get("player_name") != player or state.get("paused"):
                        raise PhotographyError("world/player/unpaused identity preflight failed")
                    if state.get("blocking_screen"):
                        raise PhotographyError("blocking screen is active")
                    self.photo.require("record-start", "replay.start_recording", {"timeline_id": master_id})
                    tick = self.photo.require("record-start-tick", "bridge.get_game_state", {}).result["client_tick"]
                    self.photo.poll("record-ticks", "bridge.get_game_state", {}, lambda r:
                        r.result.get("save_name") == world and r.result.get("client_tick", 0) >= tick + record_ticks)
                    return self.photo.require("record-stop", "replay.stop_recording", {"timeline_id": master_id})
                self.stage("record", record)
            master = self.stage("master", lambda: self.photo.await_master(master_id))["result"]
            if file_hash(Path(master["master_file"])) != master["master_hash"]:
                raise PhotographyError("accepted master changed")
            if self.data["status"] == "succeeded":
                if file_hash(final) != self.data["video_hash"]: raise PhotographyError("published video changed")
                return self.data
            # Opening is a session operation: re-open the verified master after process restart.
            if self.data["stages"].get("render", {}).get("status") != "succeeded":
                self.photo.open_master(master_id, master["master_hash"])
            self.stage("render", lambda: self.photo.render(master_id, master["master_hash"], "c1", camera,
                                                         output, start, end, width, height, fps))
            def accept():
                report = verify_render(output, expected_width=width, expected_height=height,
                    expected_fps=fps, expected_min_duration_seconds=(end-start)/20,
                    expected_duration_seconds=(end-start)/20, expected_frames=(end-start)*fps//20,
                    require_decode=True, ffmpeg_path=self.ffmpeg, ffprobe_path=self.ffprobe)
                publish_file(output, final)
                return report.model_dump(mode="json")
            self.stage("accept", accept)
            self.data["video_hash"] = file_hash(final)
            self.data["status"] = "succeeded"
            self.save()
            return self.data
        except Exception as error:
            self.data["status"] = "blocked"
            self.data["error"] = str(error)
            self.save()
            raise


class ReplayControllerBridge:
    """Adapts the existing production checkpoints to the v3 photography surface."""
    def __init__(self, bridge, workspace: Path, instance: Path | None, store):
        if instance is None: raise ValueError("ReplayMod controller needs explicit instance root")
        self.bridge, self.workspace, self.instance = bridge, workspace, instance
        self.store = store

    def __getattr__(self, name):
        return getattr(self.bridge, name)

    def photo(self, run_id): return ReplayPhotography(self.bridge, run_id)

    def begin_take(self, run_id, master_id):
        return self.photo(run_id).require("take-start", "replay.start_recording", {"timeline_id": master_id})

    def end_take(self, run_id, master_id):
        self.photo(run_id).require("take-stop", "replay.stop_recording", {"timeline_id": master_id})

    def wait_timeline(self, run_id, timeline_id, *, timeout_seconds=180):
        photo=self.photo(run_id);photo.timeout=timeout_seconds
        return photo.poll("timeline-wait", "bridge.get_timeline_status", {}, lambda r:
            r.result.get("timeline_id") == timeline_id and r.result.get("state") == "COMPLETED")

    def await_replay_saved(self, request, timeline_id):
        return self.photo(request.run_id).await_master(timeline_id)

    def master(self, run_id, timeline_id):
        from .production_models import StageName, StageStatus
        accepted = self.store.latest_stage(run_id, StageName.AWAIT_REPLAY)
        if accepted is None or accepted.status is not StageStatus.SUCCEEDED:
            raise PhotographyError("master has no persisted acceptance proof")
        path = self.instance / "replays" / f"{timeline_id}.mcpr"
        sha = file_hash(path)
        if not any(proof.get("master_hash") == sha and
                   Path(proof.get("master_file", "")).resolve() == path.resolve()
                   for proof in accepted.evidence.values() if isinstance(proof, dict)):
            raise PhotographyError("accepted master changed or identity mismatch")
        return path, sha

    def replay_offset_ticks(self, run_id, timeline_id):
        from .production_models import StageName, StageStatus
        receipt=self.store.latest_stage(run_id,StageName.RUN_TIMELINE)
        if receipt is None or receipt.status is not StageStatus.SUCCEEDED:
            raise PhotographyError("timeline has no persisted native replay clock")
        matching=[p for p in receipt.evidence.values() if isinstance(p,dict) and p.get("timeline_id")==timeline_id]
        if len(matching)!=1:
            raise PhotographyError("timeline clock identity is ambiguous")
        stamp=matching[0].get("replay_clock",{}).get("replay_start_ms")
        if type(stamp) is not int or stamp<0:
            raise PhotographyError("native replay start timestamp unavailable; refuse an unaligned export")
        return (stamp+49)//50

    def replace_camera_track(self, request, timeline_id, camera):
        _, sha = self.master(request.run_id, timeline_id)
        offset=self.replay_offset_ticks(request.run_id,timeline_id)
        photo = self.photo(request.run_id)
        photo.open_master(timeline_id, sha)
        import uuid
        return photo.require("camera-" + timeline_id + "-" + uuid.uuid4().hex[:12], "replay.replace_camera_track", {
            "timeline_id": timeline_id, "master_hash": sha, "interpolation": camera.interpolation,
            "keyframes": [{"tick": k.tick+offset, "position": list(k.position),
                           "rotation": [k.yaw, k.pitch, k.roll], "fov": k.fov} for k in camera.keyframes]})

    def start_export(self, request, *, timeline_id, range_ticks, output_relative, width, height, fps, camera_override=None):
        final = (self.workspace / output_relative).resolve()
        allowed=(self.workspace / "assets/renders").resolve()
        if not allowed.is_relative_to(self.workspace) or not final.is_relative_to(allowed):
            raise PhotographyError("export escaped allowed directory")
        if final.exists(): raise PhotographyError("published export already exists")
        _, sha = self.master(request.run_id, timeline_id)
        photo = self.photo(request.run_id)
        # Reconstruct session state from immutable derived inputs after restart.
        from .production_models import CameraTrack
        plans = self.workspace / "work/runs" / request.run_id / "plans/shots"
        matching = [folder for folder in plans.iterdir() if
                    json.loads((folder / "timeline.json").read_text(encoding="utf-8"))["timeline_id"] == timeline_id]
        if len(matching) != 1:
            raise PhotographyError("camera/timeline identity is ambiguous")
        camera = camera_override or CameraTrack.model_validate_json((matching[0] / "camera.json").read_text(encoding="utf-8"))
        self.replace_camera_track(request, timeline_id, camera)
        offset=self.replay_offset_ticks(request.run_id,timeline_id)
        output = self.instance / "bridge-renders" / request.run_id / Path(output_relative).name
        result = photo.require(request.idempotency_key.split("/")[-1], "replay.start_render", {
            "timeline_id": timeline_id, "master_hash": sha,
            "range": {"start_tick": range_ticks[0]+offset, "end_tick": range_ticks[1]+offset},
            "output_path": str(output.resolve()), "width": width, "height": height, "fps": fps})
        job_id = result.result["job_id"]
        done = photo.poll("render-wait", "replay.get_render_status", {}, lambda r:
                         r.result.get("job_id") == job_id and r.result.get("state") == "rendered")
        report = verify_render(output, expected_width=width, expected_height=height,
            expected_fps=fps, expected_min_duration_seconds=(range_ticks[1]-range_ticks[0])/20,
            expected_duration_seconds=(range_ticks[1]-range_ticks[0])/20,
            expected_frames=(range_ticks[1]-range_ticks[0])*fps//20, require_decode=True,
            ffmpeg_path=self.workspace / "tools/ffmpeg/bin/ffmpeg.exe",
            ffprobe_path=self.workspace / "tools/ffmpeg/bin/ffprobe.exe")
        final.parent.mkdir(parents=True, exist_ok=True)
        publish_file(output, final)
        return done.model_copy(update={"result": {**done.result, "native_output":str(output.resolve()), "output":output_relative, "media": report.model_dump(mode="json"), "output_hash":file_hash(final), "master_hash":sha, "replay_offset_ticks":offset}})
