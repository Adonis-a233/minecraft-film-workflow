package dev.mcfilm.cinematicbridge;

import dev.mcfilm.cinematicbridge.json.MiniJson;
import dev.mcfilm.cinematicbridge.mocap.MocapStateMachine;
import dev.mcfilm.cinematicbridge.server.AsyncOperationService;
import dev.mcfilm.cinematicbridge.server.BridgeDispatcher;
import dev.mcfilm.cinematicbridge.server.BridgeHttpServer;
import dev.mcfilm.cinematicbridge.server.ClientThreadExecutor;
import dev.mcfilm.cinematicbridge.server.OperationJournal;
import dev.mcfilm.cinematicbridge.server.PersistentJournal;
import dev.mcfilm.cinematicbridge.state.GameStateV2;
import dev.mcfilm.cinematicbridge.world.WorldOperations;
import dev.mcfilm.cinematicbridge.core.VersionGate;
import dev.mcfilm.cinematicbridge.flash.FlashbackDisabledPort;

import java.io.IOException;
import java.net.HttpURLConnection;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentLinkedQueue;

/**
 * Contract-3 core behavior (workflow v3 §4, P0 gate): persistent journal with
 * crash recovery, async write pipeline that never holds the caller, truthful
 * status (a journaled failure can never be queried back into success), exact
 * fill proofs, tag-identified actors, and a full HTTP v3 round trip.
 * Pure JDK, offline. Run: java V3CoreTests
 */
public final class V3CoreTests {

    private static int passed = 0;
    private static final List<String> failures = new ArrayList<>();

    public static void main(String[] args) throws Exception {
        persistentJournalTests();
        paramsHashTests();
        asyncServiceTests();
        dispatcherV3Tests();
        worldProofTests();
        replayPortTests();
        httpV3Tests();
        System.out.println("passed: " + passed + ", failed: " + failures.size());
        failures.forEach(failure -> System.out.println("FAIL " + failure));
        if (!failures.isEmpty()) {
            System.exit(1);
        }
    }

    // -- persistent journal ------------------------------------------------------

    static void persistentJournalTests() throws IOException {
        Path dir = Files.createTempDirectory("v3-journal-basic");

        PersistentJournal journal = PersistentJournal.open(dir);
        PersistentJournal.Record record = journal.begin("run/op-1", "world.set_time",
            PersistentJournal.paramsHash(Map.of("value", 6000L)));
        check("persistent begin creates ACCEPTED", record.state() == PersistentJournal.State.ACCEPTED);
        journal.markQueued("run/op-1");
        journal.markRunning("run/op-1");
        journal.markSucceeded("run/op-1", Map.of("ok", true, "time_of_day", 6000L));
        journal.begin("run/op-2", "world.fill_keep", "sha256:bad");
        journal.markQueued("run/op-2");
        journal.markRunning("run/op-2");
        journal.markFailed("run/op-2", "operation_failed", "proof mismatch",
            Map.of("ok", false, "reason", "proof mismatch"));

        // Reopen = process restart: terminal records survive with their proof.
        PersistentJournal reopened = PersistentJournal.open(dir);
        PersistentJournal.Record okRecord = reopened.get("run/op-1").orElseThrow();
        check("restart keeps SUCCEEDED", okRecord.state() == PersistentJournal.State.SUCCEEDED);
        check("restart keeps the proof", Long.valueOf(6000L)
            .equals(((Number) okRecord.proof().get("time_of_day")).longValue()));
        PersistentJournal.Record failRecord = reopened.get("run/op-2").orElseThrow();
        check("restart keeps FAILED with error class",
            failRecord.state() == PersistentJournal.State.FAILED
                && "operation_failed".equals(failRecord.errorClass()));

        // Non-terminal at restart → UNKNOWN carrying recovered_from.
        Path dir2 = Files.createTempDirectory("v3-journal-inflight");
        PersistentJournal crashed = PersistentJournal.open(dir2);
        crashed.begin("run/lost", "world.set_time", "sha256:x");
        crashed.markQueued("run/lost");
        PersistentJournal afterCrash = PersistentJournal.open(dir2);
        PersistentJournal.Record lost = afterCrash.get("run/lost").orElseThrow();
        check("interrupted op recovered as UNKNOWN", lost.state() == PersistentJournal.State.UNKNOWN);
        check("recovered_from names the interrupted state",
            "queued".equals(lost.recoveredFrom()));

        // A torn tail line (crash mid-append) is dropped, earlier events survive.
        Path dir3 = Files.createTempDirectory("v3-journal-torn");
        PersistentJournal torn = PersistentJournal.open(dir3);
        torn.begin("run/keep", "world.set_time", "sha256:y");
        torn.markQueued("run/keep");
        torn.markRunning("run/keep");
        torn.markSucceeded("run/keep", Map.of("ok", true));
        Files.write(dir3.resolve(PersistentJournal.FILE_NAME),
            "{\"seq\":99,\"key\":\"run/keep\",\"event\":\"succ".getBytes(StandardCharsets.UTF_8),
            java.nio.file.StandardOpenOption.APPEND);
        PersistentJournal afterTorn = PersistentJournal.open(dir3);
        check("torn tail dropped, terminal record intact",
            afterTorn.get("run/keep").orElseThrow().state() == PersistentJournal.State.SUCCEEDED);

        // Terminal states are final; re-proof of a terminal state is allowed.
        try {
            reopened.markRunning("run/op-1");
            check("SUCCEEDED is terminal", false);
        } catch (IllegalStateException expected) {
            check("SUCCEEDED is terminal", true);
        }
        reopened.markSucceeded("run/op-1", Map.of("ok", true));
        check("idempotent re-proof allowed", true);
    }

