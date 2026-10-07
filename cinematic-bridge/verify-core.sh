#!/usr/bin/env bash
# Offline verification of the cinematic-bridge pure core (no Minecraft, no Gradle).
# Compiles every class that does not import Fabric/Minecraft and runs the
# dependency-free test runners. Requires a JDK 21 (JAVA_HOME or PATH).
set -euo pipefail
cd "$(dirname "$0")/.."

JAVAC="${JAVA_HOME:+$JAVA_HOME/bin/javac}"; JAVAC="${JAVAC:-javac}"
JAVA="${JAVA_HOME:+$JAVA_HOME/bin/java}"; JAVA="${JAVA:-java}"
OUT="work/temp/cinema-classes"

rm -rf "$OUT"
mkdir -p "$OUT"

# MC-facing classes are excluded; everything else must compile standalone.
find cinematic-bridge/src/main/java -name '*.java' ! -name 'CinematicBridgeMod.java' ! -name 'ReplayModBinding.java' > work/temp/cinema-sources.txt
"$JAVAC" -encoding UTF-8 -d "$OUT" @work/temp/cinema-sources.txt
"$JAVAC" -encoding UTF-8 -cp "$OUT" -d "$OUT" \
  cinematic-bridge/src/test/java/dev/mcfilm/cinematicbridge/CoreTests.java \
  cinematic-bridge/src/test/java/dev/mcfilm/cinematicbridge/HttpBridgeTests.java \
  cinematic-bridge/src/test/java/dev/mcfilm/cinematicbridge/FixtureTests.java \
  cinematic-bridge/src/test/java/dev/mcfilm/cinematicbridge/V2CoreTests.java \
  cinematic-bridge/src/test/java/dev/mcfilm/cinematicbridge/V3CoreTests.java \
  cinematic-bridge/src/test/java/dev/mcfilm/cinematicbridge/ReplayArtifactTests.java \
  cinematic-bridge/src/test/java/dev/mcfilm/cinematicbridge/ReplayMutationTests.java
  cinematic-bridge/src/test/java/dev/mcfilm/cinematicbridge/ActorPlanTests.java

"$JAVA" -cp "$OUT" dev.mcfilm.cinematicbridge.CoreTests
"$JAVA" -cp "$OUT" dev.mcfilm.cinematicbridge.HttpBridgeTests
"$JAVA" -cp "$OUT" dev.mcfilm.cinematicbridge.FixtureTests contracts/v2
"$JAVA" -cp "$OUT" dev.mcfilm.cinematicbridge.V2CoreTests contracts/v2
"$JAVA" -cp "$OUT" dev.mcfilm.cinematicbridge.V3CoreTests
"$JAVA" -cp "$OUT" dev.mcfilm.cinematicbridge.ReplayArtifactTests
"$JAVA" -cp "$OUT" dev.mcfilm.cinematicbridge.ReplayMutationTests
"$JAVA" -cp "$OUT" dev.mcfilm.cinematicbridge.ActorPlanTests
echo "cinematic-bridge core verified offline"
