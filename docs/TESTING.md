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
.\gradlew.bat check
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
## 2026-10-08 — JSON film assembly regression

The v10 assembly recipe pins eight chapter manifests, 15 distinct MP4 chapter sources and one lossless FLAC soundtrack. The FLAC decoded PCM hash matches the original continuous soundtrack. On the source project, the new CLI produced both 510-second, 1920×1080, 30 fps films with hashes exactly matching the delivered v10 clean and subtitle movies. Full decode, CFR, black interval, 23,908 audio packet timestamps and identical encoded audio in both editions passed. A deliberately changed chapter hash was rejected before output creation. This verifies assembly from accepted chapter media, not Minecraft replay rendering after a character change.

The portable public release copy was run independently with `examples/film-assembly-v10.json` and explicit local FFmpeg paths; it produced the same two v10 SHA-256 values and passed all the same media checks. Its Python suite exited successfully with 334 passed and 7 skipped (the optional media tests need FFmpeg/ffprobe on PATH).

The v10 video is a draft retained as workflow evidence and requires substantial creative reconstruction. Hash equality and technical media checks only confirm faithful reproduction of that draft. Further film testing and acceptance are deferred.

The recast example was built twice with distinct output names after fixing ZIP member timestamps. Both generated resource packs had the same SHA-256, `0fa003346f506f79726b143a929497d6be02a07edd63d561d845867b73c479c8`. This proves deterministic pack construction; the example pack has not been visually accepted inside Minecraft.

## 2026-10-09 — master recipe migration

The public checkout's complete `agent/tests` suite exited 0 with FFmpeg/ffprobe on PATH, including the media overlay smoke test and a shot-change dependency test. `cinematic-bridge/gradlew.bat check --offline` passed. `film-master-preview` on `assets/productions/v10-master-draft-20261009/master-plan.json` resolved 68 pinned shots as fresh, eight chapters as requiring rebuild, and the film as waiting for chapters. This is an offline dependency and input-hash check; the complete 510-second `film-master-run` and live Minecraft re-render were deferred with the draft film's reconstruction. The external NicoRTX school pack is deliberately absent from this public repository and required for live re-rendering.

## 2026-10-31 分支拆分验证

去除影片资产后的Python回归：354 passed、24 skipped（缺少部分外部媒体条件）。Bridge构建在当前Mac的Java25环境启动失败：Gradle 8.10.2报告Unsupported class file major version 69；需使用文档规定的Java21重新运行。本轮未修改Bridge Java源码，不将环境失败写成构建通过或实机验收。