    static void paramsHashTests() {
        Map<String, Object> a = new LinkedHashMap<>();
        a.put("value", 6000);
        a.put("build_region", Map.of("end", Map.of("x", 15, "y", 79, "z", 15),
            "start", Map.of("x", 0, "y", 64, "z", 0)));
        Map<String, Object> sameDifferentOrder = new LinkedHashMap<>();
        sameDifferentOrder.put("build_region", Map.of("start", Map.of("z", 0, "y", 64, "x", 0),
            "end", Map.of("z", 15, "y", 79, "x", 15)));
        sameDifferentOrder.put("value", 6000);
        String hashA = PersistentJournal.paramsHash(a);
        check("canonical hash ignores key order",
            hashA.equals(PersistentJournal.paramsHash(sameDifferentOrder)));
        Map<String, Object> different = new LinkedHashMap<>(a);
        different.put("value", 7000);
        check("canonical hash detects different params",
            !hashA.equals(PersistentJournal.paramsHash(different)));
        check("hash is a pinned sha256 string", hashA.startsWith("sha256:") && hashA.length() == 71);
    }

    // -- game-thread gate ----------------------------------------------------------

    /** Parks every submitted task until released; records what ever started. */
    static final class GatedRunner implements ClientThreadExecutor.Runner {
        final ConcurrentLinkedQueue<Runnable> parked = new ConcurrentLinkedQueue<>();
        final ConcurrentLinkedQueue<Runnable> started = new ConcurrentLinkedQueue<>();

        @Override
        public void execute(Runnable task) {
            started.add(task);
            parked.add(task);
        }

        void releaseAll() {
            Runnable task;
            while ((task = parked.poll()) != null) {
                task.run();
            }
        }
    }

