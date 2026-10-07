import json
from pathlib import Path

import pytest

from minecraft_film_agent.adapters import DryRunMinecraftAdapter
from minecraft_film_agent.models import RunState, ScenePlan
from minecraft_film_agent.workflow import InvalidStateTransition, ProductionWorkflow


def plan() -> ScenePlan:
    return ScenePlan.model_validate(
        {
            "plan_id": "workflow-test",
            "title": "Workflow test",
            "world_name": "Marx Video Test",
            "objective": "Prove approval and audit boundaries",
            "build_region": {
                "start": {"x": 0, "y": 60, "z": 0},
                "end": {"x": 8, "y": 70, "z": 8},
            },
            "actions": [
                {"type": "set_time", "value": 6000},
                {"type": "set_weather", "weather": "clear"},
            ],
        }
    )


def test_execution_requires_approval(tmp_path: Path) -> None:
    workflow = ProductionWorkflow(tmp_path)
    workflow.prepare(plan(), "blocked-run")
    with pytest.raises(InvalidStateTransition):
        workflow.execute("blocked-run", DryRunMinecraftAdapter())


def test_prepare_approve_and_dry_run(tmp_path: Path) -> None:
    workflow = ProductionWorkflow(tmp_path)
    prepared = workflow.prepare(plan(), "complete-run")
    assert prepared.state is RunState.VALIDATED

    approved = workflow.approve("complete-run", "test-user")
    assert approved.state is RunState.APPROVED

    completed = workflow.execute("complete-run", DryRunMinecraftAdapter())
    assert completed.state is RunState.COMPLETED
    assert completed.dry_run is True

    results_path = tmp_path / completed.results_file
    results = [json.loads(line) for line in results_path.read_text().splitlines()]
    assert len(results) == 2
    assert all(result["status"] == "skipped" for result in results)


def test_run_directory_cannot_be_overwritten(tmp_path: Path) -> None:
    workflow = ProductionWorkflow(tmp_path)
    workflow.prepare(plan(), "unique-run")
    with pytest.raises(FileExistsError):
        workflow.prepare(plan(), "unique-run")

