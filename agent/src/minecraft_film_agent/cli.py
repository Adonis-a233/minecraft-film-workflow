from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from .actions import ActionRegistry
from .adapters import DryRunMinecraftAdapter, McpServerRestInspector
from .adapters.cinema_mock import MockCinemaBridge
from .adapters.mock import MockMinecraftAdapter
from .bridge import (
    BridgeConfigError,
    BridgeError,
    check_environment,
    resolve_bridge_config,
    save_environment_snapshot,
)
from .bridge_client import CinematicBridgeClient, CinematicBridgeConfig, BridgeTransportError, runtime_check
from .compiler import PlanValidationError
from .film_assembly import FilmAssemblyError, assemble as assemble_film, preflight as preflight_film
from .mocap import MocapLibrary
from .models import ScenePlan
from .production import ProductionController
from .production_models import ErrorClass, ProductionPlan
from .store import ProductionStore
from .video import VideoProbeError, probe_video
from .workflow import ProductionWorkflow


def _load_plan(path: Path) -> ScenePlan:
    return ScenePlan.model_validate_json(path.read_text(encoding="utf-8"))


def _print(payload: object) -> None:
    if hasattr(payload, "model_dump"):
        payload = payload.model_dump(mode="json")
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="minecraft-film-agent")
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="validate and compile a plan")
    validate.add_argument("plan", type=Path)

    prepare = subparsers.add_parser("prepare", help="create an auditable run")
    prepare.add_argument("plan", type=Path)
    prepare.add_argument("--run-id")
    prepare.add_argument(
        "--mocap-dir", type=Path,
        help="world save directory; when given, Mocap name conflicts block prepare",
    )

    approve = subparsers.add_parser("approve", help="record explicit human approval")
    approve.add_argument("run_id")
    approve.add_argument("--by", required=True)

    execute = subparsers.add_parser(
        "execute-dry-run", help="execute through the offline no-op adapter"
    )
    execute.add_argument("run_id")

    show = subparsers.add_parser("show", help="show a run manifest")
    show.add_argument("run_id")

    inspect = subparsers.add_parser(
        "inspect-environment",
        help="capture a read-only environment snapshot from the in-game bridge",
    )
    inspect.add_argument("--endpoint", required=True,
                         help="bridge base URL, loopback only (e.g. http://127.0.0.1:8081)")
    inspect.add_argument("--api-key-env", default="MINECRAFT_FILM_BRIDGE_TOKEN",
                         help="environment variable holding the bridge API key")
    inspect.add_argument("--api-key-file", type=Path,
                         help="alternative to --api-key-env: file containing the key")
    inspect.add_argument("--timeout", type=float, default=5.0)
    inspect.add_argument("--expect-world")
    inspect.add_argument("--expect-player")
    inspect.add_argument("--out", type=Path, help="snapshot output path (never overwritten)")

    check = subparsers.add_parser(
        "check-mocap",
        help="check a plan against the Mocap library of a world save (read-only)",
    )
    check.add_argument("plan", type=Path)
    check.add_argument("--mocap-dir", type=Path, required=True,
                       help="world save directory containing mocap_files/")

    verify = subparsers.add_parser(
        "verify-video",
        help="technically validate an exported video file (codec/size/duration)",
    )
    verify.add_argument("video", type=Path)
    verify.add_argument("--expect-codec")
    verify.add_argument("--expect-width", type=int)
    verify.add_argument("--expect-height", type=int)
    verify.add_argument("--expect-min-duration", type=float,
                        help="minimum duration in seconds")

    prod_validate = subparsers.add_parser(
        "production-validate",
        help="preview a whole-film ProductionPlan; pure validation, no writes",
    )
    prod_validate.add_argument("plan", type=Path)
    prod_validate.add_argument("--actions-dir", type=Path)

    prod_run = subparsers.add_parser(
        "production-run",
        help="commit the previewed plan with human approval and execute the full chain offline",
    )
    prod_run.add_argument("plan", type=Path)
    prod_run.add_argument("--run-id", required=True)
    prod_run.add_argument("--by", required=True, help="human approver recorded in the audit trail")
    prod_run.add_argument("--actions-dir", type=Path)
    prod_run.add_argument("--mocap-dir", type=Path,
                          help="world save directory; enables Mocap conflict checks")

    prod_resume = subparsers.add_parser(
        "production-resume",
        help="resume a production run from its last checkpoint; completed stages never re-execute",
    )
    prod_resume.add_argument("run_id")
    prod_resume.add_argument("--token-env", default="CINEMATIC_BRIDGE_TOKEN")
    prod_resume.add_argument("--token-file", type=Path)

    prod_show = subparsers.add_parser(
        "production-show", help="show a production run and its stage records"
    )
    prod_show.add_argument("run_id")

    check_assets = subparsers.add_parser(
        "check-assets",
        help="resolve a plan's action references against the ActionRegistry (read-only)",
    )
    check_assets.add_argument("plan", type=Path)
    check_assets.add_argument("--actions-dir", type=Path)

    bridge_check = subparsers.add_parser(
        "bridge-check",
        help="live read-only gate check against the in-game cinematic bridge "
             "(handshake, versions, capabilities, game state; writes nothing)",
    )
    bridge_check.add_argument("--endpoint", default="http://127.0.0.1:25575")
    bridge_check.add_argument("--token-env", default="CINEMATIC_BRIDGE_TOKEN")
    bridge_check.add_argument("--token-file", type=Path,
                              help="alternative to --token-env: file containing the session token")
    bridge_check.add_argument("--timeout", type=float, default=5.0)

    prod_live = subparsers.add_parser(
        "production-run-live",
        help="commit and execute a plan against the REAL game over contract-2 "
             "(explicit paths only; there is no fallback to simulation)",
    )
    prod_live.add_argument("plan", type=Path)
    prod_live.add_argument("--run-id", required=True)
    prod_live.add_argument("--by", required=True, help="human approver recorded in the audit trail")
    prod_live.add_argument("--endpoint", default="http://127.0.0.1:25575")
    prod_live.add_argument("--token-env", default="CINEMATIC_BRIDGE_TOKEN")
    prod_live.add_argument("--token-file", type=Path)
    prod_live.add_argument("--timeout", type=float, default=5.0)
    prod_live.add_argument("--instance-dir", type=Path, required=True,
                           help="Minecraft instance root (game/instances/...); saves live under saves/")
    prod_live.add_argument("--expect-world", required=True,
                           help="exact integrated-save name that must be proven before writes")
    prod_live.add_argument("--expect-dimension", default="minecraft:overworld")
    prod_live.add_argument("--expect-player", required=True)
    prod_live.add_argument("--actions-dir", type=Path)
    schematic = subparsers.add_parser("inspect-schematic", help="inspect a Sponge v2/v3 schematic without writes")
    schematic.add_argument("source", type=Path)
    asset = subparsers.add_parser("register-asset", help="preserve and register an original asset")
    asset.add_argument("record", type=Path)
    asset.add_argument("source", type=Path)
    importer = subparsers.add_parser("import-schematic", help="import verified blocks through contract-3 keep writes")
    importer.add_argument("asset_id")
    importer.add_argument("--run-id", required=True)
    importer.add_argument("--expect-world", required=True)
    importer.add_argument("--expect-player", required=True)
    importer.add_argument("--origin", type=int, nargs=3, required=True)
    importer.add_argument("--build-region", type=Path, required=True)
    importer.add_argument("--evidence-dir", type=Path, required=True)
    importer.add_argument("--endpoint", default="http://127.0.0.1:25575")
    importer.add_argument("--token-env", default="CINEMATIC_BRIDGE_TOKEN")
    importer.add_argument("--token-file", type=Path)
    importer.add_argument("--timeout", type=float, default=5.0)
    edit = subparsers.add_parser("edit-execute", help="assemble, decode and publish a validated edit")
    edit.add_argument("edit", type=Path)
    edit.add_argument("--evidence-dir", type=Path, required=True)
    edit.add_argument("--ffmpeg", type=Path, required=True)
    edit.add_argument("--ffprobe", type=Path, required=True)
    delivery = subparsers.add_parser("delivery-execute", help="assemble accepted exports with master provenance and safe resume")
    delivery.add_argument("input", type=Path, help="JSON object containing edit and exports")
    delivery.add_argument("--instance-dir", type=Path, required=True)
    delivery.add_argument("--evidence-dir", type=Path, required=True)
    delivery.add_argument("--ffmpeg", type=Path, required=True)
    delivery.add_argument("--ffprobe", type=Path, required=True)
    for name, help_text in (("film-assembly-preview", "validate chapter/audio hashes and output paths without writes"),
                            ("film-assembly-run", "assemble and verify both whole-film editions from a JSON recipe")):
        film = subparsers.add_parser(name, help=help_text)
        film.add_argument("recipe", type=Path)
        film.add_argument("--ffmpeg", type=Path, required=True)
        film.add_argument("--ffprobe", type=Path, required=True)
    return parser