    static void asyncServiceTests() throws Exception {
        Path dir = Files.createTempDirectory("v3-journal-async");
        PersistentJournal journal = PersistentJournal.open(dir);
        GatedRunner gate = new GatedRunner();
        ClientThreadExecutor game = new ClientThreadExecutor(gate);
        WorldOperations ops = new WorldOperations(new TagWorld(), game, new OperationJournal(), 60_000);
        AsyncOperationService service = new AsyncOperationService(journal, ops, game, 60_000);

        Map<String, Object> params = new LinkedHashMap<>();
        params.put("value", 6000);
        params.put("build_region", V2CoreTests.region(0, 64, 0, 15, 79, 15));

        long start = System.nanoTime();
        Map<String, Object> accepted = service.submit("world.set_time", params, "run/async-1");
        long elapsedMillis = (System.nanoTime() - start) / 1_000_000;
        check("submit returns accepted without touching the game thread",
            "accepted".equals(accepted.get("status")) && elapsedMillis < 2_000);
        check("submit reply carries the key and a params fingerprint",
            "run/async-1".equals(((Map<?, ?>) accepted.get("result")).get("idempotency_key"))
                && String.valueOf(((Map<?, ?>) accepted.get("result")).get("params_hash"))
                    .startsWith("sha256:"));

        Map<String, Object> pending = service.status("run/async-1");
        check("blocked job reports pending", "pending".equals(pending.get("status")));
        waitFor(() -> !gate.parked.isEmpty());
        check("job reaches the game thread but stays parked", !gate.started.isEmpty()
            && gate.parked.peek() != null);

        gate.releaseAll();
        waitFor(() -> "succeeded".equals(service.status("run/async-1").get("status")));
        Map<String, Object> done = service.status("run/async-1");
        check("completion lands in the journal with proof",
            "succeeded".equals(done.get("status"))
                && Long.valueOf(6000L).equals(timeOfDayProof(done)));

        // Restart: the terminal outcome is still there.
        PersistentJournal reopened = PersistentJournal.open(dir);
        check("restart keeps the async outcome",
            reopened.get("run/async-1").orElseThrow().state() == PersistentJournal.State.SUCCEEDED);

        // Same key, same params → replay, no second execution.
        int startedBefore = gate.started.size();
        Map<String, Object> replay = service.submit("world.set_time", params, "run/async-1");
        check("same key same params replays the recorded outcome",
            "succeeded".equals(replay.get("status"))
                && Boolean.TRUE.equals(((Map<?, ?>) replay.get("result")).get("replayed")));
        check("replay does not execute again", gate.started.size() == startedBefore);

        // Same key, different params → conflict, never a silent resend.
        Map<String, Object> conflicting = new LinkedHashMap<>(params);
        conflicting.put("value", 18_000);
        Map<String, Object> conflict = service.submit("world.set_time", conflicting, "run/async-1");
        check("same key different params is a conflict",
            "rejected".equals(conflict.get("status"))
                && "operation_conflict".equals(conflict.get("error_class")));

        // A refusing runner (no integrated server) is a proven FAILED, not unknown.
        Path dir2 = Files.createTempDirectory("v3-journal-dead");
        PersistentJournal journal2 = PersistentJournal.open(dir2);
        ClientThreadExecutor refusing = new ClientThreadExecutor(task -> {
            throw new IllegalStateException("no integrated server");
        });
        WorldOperations deadOps = new WorldOperations(new TagWorld(), refusing, new OperationJournal(), 60_000);
        AsyncOperationService deadService = new AsyncOperationService(journal2, deadOps, refusing, 60_000);
        Map<String, Object> deadAccepted = deadService.submit("world.set_time", params, "run/async-dead");
        check("refusing runner still gets a fast accept",
            "accepted".equals(deadAccepted.get("status")));
        waitFor(() -> "failed".equals(deadService.status("run/async-dead").get("status")));
        check("refused task ends FAILED with the environment cause",
            "failed".equals(deadService.status("run/async-dead").get("status")));
    }

    // -- dispatcher v3 (lock removal + truthful status) ----------------------------

