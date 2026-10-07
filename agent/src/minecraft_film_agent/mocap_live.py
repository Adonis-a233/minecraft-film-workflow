"""Live Mocap support (plan v2 §Phase D): feedback classification mirror and
save-artifact proof.

The bridge owns feedback classification (``MocapFeedback`` in Java, pinned to
``contracts/v2/fixtures/transcripts/``). This module mirrors those pins so
Python-side tests and transcript evidence stay in the same lockstep, and it
implements the save-proof flow:

1. resolve the integrated-save directory from the explicit instance root and
   the proven save name (path traversal is refused);
2. snapshot the recordings manifest BEFORE the save;
3. refuse any pre-existing target (live state or filesystem);
4. after the save transition, poll ONLY the exact expected
   ``.mcmocap_rec`` path;
5. record size, mtime, and SHA-256 in the stage evidence.

Nothing here deletes or overwrites an existing recording.
"""

from __future__ import annotations

import hashlib
import time
from enum import StrEnum
from pathlib import Path

from .contracts import fixtures_root
from .mocap import RECORDING_SUFFIX


class MocapFeedbackClass(StrEnum):
    """Mirror of the Java ``MocapFeedback`` pins (keep in lockstep)."""

    WAITING_FOR_SELECTION = "waiting_for_selection"
    WAITING_CANCELLED = "waiting_cancelled"
    SAVE_REJECTED_EMPTY = "save_rejected_empty"
    RECORDING_STARTED = "recording_started"
    RECORDING_STOPPED = "recording_stopped"
    SAVE_SUCCESS = "save_success"
    UNKNOWN = "unknown"


_ZH_PINS: tuple[tuple[MocapFeedbackClass, str, str], ...] = (
    # (class, pin, mode) — pins match the real live log lines
    (MocapFeedbackClass.WAITING_FOR_SELECTION,
     "执行任何操作或再次使用\"/mocap recording start\"以开始录制", "prefix"),
    (MocapFeedbackClass.WAITING_CANCELLED, "已停止等待选择", "exact"),
    (MocapFeedbackClass.SAVE_REJECTED_EMPTY, "没有可以保存的东西", "contains"),
    (MocapFeedbackClass.RECORDING_STARTED, "录制开始……", "exact"),
    (MocapFeedbackClass.RECORDING_STOPPED, "录制停止——等待选择中", "prefix"),
    (MocapFeedbackClass.SAVE_SUCCESS, "录像已成功保存", "exact"),
)

_EN_PINS: tuple[tuple[MocapFeedbackClass, str, str], ...] = (
    # provisional: fail closed until a real en_us session verifies them
    (MocapFeedbackClass.WAITING_FOR_SELECTION,
     "Perform any action or run \"/mocap recording start\" again to start recording", "prefix"),
    (MocapFeedbackClass.WAITING_CANCELLED, "Stopped waiting for selection", "exact"),
    (MocapFeedbackClass.SAVE_REJECTED_EMPTY, "There is nothing to save!", "contains"),
    (MocapFeedbackClass.RECORDING_STARTED, "Recording started...", "exact"),
    (MocapFeedbackClass.RECORDING_STOPPED,
     "Recording stopped - waiting for selection", "prefix"),
    (MocapFeedbackClass.SAVE_SUCCESS, "Recording successfully saved", "exact"),
)


def _strip_formatting(line: str) -> str:
    if "§" in line:
        out: list[str] = []
        skip = False
        for char in line:
            if skip:
                skip = False
                continue
            if char == "§":
                skip = True
                continue
            out.append(char)
        line = "".join(out)
    return line.strip()


def classify_feedback(raw: str, locale: str = "zh_cn") -> MocapFeedbackClass:
    """Classify one complete feedback event; unknown feedback fails closed."""

    line = _strip_formatting(raw)
    pins = _ZH_PINS if locale == "zh_cn" else _EN_PINS
    for feedback, pin, mode in pins:
        if mode == "prefix" and line.startswith(pin):
            return feedback
        if mode == "exact" and line == pin:
            return feedback
        if mode == "contains" and pin in line:
            return feedback
    if locale == "zh_cn" and "你需要先开始录制" in line:
        return MocapFeedbackClass.SAVE_REJECTED_EMPTY
    if locale == "en_us" and "You need to start recording first" in line:
        return MocapFeedbackClass.SAVE_REJECTED_EMPTY
    return MocapFeedbackClass.UNKNOWN


def transcript_fixtures() -> dict[str, dict[str, str]]:
    """The shared transcript fixtures, keyed by locale then event name."""

    root = fixtures_root() / "transcripts"
    out: dict[str, dict[str, str]] = {}
    for locale in ("zh_cn", "en_us", "unknown"):
        directory = root / locale
        if not directory.is_dir():
            continue
        out[locale] = {
            path.stem: path.read_text(encoding="utf-8").rstrip("\n")
            for path in sorted(directory.glob("*.txt"))
            if path.name != "README.txt"
        }
    return out


# -- save artifact proof ------------------------------------------------------


class MocapSaveProofError(RuntimeError):
    def __init__(self, reason: str, evidence: dict[str, object] | None = None):
        self.evidence = evidence or {}
        super().__init__(reason)


def recordings_dir(instance_root: Path, save_name: str) -> Path:
    """`<instance>/saves/<save_name>/mocap_files/recordings`, traversal-proof."""

    if any(token in save_name for token in ("/", "\\", "..", ":")):
        raise MocapSaveProofError(f"save_name is not a plain name: {save_name!r}")
    saves = (instance_root / "saves").resolve()
    target = (saves / save_name / "mocap_files" / "recordings").resolve()
    if saves not in target.parents:
        raise MocapSaveProofError("resolved recordings path escapes the instance saves root")
    return target


def snapshot_manifest(instance_root: Path, save_name: str) -> list[str]:
    directory = recordings_dir(instance_root, save_name)
    if not directory.is_dir():
        return []
    return sorted(path.stem for path in directory.glob("*" + RECORDING_SUFFIX))


def assert_target_free(instance_root: Path, save_name: str, recording_name: str) -> Path:
    """The exact target must not exist yet — never overwrite a recording."""

    directory = recordings_dir(instance_root, save_name)
    target = directory / f"{recording_name}{RECORDING_SUFFIX}"
    if any(token in recording_name for token in ("/", "\\", "..", ":")):
        raise MocapSaveProofError(f"recording_name is not a plain name: {recording_name!r}")
    if target.exists():
        raise MocapSaveProofError(
            f"recording already exists; never overwrite: {target}",
            evidence={"target": str(target)},
        )
    return target


def await_artifact(
    target: Path,
    *,
    attempts: int = 30,
    sleep_seconds: float = 0.5,
    sleeper=time.sleep,
) -> dict[str, object]:
    """Poll the exact expected path; prove size, mtime, and SHA-256."""

    for _ in range(attempts):
        if target.is_file() and target.stat().st_size > 0:
            payload = target.read_bytes()
            return {
                "path": str(target),
                "name": target.stem,
                "bytes": len(payload),
                "mtime": target.stat().st_mtime,
                "sha256": "sha256:" + hashlib.sha256(payload).hexdigest(),
            }
        sleeper(sleep_seconds)
    raise MocapSaveProofError(
        f"recording file never appeared: {target}",
        evidence={"target": str(target), "attempts": attempts},
    )
