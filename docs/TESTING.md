# Verification

## Clean Python setup

Run scripts/bootstrap.ps1 from a fresh clone. The script installs a managed Python 3.12 runtime with uv, syncs the exact uv.lock, runs the full Python suite and checks the installed CLI.

Release-staging result on 2026-10-07:

- uv sync --locked --all-groups --python 3.12: passed.
- Python tests: 334 passed, 7 skipped in 17.33 seconds on CPython 3.12.13.
- minecraft-film-agent --help: passed.
- No Minecraft client was launched by this test.

All seven skips were media checks that require FFmpeg/ffprobe, which are not bundled; no failure was reported. The source checkout used a different interpreter and reported 337 passed, 4 skipped, with media tooling available to a subset of checks.

## Java bridge

Build and verify with the included Gradle Wrapper:

~~~powershell
cd cinematic-bridge
.gradlew.bat check
~~~

A successful build verifies compilation and offline Java tests only. It does not prove the installed mod set, world, camera recording or video output works on another computer.

Release-staging result on 2026-10-07:

- Gradle Wrapper downloaded and ran Gradle 8.10.2.
- The bridge test was pointed at the included final v12 character pack.
- Gradle check: BUILD SUCCESSFUL, 20 actionable tasks.
- The run used JDK 21.0.10 and fetched the pinned ReplayMod API through Modrinth Maven.

## Sample assets

The two v10 MP4 files were checked against their recorded SHA-256 values in the source project. Their recorded technical verification passed full video/audio decoding and constant-frame-rate checks. The full-film visual review is scoped and has not been presented as exhaustive frame-by-frame inspection or final audio/user acceptance.

The distributed world ZIP is a map-data copy assembled from level.dat, region, entities, POI and the Nether/End region folders. Playerdata, advancements, statistics, session locks, local configuration, logs, and old backup files are excluded.