    static void dispatcherV3Tests() throws Exception {
        // Deadlock regression: while a write is parked on the game thread, a
        // status query must return promptly (v2 held one monitor across both).
        Path dir = Files.createTempDirectory("v3-journal-dispatcher");
        PersistentJournal journal = PersistentJournal.open(dir);
        GatedRunner gate = new GatedRunner();
        ClientThreadExecutor game = new ClientThreadExecutor(gate);
        WorldOperations ops = new WorldOperations(new TagWorld(), game, new OperationJournal(), 60_000);
        AsyncOperationService service = new AsyncOperationService(journal, ops, game, 60_000);
        MocapStateMachine machine = new MocapStateMachine(command -> { });
        BridgeDispatcher dispatcher = new BridgeDispatcher(
            command -> "",
            new FlashbackDisabledPort(),
            () -> GameStateV2.mainMenu().toMap(),
            VersionGate.RuntimeVersions.of("1.21.1", "0.19.3", "0.39.8", "1.3.10"),
            new OperationJournal(), ops, machine, machine::phase, 1, 0,
            journal, service);

        Map<String, Object> params = new LinkedHashMap<>();
        params.put("value", 6000);
        params.put("build_region", V2CoreTests.region(0, 64, 0, 15, 79, 15));
        Map<String, Object> reply = dispatcher.handle("world.set_time", params, 3, "run/dl-1");
        check("contract-3 write is accepted, not awaited",
            "accepted".equals(reply.get("status")) && "run/dl-1".equals(reply.get("idempotency_key")));

        long queryStart = System.nanoTime();
        Map<String, Object> status = dispatcher.handle("bridge.get_operation_status",
            Map.of("idempotency_key", "run/dl-1"), 3, "run/dl-1-status");
        long queryMillis = (System.nanoTime() - queryStart) / 1_000_000;
        check("status query answers while the write is parked on the game thread",
            queryMillis < 2_000 && "pending".equals(status.get("status")));

        waitFor(() -> !gate.parked.isEmpty());
        gate.releaseAll();
        waitFor(() -> "succeeded".equals(
            dispatcher.handle("bridge.get_operation_status",
                Map.of("idempotency_key", "run/dl-1"), 3, "run/dl-1-status").get("status")));
        check("status query shows the late completion",
            "succeeded".equals(dispatcher.handle("bridge.get_operation_status",
                Map.of("idempotency_key", "run/dl-1"), 3, "run/dl-1-status").get("status")));

        // Contract-3 without the async pipeline fails closed.
        BridgeDispatcher v2Only = new BridgeDispatcher(
            command -> "", new FlashbackDisabledPort(),
            () -> GameStateV2.mainMenu().toMap(),
            VersionGate.RuntimeVersions.of("1.21.1", "0.19.3", "0.39.8", "1.3.10"),
            new OperationJournal(), ops, machine, machine::phase, 1, 0);
        Map<String, Object> refused = v2Only.handle("world.set_time", params, 3, "run/dl-2");
        check("contract-3 write without pipeline is rejected, never degraded",
            "rejected".equals(refused.get("status")));

        // v2 false-success regression: a journaled proof failure must answer
        // failed to a later status query (v2 mapped OBSERVED → applied).
        OperationJournal v2Journal = new OperationJournal();
        TagWorld lazyV2World = new TagWorld();
        BridgeDispatcher directReads = new BridgeDispatcher(command -> "", new FlashbackDisabledPort(),
            () -> GameStateV2.mainMenu().toMap(),
            VersionGate.RuntimeVersions.of("1.21.1", "0.19.3", "0.39.8", "1.3.10"),
            new OperationJournal(), new WorldOperations(lazyV2World, ClientThreadExecutor.direct(), new OperationJournal(), 100),
            machine, machine::phase, 1, 0);
        for (String method : List.of("world.get_time", "world.get_weather", "world.get_block")) {
            Map<String,Object> read = directReads.handle(method, V2CoreTests.point(0,64,0), 3, "read/" + method);
            check("v3 read has no legacy journal state: " + method,
                "applied".equals(read.get("status")) && !read.containsKey("journal_state"));
        }
        lazyV2World.fillMode = TagWorld.FillMode.LAZY; // the fill will prove itself failed
        WorldOperations v2Ops = new WorldOperations(lazyV2World,
            ClientThreadExecutor.direct(), v2Journal, 100);
        BridgeDispatcher v2Dispatcher = new BridgeDispatcher(
            command -> "", new FlashbackDisabledPort(),
            () -> GameStateV2.mainMenu().toMap(),
            VersionGate.RuntimeVersions.of("1.21.1", "0.19.3", "0.39.8", "1.3.10"),
            v2Journal, v2Ops, machine, machine::phase, 1, 0);
        Map<String, Object> fillParams = new LinkedHashMap<>();
        fillParams.put("start", V2CoreTests.point(0, 64, 0));
        fillParams.put("end", V2CoreTests.point(1, 64, 1));
        fillParams.put("block", "minecraft:stone");
        fillParams.put("build_region", V2CoreTests.region(0, 64, 0, 15, 79, 15));
        Map<String, Object> failedWrite = v2Dispatcher.handle("world.fill_keep", fillParams, 2,
            "run/v2-fail");
        check("fill that places nothing fails synchronously",
            "failed".equals(failedWrite.get("status")));
        Map<String, Object> queried = v2Dispatcher.handle("bridge.get_operation_status",
            Map.of("idempotency_key", "run/v2-fail"), 2, "run/v2-fail-status");
        check("failed write stays failed in the status query (no fake success)",
            "failed".equals(queried.get("status"))
                && "operation_failed".equals(queried.get("error_class")));
    }

    // -- world proof upgrades --------------------------------------------------------

    /**
     * Fake world that applies commands honestly enough to exercise proofs:
     * keep-fill places exactly the air positions; summon records identities
     * and tags. fillMode=LAZY drops fills entirely — the "silent no-op" the
     * exact proof must catch (and the old weak proof would have passed).
     */
    static final class TagWorld extends V2CoreTests.FakeWorld {
        boolean ready = true;
        @Override public boolean entityPositionReady(int x, int y, int z) { return ready; }
        enum FillMode { HONEST, LAZY }

        FillMode fillMode = FillMode.HONEST;
        final Map<String, String> tagged = new LinkedHashMap<>();
        final List<String> entityUuids = new ArrayList<>();

        @Override
        public void runCommand(String command) {
            commands.add(command);
            if (command.startsWith("fill ")) {
                if (fillMode == FillMode.LAZY) {
                    return;
                }
                String[] parts = command.split(" ");
                int x1 = Integer.parseInt(parts[1]), y1 = Integer.parseInt(parts[2]),
                    z1 = Integer.parseInt(parts[3]);
                int x2 = Integer.parseInt(parts[4]), y2 = Integer.parseInt(parts[5]),
                    z2 = Integer.parseInt(parts[6]);
                String block = parts[7];
                for (int x = Math.min(x1, x2); x <= Math.max(x1, x2); x++) {
                    for (int y = Math.min(y1, y2); y <= Math.max(y1, y2); y++) {
                        for (int z = Math.min(z1, z2); z <= Math.max(z1, z2); z++) {
                            if (blockAt(x, y, z).equals("minecraft:air")) {
                                blocks.put(x + "," + y + "," + z, block);
                            }
                        }
                    }
                }
            } else if (command.startsWith("summon ")) {
                String uuid = "uuid-" + entityUuids.size();
                entityUuids.add(uuid);
                int tagStart = command.indexOf("{Tags:[\"");
                if (tagStart >= 0) {
                    String tag = command.substring(tagStart + 8, command.indexOf('"', tagStart + 8));
                    tagged.put(tag, uuid);
                }
            } else if (command.startsWith("time set ")) {
                time = Long.parseLong(command.substring("time set ".length()));
            } else if (command.startsWith("setblock ")) {
                String[] parts = command.split(" ");
                blocks.putIfAbsent(parts[1] + "," + parts[2] + "," + parts[3], parts[4]);
            }
        }

