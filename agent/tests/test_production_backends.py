"""Backend-neutral photography chain (workflow v3 §5/§8).

The controller must never branch on a mod brand: Recorder/Replay/Camera/
Renderer are named backends, 'none' means fail closed, and the v3 capability
advertisement is the source. Contract 2 advertisements map onto the same
view without any change in behavior.
"""

from __future__ import annotations

from minecraft_film_agent.production_models import (
    CapabilitiesV2,
    CapabilitiesV3,
    ProductionBackends,
)


def _v2(*, flashback: bool = False, mocap: bool = True) -> CapabilitiesV2:
    return CapabilitiesV2(
        minecraft="1.21.1", fabric_loader="0.19.3", flashback="0.39.8",
        mocap="1.3.10", bridge="0.1.0",
        typed_world_ops=True, world_reads=True,
        mocap_state_machine=mocap, tick_scheduler=True,
        flashback_automation=flashback,
        flashback_disabled_reason="" if flashback else "license-gated",
    )


def test_v2_capabilities_map_to_neutral_backends() -> None:
    backends = ProductionBackends.from_capabilities(_v2())
    assert backends.recorder == "mocap"
    assert backends.replay == "none"
    assert backends.camera == "none"
    assert backends.renderer == "none"
    assert set(backends.unavailable()) == {"replay", "camera", "renderer"}


def test_enabled_flashback_maps_replay_and_camera_to_flashback() -> None:
    backends = ProductionBackends.from_capabilities(_v2(flashback=True))
    assert backends.replay == "flashback"
    assert backends.camera == "flashback"
    assert backends.renderer == "none"  # flashback never advertised rendering here
    assert backends.unavailable() == ["renderer"]


def test_v3_capabilities_carry_the_names_directly() -> None:
    capabilities = CapabilitiesV3(
        minecraft="1.21.1", fabric_loader="0.19.3", flashback="0.39.8",
        mocap="1.3.10", bridge="0.1.0",
        typed_world_ops=True, world_reads=True,
        mocap_state_machine=True, tick_scheduler=True,
        flashback_automation=False, flashback_disabled_reason="license",
        recorder_backend="mocap", replay_backend="replaymod",
        camera_backend="replaymod", render_backend="replaymod",
        async_world_writes=True, persistent_journal=True,
    )
    backends = ProductionBackends.from_capabilities(capabilities)
    assert backends.recorder == "mocap"
    assert backends.replay == "replaymod"
    assert backends.camera == "replaymod"
    assert backends.renderer == "replaymod"
    assert backends.unavailable() == []


def test_v3_view_derives_from_v2_without_inventing_capabilities() -> None:
    derived = CapabilitiesV3.from_v2(_v2())
    assert derived.recorder_backend == "mocap"
    assert derived.replay_backend == "none"  # flashback gated → stays closed
    assert derived.render_backend == "none"
    assert derived.async_world_writes is True
    assert derived.persistent_journal is True
    derived_enabled = CapabilitiesV3.from_v2(_v2(flashback=True))
    assert derived_enabled.replay_backend == "flashback"
    assert derived_enabled.render_backend == "none"


def test_backends_default_to_none() -> None:
    backends = ProductionBackends()
    assert set(backends.unavailable()) == {"recorder", "replay", "camera", "renderer"}
