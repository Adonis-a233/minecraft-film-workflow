"""Deterministic offline launcher for the project's Minecraft instance.

Builds the java command directly from the version JSON — no GUI launcher,
no guessed paths. Explicit inputs only:

  --version-dir   active PCL version directory (default: the pinned baseline)
  --username      offline player name (default CineProbe)
  --log           stdout/stderr capture path (never overwritten)

This is operations tooling, gated behind the user's explicit approval to
launch the game. It performs no network authentication: single-player
offline rules apply (uuid derived from the offline name).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
import uuid as uuid_lib
from pathlib import Path

JAVA = Path(r"C:\Users\27303\.jdks\ms-21.0.10\bin\java.exe")
DEFAULT_VERSION_DIR = Path(r"C:\Users\27303\AppData\Roaming\.minecraft\versions\1.21.1-Fabric 0.19.3")
DOT_MINECRAFT = Path(r"C:\Users\27303\AppData\Roaming\.minecraft")


def _rule_applies(rule: dict) -> bool:
    os_rule = rule.get("os")
    if os_rule:
        name = os_rule.get("name")
        if name and name != "windows":
            return False
    if rule.get("features"):
        # Optional features (demo world, quick play) are never enabled here.
        return False
    return True


def library_allowed(rules: list[dict] | None) -> bool:
    """Standard Mojang rule semantics: later matching rules win; explicit
    allow-rules for other operating systems leave the default (deny)."""

    if not rules:
        return True
    allowed = False
    for rule in rules:
        if _rule_applies(rule):
            action = rule.get("action")
            if action == "allow":
                allowed = True
            elif action == "disallow":
                allowed = False
    return allowed


def resolve(library: dict, libraries_root: Path, errors: list[str]) -> Path | None:
    downloads = library.get("downloads", {})
    artifact = downloads.get("artifact")
    if not artifact:
        return None
    relative = artifact["path"]
    path = libraries_root / relative
    if not path.is_file():
        errors.append(f"missing library file: {relative}")
        return None
    return path


def substitute(template: str, values: dict[str, str]) -> str:
    for key, value in values.items():
        template = template.replace("${" + key + "}", value)
    return template


def build_command(
    version_dir: Path,
    username: str,
    *,
    quick_play_singleplayer: str | None = None,
    working_dir: Path | None = None,
) -> tuple[list[str], dict[str, Path | str]]:
    spec = json.loads((version_dir / f"{version_dir.name}.json").read_text(encoding="utf-8"))
    libraries_root = DOT_MINECRAFT / "libraries"
    natives_dir = version_dir / f"{version_dir.name}-natives"
    errors: list[str] = []

    classpath: list[str] = []
    for library in spec.get("libraries", []):
        if not library_allowed(library.get("rules")):
            continue
        artifact = library.get("downloads", {}).get("artifact")
        if artifact is not None:
            path = libraries_root / artifact["path"]
            if not path.is_file():
                errors.append(f"missing library file: {artifact['path']}")
            else:
                classpath.append(str(path))
            continue
        # Fabric-style entries: maven coordinates only ("group:artifact:version").
        # The launcher (PCL) pre-downloads them into the shared libraries root.
        name = library.get("name", "")
        parts = name.split(":")
        if len(parts) != 3:
            continue
        group, artifact_id, version = parts
        relative = f"{group.replace('.', '/')}/{artifact_id}/{version}/{artifact_id}-{version}.jar"
        path = libraries_root / relative
        if not path.is_file():
            errors.append(f"missing maven-coordinate library: {relative}")
        else:
            classpath.append(str(path))
    version_jar = version_dir / f"{version_dir.name}.jar"
    if not version_jar.is_file():
        errors.append(f"missing version jar: {version_jar}")
    else:
        classpath.append(str(version_jar))

    if errors:
        raise SystemExit("classpath incomplete:\n  " + "\n  ".join(errors))

    # Vanilla offline UUID: v3 over "OfflinePlayer:<name>" with a nil namespace.
    offline_uuid = uuid_lib.uuid3(uuid_lib.UUID(int=0), "OfflinePlayer:" + username)
    asset_index = spec.get("assetIndex", {}).get("id", "17")
    values = {
        "auth_player_name": username,
        "version_name": spec["id"],
        "game_directory": str((working_dir or version_dir).resolve()),
        "assets_root": str(DOT_MINECRAFT / "assets"),
        "assets_index_name": asset_index,
        "auth_uuid": str(offline_uuid),
        "auth_access_token": "0",
        "clientid": "0",
        "auth_xuid": "0",
        "user_type": "legacy",
        "natives_directory": str(natives_dir),
        "launcher_name": "minecraft-film-project",
        "launcher_version": "0.1.0",
        "classpath": ";".join(classpath),
        "user_properties": "{}",
        "version_type": spec.get("type", "release"),
        "resolution_width": "1280",
        "resolution_height": "720",
    }

    command: list[str] = [str(JAVA), "-Xmx4G"]
    for arg in spec.get("arguments", {}).get("jvm", []):
        if isinstance(arg, str):
            command.append(substitute(arg, values))
        else:
            if library_allowed(arg.get("rules")):
                value = arg.get("value", [])
                if isinstance(value, str):
                    value = [value]
                command.extend(substitute(a, values) for a in value)
    command.append(spec["mainClass"])
    for arg in spec.get("arguments", {}).get("game", []):
        if isinstance(arg, str):
            command.append(substitute(arg, values))
        else:
            if library_allowed(arg.get("rules")):
                value = arg.get("value", [])
                if isinstance(value, str):
                    value = [value]
                command.extend(substitute(a, values) for a in value)
    if quick_play_singleplayer is not None:
        if (
            not quick_play_singleplayer.strip()
            or quick_play_singleplayer in {".", ".."}
            or any(separator in quick_play_singleplayer for separator in ("/", "\\", ":"))
        ):
            raise SystemExit("--quick-play-singleplayer must be a world folder name, not a path")
        command.extend(("--quickPlaySingleplayer", quick_play_singleplayer))
    unresolved = [part for part in command if "${" in part]
    if unresolved:
        raise SystemExit(f"unresolved placeholders (unsupported features?): {unresolved}")
    return command, {"natives": natives_dir, "main_class": spec["mainClass"]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version-dir", type=Path, default=DEFAULT_VERSION_DIR)
    parser.add_argument(
        "--working-dir", type=Path,
        help="game directory (saves/config/mods root). Defaults to --version-dir; "
             "bind a candidate instance explicitly instead of relying on the default.",
    )
    parser.add_argument("--username", default="CineProbe")
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument(
        "--quick-play-singleplayer",
        help="open this exact world folder on startup (Minecraft Quick Play)",
    )
    parser.add_argument(
        "--require-mod", action="append", default=[],
        help="jar filename that MUST exist in <version-dir>/mods before launch "
             "(repeatable; launch fails closed when any is missing)",
    )
    parser.add_argument(
        "--max-runtime-seconds", type=float,
        help="deterministic shutdown: terminate the game after this many seconds "
             "(unattended render runs); without it the game runs until it exits",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    version_dir = args.version_dir.resolve()
    working_dir = args.working_dir.resolve() if args.working_dir else version_dir
    missing_mods = [
        name for name in args.require_mod
        if not (working_dir / "mods" / name).is_file()
    ]
    if missing_mods:
        raise SystemExit(
            "required mods missing in " + str(working_dir / "mods") + ":\n  "
            + "\n  ".join(missing_mods)
        )

    command, paths = build_command(
        version_dir, args.username,
        quick_play_singleplayer=args.quick_play_singleplayer,
        working_dir=working_dir,
    )
    if args.dry_run:
        classpath_flag = next(
            (index for index, part in enumerate(command[:-1]) if part in {"-cp", "-classpath", "--class-path"}),
            None,
        )
        classpath_entries = (
            len(command[classpath_flag + 1].split(";"))
            if classpath_flag is not None
            else 0
        )
        print("classpath entries:", classpath_entries)
        print("natives:", paths["natives"])
        print("main:", paths["main_class"])
        print("working dir:", working_dir)
        print("quick play singleplayer:", args.quick_play_singleplayer or "disabled")
        return

    args.log.parent.mkdir(parents=True, exist_ok=True)
    process_env = os.environ.copy()
    process_env["MINECRAFT_FILM_PROJECT_ROOT"] = str(Path(__file__).resolve().parents[1])
    ffmpeg_dir=Path(__file__).resolve().parents[1]/"tools/ffmpeg/bin"
    if (ffmpeg_dir/"ffmpeg.exe").is_file():
        process_env["PATH"] = str(ffmpeg_dir) + os.pathsep + process_env.get("PATH", "")
    with args.log.open("a", encoding="utf-8", errors="replace") as log:
        process = subprocess.Popen(
            command,
            stdout=log,
            stderr=subprocess.STDOUT,
            cwd=str(working_dir),
            env=process_env,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,  # type: ignore[attr-defined]
        )
    print(f"launched pid={process.pid} log={args.log}")
    try:
        if args.max_runtime_seconds is not None:
            code = process.wait(timeout=args.max_runtime_seconds)
            print(f"game exited within budget: code={code}")
        else:
            time.sleep(2)
            if process.poll() is not None:
                raise SystemExit(
                    f"game exited immediately (code {process.returncode}); see {args.log}"
                )
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=30)
        print(f"game terminated at the {args.max_runtime_seconds}s budget "
              f"(pid={process.pid}); log={args.log}")


if __name__ == "__main__":
    main()