        @Override
        public List<String> entityIds(String entityTypeId, int x, int y, int z, int radius) {
            return new ArrayList<>(entityUuids);
        }

        @Override
        public String firstEntityWithTag(String tag) {
            return tagged.get(tag);
        }
    }

    static void worldProofTests() {
        V2CoreTests.FakeWorld stuckThunder = new V2CoreTests.FakeWorld() {
            @Override public void runCommand(String command) { super.runCommand(command); thundering=true; }
        };
        var weatherOps=new WorldOperations(stuckThunder,ClientThreadExecutor.direct(),new OperationJournal(),100);
        var staleThunder=weatherOps.execute("world.set_weather",Map.of("weather","rain","duration_seconds",60,
            "build_region",V2CoreTests.region(0,64,0,15,79,15)),"run/stale-thunder");
        check("rain requires thundering=false", "failed".equals(staleThunder.status()));
        check("weather seconds have explicit unit", "weather rain 60s".equals(staleThunder.result().get("command")));

        // Exact keep-fill proof: only air positions may change.
        TagWorld lazyWorld = new TagWorld();
        lazyWorld.fillMode = TagWorld.FillMode.LAZY;
        lazyWorld.blocks.put("0,64,0", "minecraft:stone"); // one occupied position
        OperationJournal lazyJournal = new OperationJournal();
        WorldOperations lazyOps = new WorldOperations(lazyWorld, ClientThreadExecutor.direct(),
            lazyJournal, 100);
        Map<String, Object> fill = new LinkedHashMap<>();
        fill.put("start", V2CoreTests.point(0, 64, 0));
        fill.put("end", V2CoreTests.point(1, 64, 1));
        fill.put("block", "minecraft:stone");
        fill.put("build_region", V2CoreTests.region(0, 64, 0, 15, 79, 15));
        WorldOperations.Outcome partial = lazyOps.execute("world.fill_keep", fill, "run/partial");
        check("silent no-op fill is a proven failure (air_before vs changed)",
            "failed".equals(partial.status())
                && Long.valueOf(3L).equals(((Number) partial.result().get("air_before")).longValue()));

        TagWorld world = new TagWorld();
        world.blocks.put("0,64,0", "minecraft:stone");
        OperationJournal journal = new OperationJournal();
        WorldOperations ops = new WorldOperations(world, ClientThreadExecutor.direct(), journal, 100);
        WorldOperations.Outcome exact = ops.execute("world.fill_keep", fill, "run/exact");
        check("exact keep-fill (all 3 air positions placed) succeeds",
            "applied".equals(exact.status()) && Boolean.TRUE.equals(exact.result().get("ok")));

        Map<String, Object> airFill = new LinkedHashMap<>(fill);
        airFill.put("block", "minecraft:air");
        WorldOperations.Outcome refused = ops.execute("world.fill_keep", airFill, "run/air");
        check("fill with air is refused as a silent no-op",
            "failed".equals(refused.status()));

        // Tag-identified summon: replay never duplicates the actor.
        TagWorld actorWorld = new TagWorld();
        OperationJournal actorJournal = new OperationJournal();
        WorldOperations actorOps = new WorldOperations(actorWorld, ClientThreadExecutor.direct(),
            actorJournal, 100);
        Map<String, Object> summon = new LinkedHashMap<>();
        summon.put("entity", "minecraft:villager");
        summon.put("x", 1); summon.put("y", 64); summon.put("z", 1);
        summon.put("tag", "mcfilm-ev01-actor");
        summon.put("build_region", V2CoreTests.region(0, 64, 0, 15, 79, 15));
        WorldOperations.Outcome created = actorOps.execute("world.summon", summon, "run/actor-1");
        check("tag summon succeeds with the entity identity",
            "applied".equals(created.status())
                && created.result().get("entity_uuid") != null
                && String.valueOf(created.result().get("command")).contains("mcfilm-ev01-actor"));
        int commandsAfterCreate = actorWorld.commands.size();
        actorWorld.ready = false;
        WorldOperations.Outcome unloaded = actorOps.execute("world.summon", summon, "run/unloaded");
        check("untracked actor position fails before any summon",
            "failed".equals(unloaded.status()) && Boolean.FALSE.equals(unloaded.result().get("write_executed"))
                && actorWorld.commands.size() == commandsAfterCreate);
        actorWorld.ready = true;
        // A NEW key for the SAME actor tag: the tag already owns an entity →
        // replay proof, no second summon.
        WorldOperations.Outcome duplicate = actorOps.execute("world.summon", summon, "run/actor-2");
        check("tag-owned actor is never summoned twice",
            "applied".equals(duplicate.status())
                && Boolean.TRUE.equals(duplicate.result().get("replayed"))
                && actorWorld.commands.size() == commandsAfterCreate
                && actorWorld.entityUuids.size() == 1);

        // Untagged summon proves via entity identity diff.
        Map<String, Object> untagged = new LinkedHashMap<>(summon);
        untagged.remove("tag");
        WorldOperations.Outcome plain = actorOps.execute("world.summon", untagged, "run/actor-3");
        check("untagged summon captures the spawned uuid",
            "applied".equals(plain.status())
                && plain.result().get("spawned_entity_uuid") != null
                && actorWorld.entityUuids.size() == 2);
    }

