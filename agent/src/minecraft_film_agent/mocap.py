"""Read-only manifest of the Mocap library inside a world save.

On-disk layout (verified 2026-09-01/02 against the project instance save
`Marx Video Test`):

- `<save>/mocap_files/recordings/<name>.mcmocap_rec`
- `<save>/mocap_files/scenes/` (scene file extension not yet observed)

This module only reads. It never creates, renames, or deletes Mocap files;
proving a save target unused before a live save is exactly its job, and a
conflict must fail the run instead of being silently suffixed or overwritten.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from .models import (
    MocapPlaybackStartAction,
    MocapRecordingSaveAction,
    MocapSceneAddAction,
    MocapSceneCreateAction,
    ScenePlan,
)


RECORDING_SUFFIX = ".mcmocap_rec"


class MocapLibraryUnavailable(RuntimeError):
    pass


class MocapManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recordings: list[str] = Field(default_factory=list)
    scenes: list[str] = Field(default_factory=list)
    recordings_dir: str
    scenes_dir: str
    warnings: list[str] = Field(default_factory=list)


def _stems(directory: Path, suffix: str | None, warnings: list[str], label: str) -> list[str]:
    if not directory.is_dir():
        return []
    names: list[str] = []
    for entry in sorted(directory.iterdir()):
        if not entry.is_file():
            continue
        if suffix is not None and entry.suffix != suffix:
            warnings.append(f"unexpected {label} file extension: {entry.name}")
            continue
        names.append(entry.stem)
    return names


class MocapLibrary:
    """Read-only view of one world save's Mocap recordings and scenes."""

    def __init__(self, save_root: Path):
        self._save_root = save_root.resolve()

    def scan(self) -> MocapManifest:
        if not self._save_root.is_dir():
            raise MocapLibraryUnavailable(
                f"mocap save root does not exist or is not a directory: {self._save_root}"
            )
        mocap_root = self._save_root / "mocap_files"
        recordings_dir = mocap_root / "recordings"
        scenes_dir = mocap_root / "scenes"
        warnings: list[str] = []
        if not mocap_root.is_dir():
            warnings.append(
                "no mocap_files directory in this save; no recording has been made yet"
            )
        return MocapManifest(
            recordings=_stems(recordings_dir, RECORDING_SUFFIX, warnings, "recording"),
            scenes=_stems(scenes_dir, None, warnings, "scene"),
            recordings_dir=str(recordings_dir),
            scenes_dir=str(scenes_dir),
            warnings=warnings,
        )

    def conflicts(self, plan: ScenePlan) -> list[str]:
        """Names the plan may not (re)create, plus dangling playback references.

        Commands execute sequentially, so a `mocap_scene_add` or
        `mocap_playback_start` may only reference a recording that exists on
        disk or that an earlier action of the same plan saved. Anything else
        is a dependency error caught before approval instead of a failed
        live take.
        """
        manifest = self.scan()
        issues: list[str] = []
        saved_so_far: set[str] = set()
        for index, action in enumerate(plan.actions):
            if isinstance(action, MocapRecordingSaveAction):
                saved_so_far.add(action.name)
                if action.name in manifest.recordings:
                    issues.append(
                        f"actions[{index}] saves recording '{action.name}', "
                        "which already exists; recordings are never overwritten"
                    )
            elif isinstance(action, MocapSceneCreateAction):
                if action.scene in manifest.scenes:
                    issues.append(
                        f"actions[{index}] creates scene '{action.scene}', "
                        "which already exists; scenes are never overwritten"
                    )
            elif isinstance(action, MocapSceneAddAction):
                if action.recording not in manifest.recordings and action.recording not in saved_so_far:
                    issues.append(
                        f"actions[{index}] references recording '{action.recording}', "
                        "which is neither in the library nor saved by an earlier action"
                    )
            elif isinstance(action, MocapPlaybackStartAction):
                if action.name not in manifest.recordings and action.name not in saved_so_far:
                    issues.append(
                        f"actions[{index}] plays recording '{action.name}', "
                        "which is neither in the library nor saved by an earlier action"
                    )
        return issues