def _load_production(path: Path) -> ProductionPlan:
    return ProductionPlan.model_validate_json(path.read_text(encoding="utf-8"))


def _build_controller(
    workspace_root: Path,
    *,
    actions_dir: Path | None = None,
    mocap_dir: Path | None = None,
) -> ProductionController:
    """Offline simulation controller: no game process is ever contacted."""

    return ProductionController(
        workspace_root,
        ProductionStore(workspace_root),
        minecraft=MockMinecraftAdapter(),
        bridge=MockCinemaBridge(workspace_root),
        registry=ActionRegistry(workspace_root, actions_root=actions_dir),
        mocap_dir=mocap_dir,
    )


def _resolve_token(args: argparse.Namespace) -> str:
    token = os.environ.get(args.token_env)
    if not token and getattr(args, "token_file", None):
        token = args.token_file.read_text(encoding="utf-8").strip()
    if not token:
        raise BridgeTransportError(
            ErrorClass.AUTHENTICATION_FAILED,
            f"no bridge token: set {args.token_env} or pass --token-file",
        )
    return token


def _union_build_region(workspace_root: Path, production) -> dict[str, object] | None:
    """Bounding box of every blueprint's declared build_region (a safe
    superset; Java revalidates every write against it independently)."""

    from .compiler import validate_and_compile

    boxes: list[tuple[int, int, int, int, int, int]] = []
    for scene in production.scenes:
        if not scene.blueprint_ref:
            continue
        plan = ScenePlan.model_validate_json(
            (workspace_root / scene.blueprint_ref).read_text(encoding="utf-8")
        )
        validate_and_compile(plan)
        (min_x, max_x, min_y, max_y, min_z, max_z) = plan.build_region.bounds
        boxes.append((min_x, max_x, min_y, max_y, min_z, max_z))
    if not boxes:
        return None
    return {
        "start": {"x": min(b[0] for b in boxes), "y": min(b[2] for b in boxes),
                  "z": min(b[4] for b in boxes)},
        "end": {"x": max(b[1] for b in boxes), "y": max(b[3] for b in boxes),
                "z": max(b[5] for b in boxes)},
    }