    // -- replay-master port (P1 fail-closed surface) --------------------------------

    static void replayPortTests() throws Exception {
        Path dir = Files.createTempDirectory("v3-journal-replay");
        PersistentJournal journal = PersistentJournal.open(dir);
        GatedRunner gate = new GatedRunner();
        ClientThreadExecutor game = new ClientThreadExecutor(gate);
        WorldOperations ops = new WorldOperations(new TagWorld(), game, new OperationJournal(), 60_000);
        AsyncOperationService service = new AsyncOperationService(journal, ops, game, 60_000);
        MocapStateMachine machine = new MocapStateMachine(command -> { });
        BridgeDispatcher dispatcher = new BridgeDispatcher(
            command -> "",
            new FlashbackDisabledPort(),
            () -> GameStateV2.mainMenu().toMap(),
            VersionGate.RuntimeVersions.of("1.21.1", "0.19.3", "0.39.8", "1.3.10"),
            new OperationJournal(), ops, machine, machine::phase, 1, 0,
            journal, service);

        // Every replay method is refused under contract 3 — never skipped-open.
        Map<String, Object> render = dispatcher.handle("replay.start_render", Map.of(
            "timeline_id", "master-1",
            "range", Map.of("start_tick", 0, "end_tick", 200)), 3, "run/render-1");
        check("replay.start_render fail-closed without a binding",
            "rejected".equals(render.get("status"))
                && "manual_intervention_required".equals(render.get("error_class")));
        Map<String, Object> open = dispatcher.handle("replay.open_master",
            Map.of("timeline_id", "master-1"), 3, "run/open-1");
        check("replay.open_master fail-closed",
            "rejected".equals(open.get("status")));

        // Contract-2 never saw the replay.* methods at all (frozen surface).
        Map<String, Object> v2Replay = dispatcher.handle("replay.start_render",
            Map.of("timeline_id", "master-1"), 2, "run/render-v2");
        check("replay.* under contract 2 is an unknown-method rejection",
            "rejected".equals(v2Replay.get("status"))
                && "validation_failed".equals(v2Replay.get("error_class")));

        // v3 capability payload advertises the backend names and async flags.
        Map<String, Object> capabilities = dispatcher.handle("bridge.capabilities", Map.of(),
            3, "run/capabilities-3");
        Map<?, ?> capResult = (Map<?, ?>) capabilities.get("result");
        check("v3 capabilities advertise contract 3",
            Long.valueOf(3L).equals(((Number) capResult.get("contract")).longValue()));
        check("v3 capabilities name the recorder backend",
            "mocap".equals(capResult.get("recorder_backend")));
        check("v3 capabilities keep replay/camera/render closed without a binding",
            "none".equals(capResult.get("replay_backend"))
                && "none".equals(capResult.get("camera_backend"))
                && "none".equals(capResult.get("render_backend")));
        check("v3 capabilities advertise the async pipeline",
            Boolean.TRUE.equals(capResult.get("async_world_writes"))
                && Boolean.TRUE.equals(capResult.get("persistent_journal")));

        // v2 capabilities stay frozen in shape (no backend names leak).
        Map<String, Object> v2Capabilities = dispatcher.handle("bridge.capabilities", Map.of(),
            2, "run/capabilities-2");
        Map<?, ?> v2Cap = (Map<?, ?>) v2Capabilities.get("result");
        check("v2 capabilities keep contract 2 and no v3 fields",
            Long.valueOf(2L).equals(((Number) v2Cap.get("contract")).longValue())
                && !v2Cap.containsKey("replay_backend")
                && !v2Cap.containsKey("async_world_writes"));

        // With a binding present, the payload names replaymod.
        BridgeDispatcher bound = new BridgeDispatcher(
            command -> "",
            new FlashbackDisabledPort(),
            () -> GameStateV2.mainMenu().toMap(),
            VersionGate.RuntimeVersions.of("1.21.1", "0.19.3", "0.39.8", "1.3.10"),
            new OperationJournal(), ops, machine, machine::phase, 1, 0,
            journal, service,
            new dev.mcfilm.cinematicbridge.replay.ReplayPort() {
                @Override public String backendName() { return "replaymod"; }
                @Override public boolean enabled() { return true; }
                @Override public String disabledReason() { return ""; }
                @Override public boolean matchesHash(String id, String hash) { return "sha256:test".equals(hash); }
                @Override public Map<String, Object> startRecording(String timelineId) {
                    return Map.of("status", "applied", "result", Map.of("recording", timelineId));
                }
                @Override public Map<String, Object> stopRecording(String timelineId) {
                    return Map.of("status", "applied", "result", Map.of());
                }
                @Override public Map<String, Object> awaitMasterSaved(String timelineId) {
                    return Map.of("status", "applied", "result", Map.of("saved", true));
                }
                @Override public Map<String, Object> openMaster(String timelineId) {
                    return Map.of("status", "applied", "result", Map.of("open", timelineId));
                }
                @Override public Map<String, Object> replaceCameraTrack(String timelineId,
                                                                        java.util.List<Map<String, Object>> keyframes,
                                                                        String interpolation) {
                    return Map.of("status", "applied", "result", Map.of("track", timelineId));
                }
                @Override public Map<String, Object> startRender(String timelineId, int s, int e,
                                                                 int w, int h, int fps, String out) {
                    return Map.of("status", "applied", "result",
                        Map.of("job", timelineId, "frames", (e - s) * fps));
                }
                @Override public Map<String, Object> renderStatus() {
                    return Map.of("status", "applied", "result", Map.of("state", "idle"));
                }
                @Override public Map<String, Object> cancelRender() {
                    return Map.of("status", "applied", "result", Map.of("cancelled", true));
                }
            });
        Map<String, Object> capBound = bound.handle("bridge.capabilities", Map.of(),
            3, "run/capabilities-bound");
        Map<?, ?> boundResult = (Map<?, ?>) capBound.get("result");
        check("bound port advertises replaymod across replay/camera/render",
            "replaymod".equals(boundResult.get("replay_backend"))
                && "replaymod".equals(boundResult.get("camera_backend"))
                && "replaymod".equals(boundResult.get("render_backend")));
        Map<String, Object> boundRender = bound.handle("replay.start_render", Map.of(
            "timeline_id", "master-1",
            "master_hash", "sha256:test",
            "range", Map.of("start_tick", 0, "end_tick", 300),
            "fps", 30), 3, "run/render-bound");
        check("bound port routes replay.start_render",
            "applied".equals(boundRender.get("status"))
                && Long.valueOf(9000L).equals(((Number) ((Map<?, ?>) boundRender.get("result"))
                    .get("frames")).longValue()));
    }

