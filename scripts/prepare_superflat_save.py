"""Create an isolated 1.21.1 creative superflat save from a pinned level.dat.

Only the new save directory is written. The template is read-only; no region,
player, entity, Mocap, replay, or other production data is copied.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import time
from pathlib import Path

import nbtlib


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_save(template: Path, saves_root: Path, world_name: str, seed: int) -> dict[str, object]:
    if not world_name or world_name in {".", ".."} or any(
        token in world_name for token in ("/", "\\", ":")
    ):
        raise SystemExit("world name must be one plain folder name")
    template = template.resolve(strict=True)
    saves_root = saves_root.resolve(strict=True)
    if not template.is_file() or template.name.lower() != "level.dat":
        raise SystemExit("template must be an existing level.dat file")

    target = saves_root / world_name
    stage = saves_root / f".{world_name}.bootstrap"
    if target.exists():
        raise SystemExit(f"refusing to overwrite an existing save: {target}")
    if stage.exists():
        raise SystemExit(f"refusing to reuse an existing staging path: {stage}")
    if target.resolve(strict=False).parent != saves_root:
        raise SystemExit("target save escaped the explicit saves root")

    nbt = nbtlib.load(template)
    data = nbt["Data"]
    world_gen = data["WorldGenSettings"]
    dimensions = world_gen["dimensions"]
    overworld = dimensions["minecraft:overworld"]
    layers = nbtlib.List[nbtlib.Compound](
        [
            nbtlib.Compound({"block": nbtlib.String("minecraft:bedrock"), "height": nbtlib.Int(1)}),
            nbtlib.Compound({"block": nbtlib.String("minecraft:dirt"), "height": nbtlib.Int(2)}),
            nbtlib.Compound({"block": nbtlib.String("minecraft:grass_block"), "height": nbtlib.Int(1)}),
        ]
    )
    settings = nbtlib.Compound(
        {
            "biome": nbtlib.String("minecraft:plains"),
            "features": nbtlib.Byte(0),
            "lakes": nbtlib.Byte(0),
            "layers": layers,
            "structure_overrides": nbtlib.List[nbtlib.String]([]),
        }
    )
    overworld["generator"] = nbtlib.Compound(
        {"type": nbtlib.String("minecraft:flat"), "settings": settings}
    )
    world_gen["seed"] = nbtlib.Long(seed)
    world_gen["generate_features"] = nbtlib.Byte(0)
    world_gen["bonus_chest"] = nbtlib.Byte(0)

    data["LevelName"] = nbtlib.String(world_name)
    data["GameType"] = nbtlib.Int(1)
    data["allowCommands"] = nbtlib.Byte(1)
    data["hardcore"] = nbtlib.Byte(0)
    data["initialized"] = nbtlib.Byte(1)
    data["SpawnX"] = nbtlib.Int(0)
    # The four layers start at the 1.21.1 Overworld minimum Y (-64).
    surface_y = -64 + sum(int(layer["height"]) for layer in layers)
    data["SpawnY"] = nbtlib.Int(surface_y)
    data["SpawnZ"] = nbtlib.Int(0)
    data["SpawnAngle"] = nbtlib.Float(0.0)
    data["Time"] = nbtlib.Long(0)
    data["DayTime"] = nbtlib.Long(1000)
    data["LastPlayed"] = nbtlib.Long(time.time_ns() // 1_000_000)
    data["Difficulty"] = nbtlib.Byte(0)
    data["DifficultyLocked"] = nbtlib.Byte(1)
    rules = data.setdefault("GameRules", nbtlib.Compound())
    for rule in ("doMobSpawning", "doPatrolSpawning", "doTraderSpawning", "doInsomnia",
                 "doDaylightCycle", "doWeatherCycle"):
        rules[rule] = nbtlib.String("false")
    data["raining"] = nbtlib.Byte(0)
    data["thundering"] = nbtlib.Byte(0)
    data["rainTime"] = nbtlib.Int(0)
    data["thunderTime"] = nbtlib.Int(0)

    for transient in ("Player", "DragonFight", "CustomBossEvents", "ScheduledEvents"):
        data.pop(transient, None)
    data["DataPacks"] = nbtlib.Compound(
        {
            "Enabled": nbtlib.List[nbtlib.String]([nbtlib.String("vanilla")]),
            "Disabled": nbtlib.List[nbtlib.String]([]),
        }
    )

    stage.mkdir()
    try:
        nbt.save(stage / "level.dat", gzipped=True)
        # Reload before publication to prove the staged NBT is parseable and exact.
        saved = nbtlib.load(stage / "level.dat")
        saved_data = saved["Data"]
        saved_generator = saved_data["WorldGenSettings"]["dimensions"]["minecraft:overworld"]["generator"]
        if (
            str(saved_data["LevelName"]) != world_name
            or int(saved_data["GameType"]) != 1
            or str(saved_generator["type"]) != "minecraft:flat"
            or int(saved_data["SpawnY"]) != surface_y
            or int(saved_data["Difficulty"]) != 0
            or int(saved_data["DifficultyLocked"]) != 1
            or any(str(saved_data["GameRules"][rule]) != "false" for rule in
                   ("doMobSpawning", "doPatrolSpawning", "doTraderSpawning", "doInsomnia",
                    "doDaylightCycle", "doWeatherCycle"))
        ):
            raise RuntimeError("staged level.dat failed identity or superflat read-back")
        os.replace(stage, target)
    except Exception:
        if stage.resolve(strict=False).parent == saves_root:
            shutil.rmtree(stage)
        raise

    level_dat = target / "level.dat"
    return {
        "world_name": world_name,
        "save_path": str(target),
        "template_path": str(template),
        "template_level_dat_sha256": sha256(template),
        "new_level_dat_sha256": sha256(level_dat),
        "seed": seed,
        "game_mode": "creative",
        "generator": "minecraft:flat",
        "flat_layers_bottom_to_top": [
            ["minecraft:bedrock", 1],
            ["minecraft:dirt", 2],
            ["minecraft:grass_block", 1],
        ],
        "surface_y": surface_y,
        "difficulty": "peaceful",
        "difficulty_locked": True,
        "game_rules": {rule: str(value) for rule, value in rules.items()},
        "copied_world_regions": False,
        "copied_player_data": False,
        "copied_mocap_or_replay_data": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template-level-dat", type=Path, required=True)
    parser.add_argument("--saves-root", type=Path, required=True)
    parser.add_argument("--world-name", required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--evidence-out", type=Path)
    args = parser.parse_args()
    result = build_save(args.template_level_dat, args.saves_root, args.world_name, args.seed)
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.evidence_out:
        evidence_path = args.evidence_out.resolve(strict=False)
        if evidence_path.exists() or not evidence_path.parent.is_dir():
            raise SystemExit("evidence output must be a new file under an existing directory")
        with evidence_path.open("x", encoding="utf-8", newline="\n") as evidence_file:
            evidence_file.write(rendered)
    print(rendered, end="")


if __name__ == "__main__":
    main()
