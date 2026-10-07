from pathlib import Path
import subprocess
import pytest

from minecraft_film_agent.media import verify_render, MediaValidationError
from minecraft_film_agent.photography import PhotographyRun, PhotographyError, ReplayPhotography, publish_file
from minecraft_film_agent.production_models import OperationResultV3

ROOT = Path(__file__).resolve().parents[2]
FFMPEG = ROOT / "tools/ffmpeg/bin/ffmpeg.exe"
FFPROBE = ROOT / "tools/ffmpeg/bin/ffprobe.exe"


@pytest.mark.skipif(not FFMPEG.exists(), reason="pinned local ffmpeg unavailable")
def test_exact_decode_and_wrong_frame_count(tmp_path):
    video = tmp_path / "real.mp4"
    subprocess.run([str(FFMPEG), "-v", "error", "-f", "lavfi", "-i",
        "testsrc2=size=320x240:rate=30:duration=1", "-c:v", "libx264", str(video)], check=True)
    spec = dict(expected_width=320, expected_height=240, expected_fps=30,
        expected_min_duration_seconds=1, expected_duration_seconds=1, require_decode=True,
        ffmpeg_path=FFMPEG, ffprobe_path=FFPROBE)
    report = verify_render(video, expected_frames=30, **spec)
    assert report.full_decode_passed and report.streams[0].frames == 30
    with pytest.raises(MediaValidationError, match="frame count"):
        verify_render(video, expected_frames=31, **spec)
    with pytest.raises(MediaValidationError):
        verify_render(video, **{**spec, "ffprobe_path": tmp_path / "missing.exe"})


class Client:
    def __init__(self, replies): self.replies, self.requests = iter(replies), []
    def call_v3(self, request):
        self.requests.append(request)
        status, result = next(self.replies)
        return OperationResultV3(operation_id=request.operation_id,
            idempotency_key=request.idempotency_key, status=status, result=result)


def test_master_wait_uses_typed_reply_and_read_poll():
    client = Client([("pending", {}), ("applied", {"master_hash": "sha256:abc"})])
    photo = ReplayPhotography(client, "run", sleeper=lambda _: None)
    assert photo.await_master("master").result["master_hash"] == "sha256:abc"
    assert all(r.method == "replay.await_master_saved" for r in client.requests)
    assert len({r.idempotency_key for r in client.requests}) == 1


def test_old_master_cannot_satisfy_new_open():
    client = Client([("applied", {"state": "idle"}), ("applied", {}), ("applied", {"state": "ready", "master_id": "old", "master_hash": "sha256:old"}),
                     ("applied", {"state": "ready", "master_id": "new", "master_hash": "sha256:abc"})])
    photo = ReplayPhotography(client, "run", sleeper=lambda _: None)
    assert photo.open_master("new", "sha256:abc").result["master_id"] == "new"
    assert client.requests[1].params["master_hash"] == "sha256:abc"


def test_master_open_waits_for_resources_before_mutation():
    client = Client([
        ("applied", {"state": "idle", "resources_ready": False}),
        ("applied", {"state": "idle", "resources_ready": True}),
        ("applied", {}),
        ("applied", {"state": "ready", "master_id": "master", "master_hash": "sha256:abc"})])
    photo = ReplayPhotography(client, "run", sleeper=lambda _: None)
    photo.open_master("master", "sha256:abc")
    assert [r.method for r in client.requests[:3]] == [
        "replay.get_master_status", "replay.get_master_status", "replay.open_master"]


def test_unresolved_stage_never_reexecutes_and_preserves_evidence(tmp_path):
    runner = PhotographyRun(ReplayPhotography(Client([]), "run"), tmp_path / "instance",
        tmp_path / "evidence", ffmpeg=FFMPEG, ffprobe=FFPROBE)
    with pytest.raises(RuntimeError, match="lost"):
        runner.stage("render", lambda: (_ for _ in ()).throw(RuntimeError("lost")))
    resumed = PhotographyRun(runner.photo, runner.instance, runner.root, ffmpeg=FFMPEG, ffprobe=FFPROBE)
    with pytest.raises(PhotographyError, match="unresolved"):
        resumed.stage("render", lambda: pytest.fail("reexecuted unknown write"))