    // -- http v3 round trip -----------------------------------------------------------

    static void httpV3Tests() throws Exception {
        Path dir = Files.createTempDirectory("v3-journal-http");
        PersistentJournal journal = PersistentJournal.open(dir);
        GatedRunner gate = new GatedRunner();
        ClientThreadExecutor game = new ClientThreadExecutor(gate);
        WorldOperations ops = new WorldOperations(new TagWorld(), game, new OperationJournal(), 60_000);
        AsyncOperationService service = new AsyncOperationService(journal, ops, game, 60_000);
        MocapStateMachine machine = new MocapStateMachine(command -> { });
        BridgeDispatcher dispatcher = new BridgeDispatcher(
            command -> "",
            new FlashbackDisabledPort(),
            () -> GameStateV2.mainMenu().toMap(),
            VersionGate.RuntimeVersions.of("1.21.1", "0.19.3", "0.39.8", "1.3.10"),
            new OperationJournal(), ops, machine, machine::phase, 1, 0,
            journal, service);
        BridgeHttpServer server = new BridgeHttpServer(0, "v3-token", dispatcher);
        server.start();
        String base = "http://127.0.0.1:" + server.port() + "/rpc";
        try {
            Map<String, Object> params = new LinkedHashMap<>();
            params.put("value", 6000);
            params.put("build_region", V2CoreTests.region(0, 64, 0, 15, 79, 15));
            Map<?, ?> accepted = callV3(base, "world.set_time", params, "run/http-1");
            check("v3 write accepted over http with the caller's key",
                "accepted".equals(accepted.get("status"))
                    && "run/http-1".equals(accepted.get("idempotency_key"))
                    && Long.valueOf(3L).equals(((Number) accepted.get("schema_version")).longValue()));

            Map<?, ?> pending = callV3Status(base, "run/http-1");
            check("v3 status is pending while parked", "pending".equals(pending.get("status")));

            // Idempotent resubmit over http replays the in-flight job.
            Map<?, ?> resubmitted = callV3(base, "world.set_time", params, "run/http-1");
            check("v3 resubmit with same params stays pending (replay)",
                "pending".equals(resubmitted.get("status")));

            waitFor(() -> !gate.parked.isEmpty());
            gate.releaseAll();
            waitFor(() -> "succeeded".equals(callV3Status(base, "run/http-1").get("status")));
            Map<?, ?> done = callV3Status(base, "run/http-1");
            check("v3 status shows succeeded with proof after completion",
                "succeeded".equals(done.get("status"))
                    && Long.valueOf(6000L).equals(timeOfDayProof(done)));

            // Schema gate: a contract-3 bridge still answers v2 requests.
            int v2Still = postV2(base, "bridge.get_runtime_versions");
            check("v2 handshake still works on a contract-3 bridge", v2Still == 200);
        } finally {
            server.stop();
        }
    }

