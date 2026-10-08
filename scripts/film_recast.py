"""Prepare a compatible character resource pack for a v10 film recast.

This tool deliberately stops before replay export. A finished MP4 cannot be
reskinned, and the v10 shot/export recipes are not yet a single executable plan.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ROLES = frozenset({"a", "zhou", "teacher", "chen", "elder", "filmer", "safety"})
PACK_PREFIX = "assets/kanjian2/models/actor/"
PALETTE = "assets/kanjian2/textures/actor/palette.png"
ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,47}$")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def local_path(raw: str, *, must_exist: bool) -> Path:
    if not isinstance(raw, str) or not raw or "\\" in raw:
        raise ValueError("paths must be project-relative POSIX paths")
    candidate = Path(raw)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError("absolute and parent paths are forbidden")
    resolved = (ROOT / candidate).resolve()
    if not resolved.is_relative_to(ROOT):
        raise ValueError("path leaves project root")
    if must_exist and not resolved.is_file():
        raise ValueError(f"missing input: {raw}")
    return resolved


def read_recipe(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or set(data) != {"schema_version", "recast_id", "base_pack", "replacements", "output_pack"}:
        raise ValueError("recipe fields must be schema_version, recast_id, base_pack, replacements, output_pack")
    if data["schema_version"] != 1 or not isinstance(data["recast_id"], str) or not ID_PATTERN.fullmatch(data["recast_id"]):
        raise ValueError("invalid schema_version or recast_id")
    if not isinstance(data["replacements"], dict) or not data["replacements"]:
        raise ValueError("replacements must name at least one role")
    output = f"assets/resourcepacks/recasts/{data['recast_id']}.zip"
    if data["output_pack"] != output:
        raise ValueError(f"output_pack must be {output}")
    return data


def inventory(pack: Path, role: str) -> tuple[dict[str, bytes], bytes]:
    with zipfile.ZipFile(pack) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError(f"duplicate ZIP members in {pack.name}")
        if any(name.startswith("/") or "\\" in name or ".." in Path(name).parts for name in names):
            raise ValueError(f"unsafe ZIP member in {pack.name}")
        prefix = f"{PACK_PREFIX}{role}/"
        models = {name[len(prefix):]: archive.read(name) for name in names if name.startswith(prefix) and name.endswith(".json")}
        if not models or PALETTE not in names:
            raise ValueError(f"{pack.name} lacks actor {role} models or palette")
        return models, archive.read(PALETTE)


def preview(recipe: dict) -> dict:
    base = local_path(recipe["base_pack"], must_exist=True)
    output = local_path(recipe["output_pack"], must_exist=False)
    if base.suffix.lower() != ".zip" or not zipfile.is_zipfile(base):
        raise ValueError("base_pack must be a resource-pack ZIP")
    plan = []
    for target, replacement in sorted(recipe["replacements"].items()):
        if target not in ROLES or not isinstance(replacement, dict) or set(replacement) != {"pack", "source_role"}:
            raise ValueError(f"invalid replacement for role {target}")
        source_role = replacement["source_role"]
        if source_role not in ROLES:
            raise ValueError(f"invalid source_role for {target}")
        source = local_path(replacement["pack"], must_exist=True)
        if source.suffix.lower() == ".png":
            raise ValueError("ordinary skin PNG is not compatible with the film's articulated model pack")
        if source.suffix.lower() != ".zip" or not zipfile.is_zipfile(source):
            raise ValueError("replacement pack must be a compatible resource-pack ZIP")
        expected, _ = inventory(base, target)
        actual, _ = inventory(source, source_role)
        if set(expected) != set(actual):
            raise ValueError(f"{target}: donor model files differ; missing={sorted(set(expected)-set(actual))}, extra={sorted(set(actual)-set(expected))}")
        for filename, raw in actual.items():
            model = json.loads(raw)
            if not isinstance(model, dict) or not model.get("elements"):
                raise ValueError(f"{target}/{filename}: missing model elements")
            if set(model.get("textures", {}).values()) - {"kanjian2:actor/palette"}:
                raise ValueError(f"{target}/{filename}: unsupported texture reference")
        plan.append({"role": target, "source_role": source_role, "source_pack": replacement["pack"], "source_sha256": sha256(source.read_bytes()), "model_files": len(actual)})
    # The current film uses repeated event inserts and editorial composites.
    # Conservatively invalidate every story scene until shot-level dependencies
    # are represented by an executable master recipe.
    return {"status": "pack_ready_film_export_not_automated", "recast_id": recipe["recast_id"],
            "base_pack": recipe["base_pack"], "base_sha256": sha256(base.read_bytes()),
            "output_pack": recipe["output_pack"], "output_exists": output.exists(), "replacements": plan,
            "scenes_requiring_new_render": [f"S{i:02d}" for i in range(1, 8)],
            "blocking_step": "v10 replay/camera/shot/edit recipes are not consolidated into one executable film plan"}


def build(recipe: dict, report: dict) -> dict:
    base = local_path(recipe["base_pack"], must_exist=True)
    output = local_path(recipe["output_pack"], must_exist=False)
    if output.exists():
        raise ValueError("refusing to overwrite existing pack")
    changed: dict[str, bytes] = {}
    for item in report["replacements"]:
        target, donor_role = item["role"], item["source_role"]
        donor = local_path(item["source_pack"], must_exist=True)
        if sha256(donor.read_bytes()) != item["source_sha256"]:
            raise ValueError(f"source pack changed after preview: {item['source_pack']}")
        models, palette = inventory(donor, donor_role)
        texture_name = f"kanjian2:actor/recast_{target}"
        changed[f"assets/kanjian2/textures/actor/recast_{target}.png"] = palette
        for filename, raw in models.items():
            model = json.loads(raw)
            model["textures"] = {key: texture_name if value == "kanjian2:actor/palette" else value
                                 for key, value in model["textures"].items()}
            changed[f"{PACK_PREFIX}{target}/{filename}"] = (json.dumps(model, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(base) as source, zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as target:
            original_names = set(source.namelist())
            if set(changed).difference(original_names) != {f"assets/kanjian2/textures/actor/recast_{item['role']}.png" for item in report["replacements"]}:
                raise ValueError("unexpected target resource-pack layout")
            for member in source.infolist():
                target.writestr(member, changed.pop(member.filename, source.read(member.filename)))
            for name, content in changed.items():
                fixed = zipfile.ZipInfo(filename=name, date_time=(1980, 1, 1, 0, 0, 0))
                target.writestr(fixed, content, compress_type=zipfile.ZIP_DEFLATED)
    except Exception:
        output.unlink(missing_ok=True)
        raise
    return {**report, "output_sha256": sha256(output.read_bytes()), "output_size_bytes": output.stat().st_size}


def main() -> int:
    parser = argparse.ArgumentParser(description="Preview or build a compatible v10 character resource pack")
    parser.add_argument("command", choices=("preview", "build"))
    parser.add_argument("recipe", type=Path)
    args = parser.parse_args()
    try:
        recipe = read_recipe(args.recipe)
        report = preview(recipe)
        if args.command == "build":
            manifest = local_path(f"assets/resourcepacks/recasts/{recipe['recast_id']}.manifest.json", must_exist=False)
            if manifest.exists():
                raise ValueError("refusing to overwrite existing manifest")
            report = build(recipe, report)
            try:
                with manifest.open("x", encoding="utf-8") as stream:
                    json.dump(report, stream, ensure_ascii=False, indent=2)
                    stream.write("\n")
            except Exception:
                local_path(recipe["output_pack"], must_exist=False).unlink(missing_ok=True)
                raise
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, KeyError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