def test_publish_preserves_existing_media(tmp_path):
    source = tmp_path / "render.mp4"
    target = tmp_path / "published.mp4"
    source.write_bytes(b"first verified bytes")
    publish_file(source, target)
    source.write_bytes(b"other take")
    with pytest.raises(FileExistsError):
        publish_file(source, target)
    assert target.read_bytes() == b"first verified bytes"


def test_loaded_master_hash_mismatch_is_rejected_before_mutation():
    client = Client([("applied", {"state": "ready", "master_id": "master", "master_hash": "wrong"})])
    with pytest.raises(PhotographyError, match="hash mismatch"):
        ReplayPhotography(client, "run").open_master("master", "sha256:expected")
    assert len(client.requests) == 1


def test_controller_rejects_changed_accepted_master(tmp_path):
    from types import SimpleNamespace
    from minecraft_film_agent.photography import ReplayControllerBridge, file_hash
    from minecraft_film_agent.production_models import StageStatus
    master = tmp_path / "replays/master.mcpr"
    master.parent.mkdir()
    master.write_bytes(b"accepted master")
    proof = SimpleNamespace(status=StageStatus.SUCCEEDED, evidence={"shot": {
        "master_file": str(master), "master_hash": file_hash(master)}})
    store = SimpleNamespace(latest_stage=lambda *args: proof)
    adapter = ReplayControllerBridge(Client([]), tmp_path, tmp_path, store)
    assert adapter.master("run", "master")[0] == master
    master.write_bytes(b"changed master")
    with pytest.raises(PhotographyError, match="accepted master changed"):
        adapter.master("run", "master")


def test_native_recording_pre_roll_shifts_camera_and_missing_clock_blocks(tmp_path):
    from types import SimpleNamespace
    from minecraft_film_agent.photography import ReplayControllerBridge, file_hash
    from minecraft_film_agent.production_models import StageName, StageStatus, CameraTrack, OperationRequest
    master=tmp_path/'replays/master.mcpr';master.parent.mkdir();master.write_bytes(b'owned master')
    sha=file_hash(master)
    acceptance=SimpleNamespace(status=StageStatus.SUCCEEDED,evidence={'shot':{'master_file':str(master),'master_hash':sha}})
    clock=SimpleNamespace(status=StageStatus.SUCCEEDED,evidence={'shot':{'timeline_id':'master','replay_clock':{'replay_start_ms':123}}})
    store=SimpleNamespace(latest_stage=lambda run,stage: acceptance if stage is StageName.AWAIT_REPLAY else clock)
    client=Client([('applied',{'state':'ready','master_id':'master','master_hash':sha}),('applied',{})])
    bridge=ReplayControllerBridge(client,tmp_path,tmp_path,store)
    camera=CameraTrack(camera_track_id='camera',interpolation='linear',keyframes=[
        {'tick':0,'position':(0.,70.,0.),'yaw':0.,'pitch':0.,'fov':70.},
        {'tick':200,'position':(1.,70.,0.),'yaw':0.,'pitch':0.,'fov':70.}])
    request=OperationRequest(run_id='run',operation_id='camera',idempotency_key='run/camera',method='camera')
    bridge.replace_camera_track(request,'master',camera)
    assert [frame['tick'] for frame in client.requests[-1].params['keyframes']]==[3,203]
    assert [frame.tick for frame in camera.keyframes]==[0,200]
    clock.evidence['shot']['replay_clock']={}
    with pytest.raises(PhotographyError,match='timestamp unavailable'):
        bridge.replace_camera_track(request,'master',camera)
    assert len(client.requests)==2


def test_exited_game_aborts_poll_before_rpc():
    client = Client([])
    def exited(): raise RuntimeError("game exited")
    photo = ReplayPhotography(client, "run", health_check=exited)
    with pytest.raises(RuntimeError, match="game exited"):
        photo.poll("startup", "bridge.get_game_state", {}, lambda _: False)
    assert client.requests == []


def test_blocking_screen_prevents_live_write_gate():
    from minecraft_film_agent.production_models import GameStateV2
    state = GameStateV2(session_phase="in_world", save_name="world",
        dimension="minecraft:overworld", player_name="player", paused=False,
        client_tick=1, blocking_screen=True)
    assert state.pre_write_gate(expected_save="world", expected_dimension="minecraft:overworld",
        expected_player="player") == "blocking screen is active"
