from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from mcp.server import MCPServer

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
from .models import ScenePlan
from .production import ProductionController
from .production_models import ProductionPlan
from .store import ProductionStore
from .workflow import ProductionWorkflow


def _workspace() -> Path:
    configured = os.environ.get("MINECRAFT_FILM_PROJECT_ROOT")
    return Path(configured).resolve() if configured else Path.cwd().resolve()


def create_server(workspace_root: Path | None = None) -> MCPServer:
    workflow = ProductionWorkflow(workspace_root or _workspace())
    server = MCPServer("minecraft-film-production")

    @server.tool()
    def validate_production_plan(plan: dict[str, Any]) -> dict[str, Any]:
        """Preview a whole-film ProductionPlan offline: contracts, blueprints,
        timelines, camera preflight and action-asset resolution. Read-only —
        never writes, never executes. Commit and execution stay CLI-only."""
        controller = ProductionController(
            workspace_root,
            ProductionStore(workspace_root),
            minecraft=MockMinecraftAdapter(),
            bridge=MockCinemaBridge(workspace_root),
            registry=ActionRegistry(workspace_root),
        )
        preview = controller.preview(ProductionPlan.model_validate(plan))
        return {
            "ready": preview.ready,
            "plan_hash": preview.plan_hash,
            "issues": preview.issues,
            "asset_missing": preview.asset_missing,
            "warnings": preview.warnings,
            "scene_plan_hashes": preview.scene_plan_hashes,
        }

    @server.tool()
    def validate_scene_plan(plan: dict[str, Any]) -> dict[str, Any]:
        """Validate a ScenePlan and compile safe commands without writing or executing."""
        validated = workflow.validate(ScenePlan.model_validate(plan))
        return validated.model_dump(mode="json")

    @server.tool()
    def prepare_scene_plan(plan: dict[str, Any]) -> dict[str, Any]:
        """Create an auditable run in validated state; execution remains blocked."""
        manifest = workflow.prepare(ScenePlan.model_validate(plan))
        return manifest.model_dump(mode="json")

    @server.tool()
    def get_production_run(run_id: str) -> dict[str, Any]:
        """Read one run manifest."""
        return workflow.get_run(run_id).model_dump(mode="json")

    @server.tool()
    def execute_approved_dry_run(run_id: str) -> dict[str, Any]:
        """Execute an already human-approved run offline; never contacts Minecraft."""
        manifest = workflow.execute(run_id, DryRunMinecraftAdapter())
        return manifest.model_dump(mode="json")

    @server.tool()
    def inspect_environment(
        expect_world: str | None = None,
        expect_player: str | None = None,
    ) -> dict[str, Any]:
        """Capture a read-only environment snapshot via the in-game bridge.

        Requires MINECRAFT_FILM_BRIDGE_ENDPOINT and MINECRAFT_FILM_BRIDGE_TOKEN.
        The bridge is loopback-only, the call is GET-only, and no game state is
        modified. The snapshot is saved as immutable evidence under work/snapshots.
        """
        try:
            config = resolve_bridge_config(
                endpoint=os.environ.get("MINECRAFT_FILM_BRIDGE_ENDPOINT"),
                api_key=os.environ.get("MINECRAFT_FILM_BRIDGE_TOKEN"),
            )
        except BridgeConfigError as error:
            return {"ok": False, "kind": "not_configured", "error": str(error)}
        inspector = McpServerRestInspector(config)
        try:
            snapshot = inspector.inspect_environment()
        except BridgeError as error:
            return {"ok": False, "kind": error.kind, "error": str(error)}
        check = check_environment(
            snapshot, expect_world=expect_world, expect_player=expect_player
        )
        saved = save_environment_snapshot(workflow.workspace_root, snapshot)
        return {
            "ok": check["ok"],
            "check": check,
            "snapshot": json.loads(snapshot.model_dump_json()),
            "saved_to": str(saved),
        }

    return server


def main() -> None:
    create_server().run()


if __name__ == "__main__":
    main()

