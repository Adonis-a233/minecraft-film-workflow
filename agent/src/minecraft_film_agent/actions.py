"""ActionRegistry: the boundary between story and performance assets.

The planner may only reference Mocap actions that this registry can resolve.
An unresolvable cue is a hard stop (``asset_missing``) with a recording
checklist — never an improvised substitute (architecture spec §4, §11).
"""

from __future__ import annotations

import json
from pathlib import Path

from .contracts import plan_hash, validate_against_contract
from .production_models import (
    ActionMetadata,
    ActionResolution,
    MissingAssetReport,
)


class ActionRegistryError(RuntimeError):
    pass


class ActionRegistry:
    def __init__(
        self,
        workspace_root: Path,
        *,
        actions_root: Path | None = None,
        mocap_dirs: "list[Path] | None" = None,
    ):
        self.workspace_root = workspace_root.resolve()
        self.actions_root = (
            actions_root.resolve() if actions_root else self.workspace_root / "assets" / "actions"
        )
        self.mocap_dirs = [path.resolve() for path in (mocap_dirs or [])]
        self._actions: dict[str, ActionMetadata] = {}
        self.scan()

    def scan(self) -> dict[str, ActionMetadata]:
        self._actions.clear()
        if self.actions_root.is_dir():
            for path in sorted(self.actions_root.rglob("action.json")):
                raw = json.loads(path.read_text(encoding="utf-8"))
                validate_against_contract(raw, "action-metadata")
                metadata = ActionMetadata.model_validate(raw)
                if metadata.recording_id in self._actions:
                    raise ActionRegistryError(
                        f"duplicate recording_id {metadata.recording_id} at {path}"
                    )
                self._actions[metadata.recording_id] = metadata
        return dict(self._actions)

    def __contains__(self, recording_id: str) -> bool:
        return recording_id in self._actions

    def get(self, recording_id: str) -> ActionMetadata | None:
        return self._actions.get(recording_id)

    def catalog_hash(self) -> str:
        payload = {rid: meta.model_dump(mode="json") for rid, meta in sorted(self._actions.items())}
        return plan_hash(payload)

    def resolve(self, action_refs: "list[str]") -> MissingAssetReport:
        report = MissingAssetReport()
        seen: set[str] = set()
        for ref in action_refs:
            if ref in seen:
                continue
            seen.add(ref)
            metadata = self._actions.get(ref)
            if metadata is None:
                report.missing.append(ref)
                continue
            resolution = ActionResolution(
                action_ref=ref,
                recording_id=metadata.recording_id,
                source_file=metadata.source_file,
                verified=metadata.verified,
            )
            if not (self.workspace_root / metadata.source_file).resolve().is_file():
                report.missing.append(ref)
                continue
            if metadata.verified:
                report.resolved.append(resolution)
            else:
                report.unverified.append(resolution)
        return report

    @staticmethod
    def recording_checklist(missing: "list[str]") -> "list[str]":
        """Human-facing todo list when cues cannot be resolved."""

        return [f"record or register Mocap action '{name}' (assets/actions/…/action.json)" for name in missing]