def _live_context(args: argparse.Namespace, workspace_root: Path, run_id: str, plan_hash: str):
    """Handshake → capabilities → game state → manifest → live controller."""

    production = _load_production(args.plan)
    controller = _build_live_controller(
        workspace_root,
        run_id=run_id,
        plan_hash=plan_hash,
        production=production,
        endpoint=args.endpoint,
        timeout=args.timeout,
        instance_root=args.instance_dir.resolve(),
        expect_world=args.expect_world,
        expect_dimension=args.expect_dimension,
        expect_player=args.expect_player,
        actions_dir=getattr(args, "actions_dir", None),
        approved_by=args.by,
        token=_resolve_token(args),
    )
    manifest = {
        "run_id": run_id,
        "mode": "live",
        "plan_hash": plan_hash,
        "approved_by": args.by,
        "endpoint": args.endpoint,
        "instance_dir": str(args.instance_dir.resolve()),
        "expected_world": args.expect_world,
        "expected_dimension": args.expect_dimension,
        "expected_player": args.expect_player,
        "versions": controller.capabilities_data["versions"],
        "capabilities": controller.capabilities.model_dump(mode="json", exclude_none=True),
        "game_state": controller.capabilities_data["game_state"],
        "recordings_dir": str(controller.instance_root / "saves" / args.expect_world
                               / "mocap_files" / "recordings"),
        "recorded_at": datetime.now(UTC).isoformat(),
        "token": "REDACTED",
    }
    manifest_path = workspace_root / "work" / "runs" / run_id / "live-manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with manifest_path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(manifest, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    return controller