    static Map<?, ?> callV3(String base, String method, Map<String, Object> params, String key)
            throws IOException {
        Map<String, Object> request = new LinkedHashMap<>();
        request.put("schema_version", 3);
        request.put("run_id", "v3");
        request.put("operation_id", "op-" + key.replace('/', '-'));
        request.put("idempotency_key", key);
        request.put("method", method);
        request.put("params", params);
        Map<String, Object> envelope = new LinkedHashMap<>();
        envelope.put("request", request);
        HttpURLConnection connection = (HttpURLConnection) URI.create(base).toURL().openConnection();
        connection.setRequestMethod("POST");
        connection.setRequestProperty("Authorization", "Bearer v3-token");
        connection.setDoOutput(true);
        connection.getOutputStream().write(MiniJson.write(envelope).getBytes(StandardCharsets.UTF_8));
        String body = new String(connection.getInputStream().readAllBytes(), StandardCharsets.UTF_8);
        return (Map<?, ?>) MiniJson.parse(body);
    }

    static Map<?, ?> callV3Status(String base, String key) throws IOException {
        return callV3(base, "bridge.get_operation_status", Map.of("idempotency_key", key),
            key + "-status");
    }

    static int postV2(String base, String method) throws IOException {
        Map<String, Object> request = new LinkedHashMap<>();
        request.put("schema_version", 2);
        request.put("run_id", "v3");
        request.put("operation_id", "op-v2-" + method.replace('.', '-'));
        request.put("idempotency_key", "v3/" + method.replace('.', '-'));
        request.put("method", method);
        request.put("params", Map.of());
        Map<String, Object> envelope = new LinkedHashMap<>();
        envelope.put("request", request);
        HttpURLConnection connection = (HttpURLConnection) URI.create(base).toURL().openConnection();
        connection.setRequestMethod("POST");
        connection.setRequestProperty("Authorization", "Bearer v3-token");
        connection.setDoOutput(true);
        connection.getOutputStream().write(MiniJson.write(envelope).getBytes(StandardCharsets.UTF_8));
        return connection.getResponseCode();
    }

    // -- helpers --------------------------------------------------------------------

    static void waitFor(Condition condition) throws Exception {
        long deadline = System.currentTimeMillis() + 10_000;
        while (System.currentTimeMillis() < deadline) {
            try {
                if (condition.met()) {
                    return;
                }
            } catch (Exception ignored) {
                // state not ready yet (or the HTTP read raced the journal)
            }
            Thread.sleep(25);
        }
        if (!condition.met()) {
            throw new AssertionError("condition not met within 10s");
        }
    }

    /** time_of_day lives inside the journaled proof (result.proof.time_of_day). */
    static Long timeOfDayProof(Map<?, ?> reply) {
        Object result = reply.get("result");
        Object proof = result instanceof Map<?, ?> map ? map.get("proof") : null;
        return proof instanceof Map<?, ?> proofMap && proofMap.get("time_of_day") instanceof Number number
            ? number.longValue() : null;
    }

    interface Condition {
        boolean met() throws Exception;
    }

    static void check(String name, boolean condition) {
        if (condition) {
            passed++;
        } else {
            failures.add(name);
        }
    }
}
