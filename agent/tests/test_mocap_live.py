"""Mocap live support (plan v2 §Phase D): classifier pins mirror the shared
transcript fixtures for both supported locales and reject unknown feedback;
the save-proof helpers refuse overwrites and hash the artifact."""

from __future__ import annotations

from pathlib import Path

import pytest

from minecraft_film_agent.mocap_live import (
    MocapSaveProofError,
    assert_target_free,
    await_artifact,
    classify_feedback,
    recordings_dir,
    snapshot_manifest,
    transcript_fixtures,
)
from minecraft_film_agent.mocap_live import MocapFeedbackClass as FB


# -- classifier pins (mirror of the Java MocapFeedback table) ----------------


@pytest.mark.parametrize(
    ("event", "expected"),
    [
        ("waiting-for-selection", FB.WAITING_FOR_SELECTION),
        ("waiting-cancelled", FB.WAITING_CANCELLED),
        ("save-rejected-empty", FB.SAVE_REJECTED_EMPTY),
        ("recording-started", FB.RECORDING_STARTED),
        ("recording-stopped", FB.RECORDING_STOPPED),
        ("save-success", FB.SAVE_SUCCESS),
    ],
)
def test_zh_cn_fixture_pins_classify_as_the_live_outcome(event: str, expected: FB) -> None:
    text = transcript_fixtures()["zh_cn"][event]
    assert classify_feedback(text, locale="zh_cn") is expected


def test_unknown_mod_chatter_fails_closed() -> None:
    text = transcript_fixtures()["unknown"].get("axiom-tip") or (
        "[Axiom] Tip: Access the Axiom config by running /axiomconfig"
    )
    assert classify_feedback(text, locale="zh_cn") is FB.UNKNOWN
    assert classify_feedback("totally new message from a mod update", locale="zh_cn") is FB.UNKNOWN


def test_en_us_provisional_pins_classify() -> None:
    fixtures = transcript_fixtures()["en_us"]
    assert classify_feedback(fixtures["recording-started"], locale="en_us") is FB.RECORDING_STARTED
    assert classify_feedback(fixtures["save-success"], locale="en_us") is FB.SAVE_SUCCESS
    assert classify_feedback(fixtures["save-rejected-empty"], locale="en_us") is FB.SAVE_REJECTED_EMPTY


def test_formatting_codes_are_stripped_before_matching() -> None:
    assert classify_feedback("§l错误：§r没有可以保存的东西！", locale="zh_cn") is FB.SAVE_REJECTED_EMPTY


# -- save artifact proof -------------------------------------------------------


@pytest.fixture()
def instance(tmp_path: Path) -> Path:
    recordings = tmp_path / "saves" / "Marx Video Test" / "mocap_files" / "recordings"
    recordings.mkdir(parents=True)
    return tmp_path


def test_recordings_dir_refuses_traversal(instance: Path) -> None:
    with pytest.raises(MocapSaveProofError):
        recordings_dir(instance, "../elsewhere")
    with pytest.raises(MocapSaveProofError):
        recordings_dir(instance, "a/b")


def test_assert_target_free_refuses_existing_recording(instance: Path) -> None:
    target = assert_target_free(instance, "Marx Video Test", "take_01")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"existing take - never overwrite")
    with pytest.raises(MocapSaveProofError, match="never overwrite"):
        assert_target_free(instance, "Marx Video Test", "take_01")


def test_snapshot_manifest_lists_existing_recordings(instance: Path) -> None:
    recordings = recordings_dir(instance, "Marx Video Test")
    (recordings / "take_01.mcmocap_rec").write_bytes(b"x")
    assert snapshot_manifest(instance, "Marx Video Test") == ["take_01"]
    assert snapshot_manifest(instance, "Marx Video Test") is not None


def test_await_artifact_hashes_the_exact_path(instance: Path) -> None:
    import hashlib

    target = assert_target_free(instance, "Marx Video Test", "take_02")
    target.write_bytes(b"recorded-payload")

    proof = await_artifact(target, attempts=1, sleep_seconds=0.0, sleeper=lambda s: None)
    assert proof["name"] == "take_02"
    assert proof["bytes"] == len(b"recorded-payload")
    assert proof["sha256"] == "sha256:" + hashlib.sha256(b"recorded-payload").hexdigest()


def test_await_artifact_fails_closed_when_file_never_appears(instance: Path) -> None:
    target = recordings_dir(instance, "Marx Video Test") / "ghost.mcmocap_rec"
    with pytest.raises(MocapSaveProofError, match="never appeared"):
        await_artifact(target, attempts=3, sleep_seconds=0.0, sleeper=lambda s: None)