def _live_context_from_manifest(
    manifest_path: Path, args: argparse.Namespace, workspace_root: Path
) -> ProductionController:
    """Rebuild the live controller for a crashed run from its manifest."""

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return _build_live_controller(
        workspace_root,
        run_id=manifest["run_id"],
        plan_hash=manifest["plan_hash"],
        production=ProductionPlan.model_validate_json(
            (manifest_path.parent / "production.json").read_text(encoding="utf-8")
        ),
        endpoint=manifest["endpoint"],
        timeout=args.timeout,
        instance_root=Path(manifest["instance_dir"]),
        expect_world=manifest["expected_world"],
        expect_dimension=manifest["expected_dimension"],
        expect_player=manifest["expected_player"],
        actions_dir=None,
        approved_by=manifest["approved_by"],
        token=_resolve_token(args),
    )


def _build_live_controller(
    workspace_root: Path,
    *,
    run_id: str,
    plan_hash: str,
    production,
    endpoint: str,
    timeout: float,
    instance_root: Path,
    expect_world: str,
    expect_dimension: str,
    expect_player: str,
    actions_dir: Path | None,
    approved_by: str,
    token: str,
) -> ProductionController:
    """Handshake → capabilities → game-state gate → controller. Fails closed
    BEFORE the first write on any drift; there is no simulation fallback."""

    from .adapters.live import LiveMinecraftAdapter
    from .bridge_client import (
        BridgeTransportError,
        CinematicBridgeClient,
        CinematicBridgeConfig,
        version_mismatches_v2,
    )
    from .mocap_live import recordings_dir

    if not instance_root.is_dir():
        raise BridgeTransportError(
            ErrorClass.ENVIRONMENT_MISMATCH, f"instance dir does not exist: {instance_root}"
        )
    recordings = recordings_dir(instance_root, expect_world)
    client = CinematicBridgeClient(
        CinematicBridgeConfig(endpoint=endpoint, token=token, timeout_seconds=timeout),
        recording_root=recordings,
    )

    versions = client.handshake()
    mismatches = version_mismatches_v2(versions)
    if mismatches:
        raise BridgeTransportError(ErrorClass.ENVIRONMENT_MISMATCH, "; ".join(mismatches))
    capabilities = client.capabilities_v3(run_id)
    game_state = client.game_state(run_id)
    refusal = game_state.pre_write_gate(
        expected_save=expect_world,
        expected_dimension=expect_dimension,
        expected_player=expect_player,
    )
    if refusal:
        raise BridgeTransportError(
            ErrorClass.WORLD_MISMATCH,
            f"pre-write gate before any write: {refusal}",
        )

    adapter = LiveMinecraftAdapter(
        client,
        run_id=run_id,
        build_region=_union_build_region(workspace_root, production) or {},
        expected_save=expect_world,
        expected_dimension=expect_dimension,
        expected_player=expect_player,
    )
    controller = ProductionController(
        workspace_root,
        ProductionStore(workspace_root),
        minecraft=adapter,
        bridge=client,
        registry=ActionRegistry(workspace_root, actions_root=actions_dir),
        mocap_dir=recordings.parent.parent,
        mode="live",
        capabilities=capabilities,
        expected_world=expect_world,
        expected_dimension=expect_dimension,
        expected_player=expect_player,
        instance_root=instance_root,
    )
    controller.capabilities_data = {
        "versions": versions.model_dump(mode="json"),
        "game_state": game_state.model_dump(mode="json"),
    }
    return controller


def _production_run_live(args: argparse.Namespace, workspace_root: Path) -> dict[str, object]:
    from .contracts import (
        contract_payload,
        plan_hash as canonical_plan_hash,
        preview_commit_guard,
    )

    production = _load_production(args.plan)
    run_id = args.run_id
    preview_hash = canonical_plan_hash(contract_payload(production))
    controller = _live_context(args, workspace_root, run_id, preview_hash)
    preview = controller.preview(production)
    # The committed plan must be exactly the one hashed into the manifest.
    preview_commit_guard(preview_hash, preview.plan_hash)
    controller.commit(preview, args.by, run_id)
    result = controller.execute(run_id)
    return result


