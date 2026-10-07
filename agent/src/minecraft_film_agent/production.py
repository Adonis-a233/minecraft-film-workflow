"""Production controller: the deterministic whole-film chain (plan P1, v2 in
plan v2 §Phase E).

Chain, each stage a separate auditable step:

    validate_plan → prepare_scene → resolve_actions → compose_take
    → prepare_recording → start_recording → run_timeline → stop_recording
    → save_mocap → await_replay → apply_camera → export_shot
    → inspect_media → approve_final

The four recording checkpoints (plan v2 §Phase E) reflect real boundaries:
an unsaved Mocap take and a missing Flashback replay can never collapse into
one ambiguous failure. When the runtime advertises ``flashback_automation:
false`` (the license-gated default), the flashback-dependent stages are
recorded as SKIPPED and the run is labeled with the achieved scope — the
``live end-to-end`` label is reserved for runs that prove every item of the
definition of done.

Properties enforced here, not promised by callers:

- two-phase execution: commit only executes the exact previewed plan hash;
- idempotent stages: a succeeded stage with the same input hash is skipped,
  so re-running after a crash can never duplicate world writes, recordings,
  or exports;
- timeout-unknown writes are resolved through a status/state read before any
  resend (architecture spec §9);
- capability preflight BEFORE the first write: plans requiring flashback are
  rejected while flashback automation is off; no fallback to simulation;
- retries follow the structured per-error policy; export/media failures
  re-run only the export node, on a fresh output version — a valid replay is
  never re-recorded, and existing outputs are never overwritten.

Offline, ``sleep`` is a no-op: backoff policy is expressed as data and
verified as data, never by actually waiting.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from . import statemachine
from .actions import ActionRegistry
from .bridge_client import version_mismatches, version_mismatches_v2
from .camera import CameraPreflightError, preflight_camera
from .contracts import (
    ContractError,
    contract_payload,
    plan_hash,
    preview_commit_guard,
    validate_against_contract,
)
from .compiler import PlanValidationError, validate_and_compile
from .models import CompiledCommand, ScenePlan
from .mocap import MocapLibrary
from .mocap_live import MocapSaveProofError, await_artifact, assert_target_free
from .media import MediaValidationError, verify_render
from .photography import PhotographyError, file_hash
from .locking import replace_evidence
from .production_models import (
    CameraTrack,
    CapabilitiesV2,
    CapabilitiesV3,
    ErrorClass,
    ExportPlan,
    GameStateV2,
    OperationRequest,
    ProductionBackends,
    ProductionPlan,
    RetryScope,
    ShotPlan,
    StageName,
    StageRecord,
    StageStatus,
    TickRange,
    TimelinePlan,
)
from .store import ProductionStore
from .timeline import (
    TimelineError,
    compile_shot_timeline,
    validate_timeline,
)
from .video import VideoProbeError, probe_video


class StageFailure(RuntimeError):
    def __init__(self, error_class: ErrorClass, message: str, evidence: dict | None = None):
        self.error_class = error_class
        self.evidence = evidence or {}
        super().__init__(message)


class StageSkipped(RuntimeError):
    """A stage that cannot apply to this runtime (e.g. flashback gated off).

    Recorded as SKIPPED with its reason — never as success, never as failure.
    """

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


@dataclass
class PlanPreview:
    production: ProductionPlan
    plan_hash: str
    scene_plan_hashes: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    asset_missing: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return not self.issues and not self.asset_missing


class ProductionController:
    def __init__(
        self,
        workspace_root: Path,
        store: ProductionStore,
        *,
        minecraft,
        bridge,
        registry: ActionRegistry | None = None,
        mocap_dir: Path | None = None,
        mode: str = "simulation",
        capabilities: CapabilitiesV2 | CapabilitiesV3 | None = None,
        expected_world: str | None = None,
        expected_dimension: str = "minecraft:overworld",
        expected_player: str | None = None,
        instance_root: Path | None = None,
    ):
        if mode not in ("simulation", "live"):
            raise ValueError(f"unknown controller mode: {mode}")
        if mode == "live" and capabilities is None:
            raise ValueError("live mode requires advertised runtime capabilities")
        self.workspace_root = workspace_root.resolve()
        self.store = store
        self.minecraft = minecraft
        self.bridge = bridge
        self.registry = registry
        self.mocap_dir = mocap_dir.resolve() if mocap_dir else None
        self.mode = mode
        self.capabilities = capabilities
        # Backend-neutral photography chain (workflow v3 §8): stages gate on
        # these names, never on a mod brand. Simulation keeps the historical
        # mock behavior (the mock simulates replay/camera/export); live
        # derives from the advertised capabilities.
        if capabilities is not None:
            self.backends = ProductionBackends.from_capabilities(capabilities)
        else:
            self.backends = ProductionBackends(
                recorder="mocap", replay="flashback", camera="flashback",
                renderer="flashback",
            )
        self.expected_world = expected_world
        self.expected_dimension = expected_dimension
        self.expected_player = expected_player
        self.instance_root = instance_root.resolve() if instance_root else None
        self.runs_root = self.workspace_root / "work" / "runs"
        if mode == "live" and self.backends.replay == "replaymod":
            from .photography import ReplayControllerBridge
            self.bridge = ReplayControllerBridge(bridge, self.workspace_root, self.instance_root, store)

    @property
    def flashback_enabled(self) -> bool:
        """Whether flashback automation may run in this mode.

        Simulation keeps the historical mock behavior (the mock simulates
        replay/export); live follows the runtime's advertised capability.
        """

        if self.mode == "live":
            return bool(self.capabilities and self.capabilities.flashback_automation)
        return True

    # -- phase 1: preview (pure; touches nothing but temp-free reads) --------

    def preview(self, production: ProductionPlan) -> PlanPreview:
        result = PlanPreview(
            production=production, plan_hash=plan_hash(contract_payload(production))
        )
        try:
            validate_against_contract(contract_payload(production), "production-plan")
        except ContractError as error:
            result.issues.append(str(error))
            return result

        registry = self.registry
        action_refs = [actor.action_ref for shot in production.shots for actor in shot.actors]
        for shot in production.shots:
            try:
                validate_against_contract(contract_payload(shot), "shot-plan")
                compile_shot_timeline(
                    shot, world_name=self._world_for(production, shot), mocap_scene=shot.shot_id,
                    include_flashback=self.flashback_enabled,
                )
            except (ContractError, TimelineError, ValidationError) as error:
                result.issues.append(f"shot {shot.shot_id}: {error}")
                continue
            if shot.camera_ref is not None:
                camera_path = self.workspace_root / "assets" / "cameras" / f"{shot.camera_ref}.json"
                try:
                    camera = self._load_camera(camera_path)
                except (OSError, ContractError, ValidationError) as error:
                    result.issues.append(f"camera {shot.camera_ref}: {error}")
                    continue
                try:
                    result.warnings.extend(
                        f"camera {shot.camera_ref}: {warning}"
                        for warning in preflight_camera(camera, shot)
                    )
                except CameraPreflightError as error:
                    result.issues.append(f"camera {shot.camera_ref}: {error}")

            scene = self._scene_of(production, shot)
            if scene.blueprint_ref:
                try:
                    scene_plan = self._load_scene_plan(self.workspace_root / scene.blueprint_ref)
                    validated = validate_and_compile(scene_plan)
                    result.scene_plan_hashes[scene.scene_id] = validated.plan_sha256
                except (OSError, ValidationError, PlanValidationError, ContractError) as error:
                    result.issues.append(f"blueprint {scene.blueprint_ref}: {error}")

        if registry is not None:
            report = registry.resolve(action_refs)
            result.asset_missing = list(report.missing)
            if report.unverified:
                result.warnings.append(
                    "unverified actions in use: " + ", ".join(r.action_ref for r in report.unverified)
                )
        return result

    def commit(self, preview: PlanPreview, approved_by: str, run_id: str | None = None) -> str:
        """Phase 2: create the run for exactly this preview and record approval."""

        if not approved_by.strip():
            raise StageFailure(ErrorClass.APPROVAL_REQUIRED, "human approval is required to commit")
        if not preview.ready:
            raise StageFailure(
                ErrorClass.ASSET_MISSING if preview.asset_missing else ErrorClass.VALIDATION_FAILED,
                "; ".join(preview.issues + preview.asset_missing) or "preview not ready",
            )
        production = preview.production
        # Two-phase guard (plan §8.2): commit only the exact previewed plan.
        preview_commit_guard(plan_hash(contract_payload(production)), preview.plan_hash)
        resolved = run_id or self._run_id_for(production, preview.plan_hash)
        resolved_run_id, created = self.store.create_run(
            resolved, production.production_id, preview.plan_hash
        )
        if created:
            self._write_run_inputs(resolved_run_id, preview)
            self.store.set_approval(resolved_run_id, approved_by)
        return resolved_run_id

    # -- phase 3: stage execution -------------------------------------------

    def execute(self, run_id: str) -> dict[str, object]:
        if self.mode != "live":
            return self._execute(run_id)
        lock = self._run_dir(run_id) / "execution.lock"
        from .locking import RunLease
        with RunLease(lock):
            return self._execute(run_id)

    def _execute(self, run_id: str) -> dict[str, object]:
        production = self._load_production(run_id)
        stage_outputs: dict[str, object] = {}
        skipped_any = False
        for stage in statemachine.STAGE_ORDER:
            prior = self.store.succeeded_stage(run_id, stage, self._stage_hash(run_id, stage))
            if prior is not None:
                stage_outputs[stage.value] = {"status": "skipped", "reason": "already succeeded"}
                continue
            attempt = self.store.next_attempt(run_id, stage)
            if self.mode == "live":
                operation_dir = self._run_dir(run_id) / "operations"
                operation_dir.mkdir(parents=True, exist_ok=True)
                for marker in operation_dir.glob(f"{stage.value}-*.json"):
                    data = json.loads(marker.read_text(encoding="utf-8"))
                    if data["status"] == "running":
                        return self._halt(run_id, stage, ErrorClass.OPERATION_TIMEOUT_UNKNOWN,
                            f"unresolved stage attempt: {marker}; reconcile evidence before retry")
            last = self.store.latest_stage(run_id, stage)
            if last is not None and last.status is StageStatus.FAILED and last.error_class:
                policy = statemachine.retry_policy_for(last.error_class)
                if policy.scope is RetryScope.NONE:
                    return self._halt(run_id, stage, last.error_class,
                                      f"{stage.value} failed with {last.error_class.value}; policy forbids retry")
                if attempt > policy.max_attempts:
                    return self._halt(run_id, stage, ErrorClass.MANUAL_INTERVENTION_REQUIRED,
                                      f"{stage.value} exhausted {policy.max_attempts} attempts")
            try:
                if self.mode == "live":
                    self._write_durable(operation_dir / f"{stage.value}-{attempt}.json",
                        {"status": "running", "stage": stage.value, "attempt": attempt,
                         "input_hash": self._stage_hash(run_id, stage)})
                evidence = self._run_stage(run_id, stage, production)
            except StageSkipped as skip:
                skipped_any = True
                self._record(run_id, stage, attempt, StageStatus.SKIPPED,
                             self._stage_hash(run_id, stage), None, skip.reason,
                             {"skipped": skip.reason})
                stage_outputs[stage.value] = {"status": "skipped", "reason": skip.reason}
                continue
            except StageFailure as failure:
                self._record(run_id, stage, attempt, StageStatus.FAILED,
                             self._stage_hash(run_id, stage), failure.error_class, str(failure), failure.evidence)
                return self._halt(run_id, stage, failure.error_class, str(failure))
            except (PhotographyError, MediaValidationError) as failure:
                error_class = ErrorClass.MEDIA_VALIDATION_FAILED if isinstance(failure, MediaValidationError) \
                    else ErrorClass.OPERATION_TIMEOUT_UNKNOWN
                self._record(run_id, stage, attempt, StageStatus.FAILED,
                    self._stage_hash(run_id, stage), error_class, str(failure), {"unresolved": str(failure)})
                return self._halt(run_id, stage, error_class, str(failure))
            record = self._record(run_id, stage, attempt, StageStatus.SUCCEEDED,
                                  self._stage_hash(run_id, stage), None, None, evidence)
            stage_outputs[stage.value] = {"status": "succeeded", "evidence": evidence,
                                          "output_path": record.output_path}
        self._set_state(run_id, "completed")
        return {"ok": True, "run_id": run_id, "mode": self.mode,
                "scope": self._scope_label(skipped_any), "stages": stage_outputs}

    def _scope_label(self, skipped_any: bool) -> str:
        """DoD §6: name the achieved scope precisely; `live end-to-end` is
        reserved for full definition-of-done runs (none of which exist yet)."""

        if self.mode == "simulation":
            return "simulation"
        if skipped_any:
            return "live-mocap"
        if self.backends.replay == "replaymod":
            return "live-replaymod-photography"
        return "live-mocap"

    # -- stage bodies --------------------------------------------------------

    def _run_stage(self, run_id: str, stage: StageName, production: ProductionPlan) -> dict:
        if stage is StageName.VALIDATE_PLAN:
            return self._stage_validate(run_id, production)
        if stage is StageName.PREPARE_SCENE:
            return self._stage_prepare_scene(run_id, production)
        if stage is StageName.RESOLVE_ACTIONS:
            return self._stage_resolve_actions(production)
        if stage is StageName.COMPOSE_TAKE:
            return self._stage_compose_take(run_id, production)
        if stage is StageName.PREPARE_RECORDING:
            return self._stage_prepare_recording(run_id, production)
        if stage is StageName.START_RECORDING:
            return self._stage_start_recording(run_id, production)
        if stage is StageName.RUN_TIMELINE:
            return self._stage_run_timeline(run_id, production)
        if stage is StageName.STOP_RECORDING:
            return self._stage_stop_recording(run_id, production)
        if stage is StageName.SAVE_MOCAP:
            return self._stage_save_mocap(run_id, production)
        if stage is StageName.AWAIT_REPLAY:
            return self._stage_await_replay(run_id, production)
        if stage is StageName.APPLY_CAMERA:
            return self._stage_apply_camera(run_id, production)
        if stage is StageName.EXPORT_SHOT:
            return self._stage_export(run_id, production)
        if stage is StageName.INSPECT_MEDIA:
            return self._stage_inspect(run_id, production)
        if stage is StageName.APPROVE_FINAL:
            approved_by = self.store.approval(run_id)
            if not approved_by:
                raise StageFailure(ErrorClass.APPROVAL_REQUIRED, "run has no recorded approval")
            return {"approved_by": approved_by}
        raise StageFailure(ErrorClass.OPERATION_REJECTED, f"unknown stage {stage}")

    # -- capability preflight (before ANY write) ------------------------------

    def _preflight_capabilities(self, production: ProductionPlan) -> None:
        """Live runs refuse impossible plans BEFORE PREPARE_SCENE (plan v2 §E).

        There is no fallback: a plan needing replay/camera/export is rejected
        while flashback automation is license-gated off, and a Mocap-only
        plan proceeds only with typed world ops, world reads, the Mocap
        state machine, and the tick scheduler advertised.
        """

        if self.mode != "live" or self.capabilities is None:
            return
        mismatches = self.capabilities.runtime_mismatches()
        if mismatches:
            raise StageFailure(ErrorClass.ENVIRONMENT_MISMATCH, "; ".join(mismatches))
        if self.backends.replay == "replaymod" and len(production.shots) != 1:
            raise StageFailure(ErrorClass.VALIDATION_FAILED,
                "ReplayMod currently requires one event take per production run; export multiple views from its master")
        flashback_required = any(shot.camera_ref is not None for shot in production.shots)
        if flashback_required and self.backends.camera == "none":
            reason = self.capabilities.flashback_disabled_reason or "no camera backend advertised"
            raise StageFailure(
                ErrorClass.MANUAL_INTERVENTION_REQUIRED,
                f"plan requires camera tracks but camera={self.backends.camera!r} / "
                f"replay={self.backends.replay!r}: {reason}",
            )
        missing = self.capabilities.missing_for_mocap_only()
        if missing:
            raise StageFailure(
                ErrorClass.ENVIRONMENT_MISMATCH,
                "runtime lacks required capabilities: " + ", ".join(missing),
            )

    def _stage_validate(self, run_id: str, production: ProductionPlan) -> dict:
        preview = self.preview(production)
        if not preview.ready:
            raise StageFailure(
                ErrorClass.ASSET_MISSING if preview.asset_missing else ErrorClass.VALIDATION_FAILED,
                "; ".join(preview.issues + preview.asset_missing),
            )
        # persist the derived plans this run will execute
        for shot in production.shots:
            shot_dir = self._run_dir(run_id) / "plans" / "shots" / shot.shot_id
            shot_dir.mkdir(parents=True, exist_ok=True)
            timeline = compile_shot_timeline(
                shot, world_name=self._world_for(production, shot), mocap_scene=shot.shot_id,
                include_flashback=self.flashback_enabled,
            )
            if self.backends.replay == "replaymod":
                import hashlib
                timeline = timeline.model_copy(update={"timeline_id": "take-" + hashlib.sha256(
                    f"{run_id}/{shot.shot_id}".encode()).hexdigest()[:40]})
            validate_against_contract(contract_payload(timeline), "timeline-plan")
            self._write_derived(shot_dir / "timeline.json", timeline.model_dump(mode="json"))
            if shot.camera_ref:
                camera = self._load_camera(
                    self.workspace_root / "assets" / "cameras" / f"{shot.camera_ref}.json"
                )
                self._write_derived(shot_dir / "camera.json", camera.model_dump(mode="json"))
        return {"plan_hash": preview.plan_hash, "scene_hashes": preview.scene_plan_hashes}

    def _stage_prepare_scene(self, run_id: str, production: ProductionPlan) -> dict:
        evidence: dict[str, object] = {}
        self._preflight_capabilities(production)
        self.minecraft.get_status()
        for scene in production.scenes:
            if not scene.blueprint_ref:
                continue
            plan_path = self._run_dir(run_id) / "plans" / "scenes" / scene.scene_id / "scene-plan.json"
            commands_path = plan_path.with_name("commands.json")
            if not plan_path.is_file():
                raise StageFailure(ErrorClass.OPERATION_REJECTED,
                                   f"missing compiled scene inputs for {scene.scene_id}")
            scene_plan = ScenePlan.model_validate_json(plan_path.read_text(encoding="utf-8"))
            validated = validate_and_compile(scene_plan)
            if commands_path.is_file():
                raw_commands = json.loads(commands_path.read_text(encoding="utf-8"))
            else:
                raw_commands = [c.model_dump(mode="json") for c in validated.commands]
                self._write_new(commands_path, raw_commands)
            applied = 0
            for raw in raw_commands:
                command = CompiledCommand.model_validate(raw)
                result = self.minecraft.execute(command)
                result = _resolve_uncertain(self.minecraft, command, result)
                if result.status in {"rejected", "failed"}:
                    raise StageFailure(ErrorClass.OPERATION_REJECTED,
                                       f"scene {scene.scene_id}: {result.message}")
                if command.action_type=='set_weather' and hasattr(self.minecraft,'await_scene_weather'):
                    evidence[scene.scene_id+'-visual-weather']=self.minecraft.await_scene_weather(command)
                applied += 1
            evidence[scene.scene_id] = {"commands": applied, "world": scene_plan.world_name}
        return evidence

    def _stage_resolve_actions(self, production: ProductionPlan) -> dict:
        refs = sorted({actor.action_ref for shot in production.shots for actor in shot.actors})
        if not refs:
            return {"resolved": [], "unverified": [], "missing": []}
        if self.registry is None:
            raise StageFailure(ErrorClass.ASSET_MISSING,
                               "no ActionRegistry configured; refusing to improvise performances")
        refs = sorted({actor.action_ref for shot in production.shots for actor in shot.actors})
        report = self.registry.resolve(refs)
        if not report.ok:
            raise StageFailure(
                ErrorClass.ASSET_MISSING,
                "missing actions: " + ", ".join(report.missing),
                evidence={"missing": report.missing,
                          "checklist": ActionRegistry.recording_checklist(report.missing)},
            )
        return report.model_dump(mode="json")

    def _stage_compose_take(self, run_id: str, production: ProductionPlan) -> dict:
        evidence: dict[str, object] = {}
        library = MocapLibrary(self.mocap_dir).scan() if self.mocap_dir else None
        for shot in production.shots:
            timeline = self._load_timeline(run_id, shot.shot_id)
            issues = validate_timeline(timeline)
            if issues:
                raise StageFailure(ErrorClass.VALIDATION_FAILED, f"{shot.shot_id}: {issues}")
            if library is not None:
                if shot.shot_id in library.scenes:
                    raise StageFailure(
                        ErrorClass.OPERATION_REJECTED,
                        f"Mocap scene '{shot.shot_id}' already exists; rename the production instead of overwriting",
                    )
                missing_recordings = sorted(
                    {actor.action_ref for actor in shot.actors}
                    - set(library.recordings)
                )
                if missing_recordings:
                    raise StageFailure(
                        ErrorClass.ASSET_MISSING,
                        f"recordings not in Mocap library: {missing_recordings}",
                    )
            evidence[shot.shot_id] = {"timeline_id": timeline.timeline_id,
                                      "total_ticks": timeline.total_ticks}
        return evidence

    # -- recording checkpoints (plan v2 §Phase E) ------------------------------

    def _bridge_handshake_evidence(self) -> dict[str, object]:
        versions = self.bridge.handshake()
        mismatches = (
            version_mismatches_v2(versions)
            if self.mode == "live"
            else version_mismatches(versions)
        )
        if mismatches:
            raise StageFailure(ErrorClass.ENVIRONMENT_MISMATCH, "; ".join(mismatches))
        return {"bridge": versions.model_dump()}

    def _stage_prepare_recording(self, run_id: str, production: ProductionPlan) -> dict:
        evidence = self._bridge_handshake_evidence()
        if self.mode == "live":
            self._assert_live_world()
        for shot in production.shots:
            request = self._request(run_id, f"mocap-prepare-{shot.shot_id}", "mocap.prepare_recording")
            result = self.bridge.mocap_prepare(request)
            if result.status not in ("applied", "observed"):
                raise StageFailure(
                    ErrorClass.MOCAP_FEEDBACK_UNKNOWN if result.error_class is ErrorClass.MOCAP_FEEDBACK_UNKNOWN
                    else ErrorClass.OPERATION_REJECTED,
                    f"{shot.shot_id}: prepare_recording did not reach waiting_for_selection: "
                    + (result.message or result.status),
                    evidence=dict(result.result),
                )
            evidence[shot.shot_id] = {"phase": "waiting_for_selection", **_result_evidence(result)}
        return evidence

    def _stage_start_recording(self, run_id: str, production: ProductionPlan) -> dict:
        evidence: dict[str, object] = {}
        for shot in production.shots:
            request = self._request(
                run_id, f"mocap-confirm-{shot.shot_id}", "mocap.confirm_recording_start"
            )
            result = self.bridge.mocap_confirm(request)
            if result.status not in ("applied", "observed"):
                raise StageFailure(
                    ErrorClass.MOCAP_FEEDBACK_UNKNOWN if result.error_class is ErrorClass.MOCAP_FEEDBACK_UNKNOWN
                    else ErrorClass.OPERATION_REJECTED,
                    f"{shot.shot_id}: recording never started (two-step start unfinished): "
                    + (result.message or result.status),
                    evidence=dict(result.result),
                )
            evidence[shot.shot_id] = {"phase": "recording", **_result_evidence(result)}
        return evidence

    def _stage_run_timeline(self, run_id: str, production: ProductionPlan) -> dict:
        evidence: dict[str, object] = {}
        for shot in production.shots:
            timeline = self._load_timeline(run_id, shot.shot_id)
            if self.backends.replay == "replaymod":
                self.bridge.begin_take(run_id, timeline.timeline_id)
            request = self._request(run_id, f"record-{shot.shot_id}", "bridge.submit_timeline")
            result = self.bridge.submit_timeline(request, timeline)
            if result.status == "unknown":
                # Never resend blindly: resolve the outcome with a status read.
                result = self.bridge.timeline_status(
                    request.model_copy(update={"method": "bridge.get_timeline_status"})
                )
            if result.status == "rejected" and result.error_class is ErrorClass.WORLD_MISMATCH:
                raise StageFailure(ErrorClass.WORLD_MISMATCH, result.message or "world mismatch")
            if result.status not in ("applied", "observed"):
                raise StageFailure(ErrorClass.OPERATION_TIMEOUT_UNKNOWN,
                                   f"{shot.shot_id}: timeline outcome unresolved: {result.message}")
            replay_clock={}
            if self.backends.replay == "replaymod":
                done=self.bridge.wait_timeline(run_id, timeline.timeline_id,timeout_seconds=timeline.total_ticks/20*3+60)
                replay_clock=dict(done.result)
                feedback=replay_clock.get("feedback",[])
                if (feedback.count("Scene successfully added")!=1
                    or feedback.count("Element successfully added to scene")!=len(shot.actors)
                    or feedback.count("Playing started...")!=1
                    or not any(s in feedback for s in ("Playing stopped","Owned scene already completed","Playing of all scenes stopped"))):
                    raise StageFailure(ErrorClass.MOCAP_FEEDBACK_UNKNOWN,"scene composition/playback feedback not fully proven",evidence=replay_clock)
            evidence[shot.shot_id] = {"timeline_id": timeline.timeline_id,
                                      "total_ticks": timeline.total_ticks,
                                      **_result_evidence(result),"replay_clock":replay_clock}
        return evidence

    def _stage_stop_recording(self, run_id: str, production: ProductionPlan) -> dict:
        evidence: dict[str, object] = {}
        for shot in production.shots:
            request = self._request(run_id, f"mocap-stop-{shot.shot_id}", "mocap.stop_recording")
            result = self.bridge.mocap_stop(request)
            if result.status not in ("applied", "observed"):
                raise StageFailure(
                    ErrorClass.MOCAP_FEEDBACK_UNKNOWN if result.error_class is ErrorClass.MOCAP_FEEDBACK_UNKNOWN
                    else ErrorClass.OPERATION_REJECTED,
                    f"{shot.shot_id}: recording never stopped cleanly: "
                    + (result.message or result.status),
                    evidence=dict(result.result),
                )
            evidence[shot.shot_id] = {"phase": "recorded_unsaved", **_result_evidence(result)}
        return evidence

    def _stage_save_mocap(self, run_id: str, production: ProductionPlan) -> dict:
        evidence: dict[str, object] = {}
        for shot in production.shots:
            timeline = self._load_timeline(run_id, shot.shot_id)
            save_name = timeline.timeline_id
            if self.instance_root is not None and self.expected_world:
                # live proof: the exact target must be free on disk as well
                assert_target_free(self.instance_root, self.expected_world, save_name)
            request = self._request(
                run_id, f"mocap-save-{shot.shot_id}", "mocap.save_recording"
            )
            result = self.bridge.mocap_save(request, save_name)
            if result.status not in ("applied", "observed"):
                raise StageFailure(
                    ErrorClass.MOCAP_FEEDBACK_UNKNOWN if result.error_class is ErrorClass.MOCAP_FEEDBACK_UNKNOWN
                    else ErrorClass.OPERATION_REJECTED,
                    f"{shot.shot_id}: save rejected or unproven: "
                    + (result.message or result.status),
                    evidence=dict(result.result),
                )
            target = self.bridge.recording_path(save_name)
            if target is not None:
                try:
                    artifact = await_artifact(target, attempts=1, sleep_seconds=0.0,
                                              sleeper=lambda _seconds: None)
                except MocapSaveProofError as error:
                    raise StageFailure(ErrorClass.ASSET_MISSING,
                                       f"{shot.shot_id}: {error}", evidence=error.evidence)
                evidence[shot.shot_id] = {"saved": save_name, **artifact}
            else:
                evidence[shot.shot_id] = {"saved": save_name, **_result_evidence(result)}
            if self.backends.replay == "replaymod":
                self.bridge.end_take(run_id, timeline.timeline_id)
        return evidence

    def _stage_await_replay(self, run_id: str, production: ProductionPlan) -> dict:
        if self.backends.replay == "none":
            raise StageSkipped(
                f"no replay backend (replay={self.backends.replay!r}; flashback_automation="
                f"{bool(self.capabilities and self.capabilities.flashback_automation)}); "
                "no replay exists to await. Scope: live-mocap."
            )
        evidence: dict[str, object] = {}
        for shot in production.shots:
            timeline = self._load_timeline(run_id, shot.shot_id)
            request = self._request(
                run_id, f"replay-{shot.shot_id}", "flashback.await_replay_saved"
            )
            saved = self.bridge.await_replay_saved(request, timeline.timeline_id)
            if saved.status != "applied":
                raise StageFailure(
                    ErrorClass.REPLAY_NOT_CREATED,
                    saved.message or "replay missing",
                    evidence=dict(saved.result),
                )
            evidence[shot.shot_id] = dict(saved.result)
        return evidence

    def _assert_live_world(self) -> None:
        """Pre-write gate: truthful in-world identity, exact save, not paused."""

        from .bridge_client import BridgeTransportError

        if not self.expected_world or not self.expected_player:
            raise StageFailure(
                ErrorClass.VALIDATION_FAILED,
                "live mode requires --expect-world and --expect-player",
            )
        try:
            state = self.minecraft.get_status()
        except BridgeTransportError as error:
            raise StageFailure(error.kind, f"game state unavailable: {error}")
        game_state = GameStateV2.model_validate(state)
        refusal = game_state.pre_write_gate(
            expected_save=self.expected_world,
            expected_dimension=self.expected_dimension,
            expected_player=self.expected_player,
        )
        if refusal:
            raise StageFailure(ErrorClass.WORLD_MISMATCH, f"pre-write gate: {refusal}")

    def _stage_apply_camera(self, run_id: str, production: ProductionPlan) -> dict:
        if self.backends.camera == "none":
            raise StageSkipped(
                f"no camera backend (camera={self.backends.camera!r}); "
                "no replay editor to receive a camera track")
        evidence: dict[str, object] = {}
        for shot in production.shots:
            shot_dir = self._run_dir(run_id) / "plans" / "shots" / shot.shot_id
            if not (shot_dir / "camera.json").is_file():
                continue
            camera = CameraTrack.model_validate_json(
                (shot_dir / "camera.json").read_text(encoding="utf-8")
            )
            try:
                preflight_camera(camera, shot)
            except CameraPreflightError as error:
                raise StageFailure(ErrorClass.VALIDATION_FAILED, f"camera {shot.shot_id}: {error}")
            timeline = self._load_timeline(run_id, shot.shot_id)
            request = self._request(run_id, f"camera-{shot.shot_id}", "flashback.replace_camera_track")
            result = self.bridge.replace_camera_track(request, timeline.timeline_id, camera)
            if result.status != "applied":
                raise StageFailure(
                    result.error_class or ErrorClass.EDITOR_NOT_READY,
                    f"{shot.shot_id}: {result.message}",
                )
            evidence[shot.shot_id] = result.result
        return evidence

    def _stage_export(self, run_id: str, production: ProductionPlan) -> dict:
        if self.backends.renderer == "none":
            raise StageSkipped(
                f"no renderer backend (renderer={self.backends.renderer!r}); "
                "exports require a proven replay and a render exit")
        attempt = self.store.next_attempt(run_id, StageName.EXPORT_SHOT)
        evidence: dict[str, object] = {"attempt": attempt}
        for shot in production.shots:
            timeline = self._load_timeline(run_id, shot.shot_id)
            output_relative = self.store.next_output_version(
                shot.shot_id,
                also_taken=lambda rel: (self.workspace_root / rel).is_file(),
            )
            export = ExportPlan(
                export_id=f"{shot.shot_id}-export-v{attempt}",
                shot_id=shot.shot_id,
                timeline_id=timeline.timeline_id,
                replay_ref=timeline.timeline_id,
                range=TickRange(start_tick=0, end_tick=timeline.total_ticks),
                output=production.target,
                output_path=output_relative,
            )
            validate_against_contract(contract_payload(export), "export-plan")
            shot_dir = self._run_dir(run_id) / "plans" / "shots" / shot.shot_id
            self._write_derived(shot_dir / "export-plan.json", export.model_dump(mode="json"))
            request = self._request(run_id, f"export-{shot.shot_id}-v{attempt}", "flashback.start_export")
            result = self.bridge.start_export(
                request,
                timeline_id=timeline.timeline_id,
                range_ticks=(export.range.start_tick, export.range.end_tick),
                output_relative=export.output_path,
                width=production.target.width,
                height=production.target.height,
                fps=production.target.fps,
            )
            if result.status != "applied":
                raise StageFailure(
                    result.error_class or ErrorClass.EXPORT_FAILED,
                    f"{shot.shot_id}: {result.message}",
                )
            self.store.register_artifact(export.output_path, run_id)
            evidence[shot.shot_id] = {"output": export.output_path, **result.result}
        return evidence

    def _stage_inspect(self, run_id: str, production: ProductionPlan) -> dict:
        if self.backends.renderer == "none" and self.backends.replay == "none":
            raise StageSkipped(
                f"no render/replay backend (renderer={self.backends.renderer!r}); "
                "no export output exists to inspect")
        evidence: dict[str, object] = {}
        for shot in production.shots:
            export_path = self._run_dir(run_id) / "plans" / "shots" / shot.shot_id / "export-plan.json"
            if not export_path.is_file():
                raise StageFailure(ErrorClass.EXPORT_FAILED, f"{shot.shot_id}: no export plan")
            export = ExportPlan.model_validate_json(export_path.read_text(encoding="utf-8"))
            video_path = self.workspace_root / export.output_path
            if not video_path.is_file() or video_path.stat().st_size == 0:
                raise StageFailure(ErrorClass.MEDIA_VALIDATION_FAILED,
                                   f"{shot.shot_id}: output missing or empty: {export.output_path}")
            try:
                probe = probe_video(video_path)
            except VideoProbeError as error:
                raise StageFailure(ErrorClass.MEDIA_VALIDATION_FAILED, f"{shot.shot_id}: {error}")
            expected_seconds = export.duration_ticks / 20.0
            video_tracks = [t for t in probe.tracks if t.width or t.height]
            issues: list[str] = []
            if not probe.has_moov:
                issues.append("container has no moov atom")
            if not any(t.fourcc == "avc1" for t in probe.tracks):
                issues.append("no H.264 (avc1) video track")
            if not video_tracks or video_tracks[0].width != production.target.width \
                    or video_tracks[0].height != production.target.height:
                issues.append("resolution does not match the production target")
            if probe.duration_seconds is None or probe.duration_seconds < expected_seconds * 0.8:
                issues.append("duration shorter than the exported range")
            if issues:
                raise StageFailure(ErrorClass.MEDIA_VALIDATION_FAILED,
                                   f"{shot.shot_id}: " + "; ".join(issues),
                                   evidence={"probe": probe.model_dump()})
            evidence[shot.shot_id] = {
                "output": export.output_path,
                "duration_seconds": probe.duration_seconds,
                "resolution": f"{video_tracks[0].width}x{video_tracks[0].height}",
                "codec": video_tracks[0].fourcc,
                "sha256": file_hash(video_path),
            }
            # Real-artifact acceptance (workflow v3 §7): when ffprobe exists it
            # upgrades the box-walk check to an actual decode-level verdict.
            try:
                media_report = verify_render(
                    video_path,
                    expected_width=production.target.width,
                    expected_height=production.target.height,
                    expected_fps=float(production.target.fps),
                    expected_min_duration_seconds=expected_seconds * 0.8,
                    expected_duration_seconds=expected_seconds if self.mode == "live" else None,
                    expected_frames=round(expected_seconds * production.target.fps) if self.mode == "live" else None,
                    require_decode=self.mode == "live",
                    structural_only=self.mode == "simulation",
                    ffmpeg_path=self.workspace_root / "tools/ffmpeg/bin/ffmpeg.exe" if self.mode == "live" else None,
                    ffprobe_path=self.workspace_root / "tools/ffmpeg/bin/ffprobe.exe" if self.mode == "live" else None,
                )
            except MediaValidationError as error:
                raise StageFailure(
                    ErrorClass.MEDIA_VALIDATION_FAILED,
                    f"{shot.shot_id}: {error}",
                    evidence={"probe": probe.model_dump(),
                              "media_report": error.report.model_dump()},
                )
            evidence[shot.shot_id]["decoder"] = media_report.decoder
            if media_report.raw_notes:
                evidence[shot.shot_id]["media_notes"] = media_report.raw_notes
        return evidence

    # -- helpers -------------------------------------------------------------

    def _stage_hash(self, run_id: str, stage: StageName) -> str:
        """Stage input identity.

        Plain stages hash their plan. Export and inspect additionally hash a
        `retry_seed`: the attempt number of the latest failed export/inspect
        record. A succeeded pair therefore keeps a stable hash (later resumes
        skip), while any export/media failure moves the seed and forces a
        fresh export on a new output version — never a re-record.
        """

        base: dict[str, object] = {"stage": stage.value, "plan_hash": self._plan_hash_of(run_id)}
        if stage in (StageName.EXPORT_SHOT, StageName.INSPECT_MEDIA):
            seed = 0
            for record in self.store.stages(run_id):
                if (
                    record.stage in (StageName.EXPORT_SHOT, StageName.INSPECT_MEDIA)
                    and record.status is StageStatus.FAILED
                ):
                    seed = max(seed, record.attempt)
            base["retry_seed"] = seed
        return plan_hash(base)

    def _record(self, run_id, stage, attempt, status, input_hash, error_class, message, evidence) -> StageRecord:
        record = StageRecord(
            run_id=run_id,
            stage=stage,
            attempt=attempt,
            status=status,
            input_hash=input_hash,
            evidence=evidence or {},
            error_class=error_class,
            message=message,
            recorded_at=datetime.now(UTC),
        )
        self.store.record_stage(record)
        if self.mode == "live":
            self._write_durable(self._run_dir(run_id) / "operations" / f"{stage.value}-{attempt}.json",
                {"status": status.value, "stage": stage.value, "attempt": attempt,
                 "input_hash": input_hash, "recorded_at": record.recorded_at.isoformat()})
        if status is StageStatus.FAILED:
            self._set_state(run_id, "failed")
        return record

    def _halt(self, run_id, stage, error_class, message) -> dict:
        return {"ok": False, "run_id": run_id, "stage": stage.value,
                "error_class": error_class.value, "message": message}

    def _run_id_for(self, production: ProductionPlan, plan_hash_value: str) -> str:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        return f"{stamp}-{production.production_id}-{plan_hash_value[7:15]}"

    def _request(self, run_id: str, operation: str, method: str) -> OperationRequest:
        return OperationRequest(
            run_id=run_id,
            operation_id=f"{run_id}-{operation}",
            idempotency_key=f"{run_id}/{operation}",
            plan_hash=self._plan_hash_of(run_id),
            method=method,
        )

    def _run_dir(self, run_id: str) -> Path:
        return self.runs_root / run_id

    def _load_production(self, run_id: str) -> ProductionPlan:
        path = self._run_dir(run_id) / "production.json"
        return ProductionPlan.model_validate_json(path.read_text(encoding="utf-8"))

    def _plan_hash_of(self, run_id: str) -> str:
        preview = json.loads((self._run_dir(run_id) / "preview.json").read_text(encoding="utf-8"))
        return preview["plan_hash"]  # type: ignore[no-any-return]

    def _load_timeline(self, run_id: str, shot_id: str) -> TimelinePlan:
        path = self._run_dir(run_id) / "plans" / "shots" / shot_id / "timeline.json"
        return TimelinePlan.model_validate_json(path.read_text(encoding="utf-8"))

    def _load_camera(self, path: Path) -> CameraTrack:
        raw = json.loads(path.read_text(encoding="utf-8"))
        validate_against_contract(raw, "camera-track")
        return CameraTrack.model_validate(raw)

    def _load_scene_plan(self, path: Path) -> ScenePlan:
        raw = json.loads(path.read_text(encoding="utf-8"))
        validate_against_contract(raw, "scene-plan")
        return ScenePlan.model_validate(raw)

    def _write_new(self, path: Path, payload: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, default=str)
            stream.write("\n")

    def _write_derived(self, path: Path, payload: object) -> None:
        """Derived intermediates may be regenerated on retry (atomic replace).

        Run *inputs* (production.json, preview.json) stay write-once; only
        controller-owned derived plans may be replaced, and only with content
        derived from the same immutable inputs.
        """

        import os

        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(f".{path.name}.tmp")
        with temp.open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, default=str)
            stream.write("\n")
        replace_evidence(temp,path)

    def _write_durable(self, path: Path, payload: object) -> None:
        import os
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".json.tmp")
        with temp.open("w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        replace_evidence(temp,path)

    def _write_run_inputs(self, run_id: str, preview: PlanPreview) -> None:
        run_dir = self._run_dir(run_id)
        self._write_new(run_dir / "production.json", preview.production.model_dump(mode="json"))
        self._write_new(
            run_dir / "preview.json",
            {
                "plan_hash": preview.plan_hash,
                "scene_plan_hashes": preview.scene_plan_hashes,
                "warnings": preview.warnings,
            },
        )
        for scene in preview.production.scenes:
            if not scene.blueprint_ref:
                continue
            scene_dir = run_dir / "plans" / "scenes" / scene.scene_id
            scene_dir.mkdir(parents=True, exist_ok=True)
            source = (self.workspace_root / scene.blueprint_ref).read_bytes()
            # copy with a fresh name; never touch the blueprint itself
            (scene_dir / "scene-plan.json").write_bytes(source)

    def _set_state(self, run_id: str, state: str) -> None:
        with self.store._connection as connection:  # noqa: SLF001 (same-package store)
            connection.execute(
                "UPDATE runs SET state = ?, updated_at = ? WHERE run_id = ?",
                (state, datetime.now(UTC).isoformat(), run_id),
            )

    def _world_for(self, production: ProductionPlan, shot: ShotPlan) -> str:
        return self._scene_of(production, shot).world_ref

    @staticmethod
    def _scene_of(production: ProductionPlan, shot: ShotPlan):
        for scene in production.scenes:
            if scene.scene_id == shot.scene_id:
                return scene
        raise StageFailure(ErrorClass.VALIDATION_FAILED, f"shot {shot.shot_id} references unknown scene")

    def status(self, run_id: str) -> dict[str, object]:
        run = self.store.get_run(run_id)
        return {
            "run": run,
            "stages": [record.model_dump(mode="json") for record in self.store.stages(run_id)],
        }


def _result_evidence(result) -> dict[str, object]:
    """Bridge result payload for stage evidence (v1 and v2 results alike)."""

    return dict(getattr(result, "result", {}) or {})


def _resolve_uncertain(adapter, command, result):
    """Shared uncertain-outcome resolution (same rule as ProductionWorkflow)."""

    if result.status != "uncertain":
        return result
    observed = adapter.read_state(command)
    if observed.get("confirmed") is True:
        return result.model_copy(update={"status": "applied", "observed_state": observed,
                                         "message": f"{result.message} (resolved applied via state read)"})
    return result.model_copy(update={"status": "failed", "observed_state": observed,
                                     "message": f"{result.message} (state read shows not applied)"})