def _inspect_environment(args: argparse.Namespace, workspace_root: Path) -> dict[str, object]:
    api_key = os.environ.get(args.api_key_env)
    config = resolve_bridge_config(
        endpoint=args.endpoint,
        api_key=api_key,
        api_key_file=args.api_key_file,
        timeout_seconds=args.timeout,
    )
    inspector = McpServerRestInspector(config)
    snapshot = inspector.inspect_environment()
    check = check_environment(
        snapshot, expect_world=args.expect_world, expect_player=args.expect_player
    )
    saved = save_environment_snapshot(
        workspace_root, snapshot, out_path=args.out
    )
    return {
        "ok": check["ok"],
        "check": check,
        "snapshot": json.loads(snapshot.model_dump_json()),
        "saved_to": str(saved),
    }


def _mocap_report(mocap_dir: Path, plan: ScenePlan) -> dict[str, object]:
    library = MocapLibrary(mocap_dir)
    manifest = library.scan()
    issues = library.conflicts(plan)
    return {
        "ok": not issues,
        "conflicts": issues,
        "manifest": manifest.model_dump(),
    }


def _verify_video(args: argparse.Namespace) -> dict[str, object]:
    probe = probe_video(args.video)
    expectations: list[dict[str, object]] = []
    tracks = [track for track in probe.tracks if track.width or track.height]
    video_track = tracks[0] if tracks else None
    if args.expect_codec:
        expectations.append({
            "expect_codec": args.expect_codec,
            "met": any(track.fourcc == args.expect_codec for track in probe.tracks),
        })
    if args.expect_width is not None:
        expectations.append({
            "expect_width": args.expect_width,
            "met": video_track is not None and video_track.width == args.expect_width,
        })
    if args.expect_height is not None:
        expectations.append({
            "expect_height": args.expect_height,
            "met": video_track is not None and video_track.height == args.expect_height,
        })
    if args.expect_min_duration is not None:
        expectations.append({
            "expect_min_duration": args.expect_min_duration,
            "met": probe.duration_seconds is not None
            and probe.duration_seconds >= args.expect_min_duration,
        })
    return {
        "ok": all(item["met"] for item in expectations) if expectations else probe.has_moov,
        "probe": probe.model_dump(),
        "expectations": expectations,
    }


def _bridge_check(args: argparse.Namespace) -> dict[str, object]:
    token = _resolve_token(args)
    client = CinematicBridgeClient(
        CinematicBridgeConfig(endpoint=args.endpoint, token=token, timeout_seconds=args.timeout)
    )
    return runtime_check(client)


def main() -> None:
    args = build_parser().parse_args()
    workflow = ProductionWorkflow(args.workspace)
    try:
        if args.command == "inspect-schematic":
            from .schematic import inspect_schematic
            _print(inspect_schematic(args.source))
        elif args.command == "register-asset":
            from .assets import register_asset
            _print(register_asset(workflow.workspace_root, json.loads(args.record.read_text(encoding="utf-8")), args.source))
        elif args.command == "import-schematic":
            from .importer import import_schematic
            client = CinematicBridgeClient(CinematicBridgeConfig(endpoint=args.endpoint, token=_resolve_token(args), timeout_seconds=args.timeout))
            _print(import_schematic(workspace=workflow.workspace_root, client=client, asset_id=args.asset_id, run_id=args.run_id,
                world=args.expect_world, player=args.expect_player, origin=tuple(args.origin),
                build_region=json.loads(args.build_region.read_text(encoding="utf-8")), evidence_dir=args.evidence_dir, data_version=3955))
        elif args.command == "edit-execute":
            from .edit import execute_edit
            _print(execute_edit(json.loads(args.edit.read_text(encoding="utf-8")), workspace=workflow.workspace_root,
                evidence_dir=args.evidence_dir, ffmpeg=args.ffmpeg, ffprobe=args.ffprobe))
        elif args.command == "delivery-execute":
            from .delivery import assemble_delivery
            inputs=json.loads(args.input.read_text(encoding="utf-8"))
            _print(assemble_delivery(inputs['edit'], exports=inputs['exports'], workspace=workflow.workspace_root,
                instance=args.instance_dir, evidence_dir=args.evidence_dir, ffmpeg=args.ffmpeg, ffprobe=args.ffprobe))
        elif args.command == "validate":
            _print(workflow.validate(_load_plan(args.plan)))
        elif args.command == "prepare":
            if getattr(args, "mocap_dir", None):
                report = _mocap_report(args.mocap_dir, _load_plan(args.plan))
                if not report["ok"]:
                    _print(report)
                    raise SystemExit(2)
            _print(workflow.prepare(_load_plan(args.plan), args.run_id))
        elif args.command == "approve":
            _print(workflow.approve(args.run_id, args.by))
        elif args.command == "execute-dry-run":
            _print(workflow.execute(args.run_id, DryRunMinecraftAdapter()))
        elif args.command == "show":
            _print(workflow.get_run(args.run_id))
        elif args.command == "inspect-environment":
            _print(_inspect_environment(args, workflow.workspace_root))
        elif args.command == "check-mocap":
            report = _mocap_report(args.mocap_dir, _load_plan(args.plan))
            _print(report)
            if not report["ok"]:
                raise SystemExit(2)
        elif args.command == "verify-video":
            report = _verify_video(args)
            _print(report)
            if not report["ok"]:
                raise SystemExit(2)
        elif args.command == "production-validate":
            controller = _build_controller(
                workflow.workspace_root, actions_dir=getattr(args, "actions_dir", None)
            )
            preview = controller.preview(_load_production(args.plan))
            _print({
                "ready": preview.ready,
                "plan_hash": preview.plan_hash,
                "issues": preview.issues,
                "asset_missing": preview.asset_missing,
                "warnings": preview.warnings,
                "scene_plan_hashes": preview.scene_plan_hashes,
            })
            if not preview.ready:
                raise SystemExit(2)
        elif args.command == "production-run":
            controller = _build_controller(
                workflow.workspace_root,
                actions_dir=getattr(args, "actions_dir", None),
                mocap_dir=getattr(args, "mocap_dir", None),
            )
            preview = controller.preview(_load_production(args.plan))
            run_id = controller.commit(preview, args.by, args.run_id)
            result = controller.execute(run_id)
            _print(result)
            if not result["ok"]:
                raise SystemExit(2)
        elif args.command == "production-resume":
            manifest = (
                workflow.workspace_root / "work" / "runs" / args.run_id / "live-manifest.json"
            )
            if manifest.is_file():
                context = _live_context_from_manifest(manifest, args, workflow.workspace_root)
                result = context.execute(args.run_id)
            else:
                controller = _build_controller(workflow.workspace_root)
                result = controller.execute(args.run_id)
            _print(result)
            if not result["ok"]:
                raise SystemExit(2)
        elif args.command == "production-run-live":
            result = _production_run_live(args, workflow.workspace_root)
            _print(result)
            if not result["ok"]:
                raise SystemExit(2)
        elif args.command == "production-show":
            controller = _build_controller(workflow.workspace_root)
            _print(controller.status(args.run_id))
        elif args.command == "bridge-check":
            report = _bridge_check(args)
            _print(report)
            if not report["ok"]:
                raise SystemExit(2)
        elif args.command == "check-assets":
            registry = ActionRegistry(
                workflow.workspace_root, actions_dir=getattr(args, "actions_dir", None)
            )
            production = _load_production(args.plan)
            refs = sorted({
                actor.action_ref
                for scene in production.scenes
                for shot in scene.shots
                for actor in shot.actors
            })
            report = registry.resolve(refs)
            _print({
                "ok": report.ok,
                **report.model_dump(mode="json"),
                "checklist": ActionRegistry.recording_checklist(report.missing),
            })
            if not report.ok:
                raise SystemExit(2)
        elif args.command in ("film-assembly-preview", "film-assembly-run"):
            recipe = json.loads(args.recipe.read_text(encoding="utf-8"))
            action = preflight_film if args.command == "film-assembly-preview" else assemble_film
            _print(action(recipe, root=workflow.workspace_root,
                          ffmpeg=args.ffmpeg.resolve(), ffprobe=args.ffprobe.resolve()))
    except (ValidationError, PlanValidationError, ValueError, RuntimeError, OSError) as error:
        _print({"ok": False, "error": str(error)})
        raise SystemExit(2) from error


if __name__ == "__main__":
    main()

