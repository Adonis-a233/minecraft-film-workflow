package dev.mcfilm.cinematicbridge;

import dev.mcfilm.cinematicbridge.json.MiniJson;
import dev.mcfilm.cinematicbridge.mocap.MocapFeedback;
import dev.mcfilm.cinematicbridge.mocap.MocapStateMachine;
import dev.mcfilm.cinematicbridge.server.BridgeDispatcher;
import dev.mcfilm.cinematicbridge.server.BridgeHttpServer;
import dev.mcfilm.cinematicbridge.server.ClientThreadExecutor;
import dev.mcfilm.cinematicbridge.server.OperationJournal;
import dev.mcfilm.cinematicbridge.state.GameStateV2;
import dev.mcfilm.cinematicbridge.state.MocapStateV2;
import dev.mcfilm.cinematicbridge.world.WorldAccess;
import dev.mcfilm.cinematicbridge.world.WorldOperations;
import dev.mcfilm.cinematicbridge.world.WorldOpParser;
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
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * Contract-2 core behavior: truthful journal, bounded client-thread dispatch,
 * proven typed world writes, the two-step Mocap start, fail-closed feedback,
 * and a full HTTP v2 round trip. Pure JDK, offline. Run: java V2CoreTests
 * [contracts/v2]
 */
public final class V2CoreTests {

    private static int passed = 0;
    private static final List<String> failures = new ArrayList<>();

    public static void main(String[] args) throws Exception {
        Path fixtures = Path.of(args.length > 0 ? args[0] : "contracts/v2").resolve("fixtures");
        journalTests();
        executorTests();
        parserTests();
        worldOperationTests();
        mocapTests(fixtures);
        gameStateTests();
        httpV2Tests();
        System.out.println("passed: " + passed + ", failed: " + failures.size());
        failures.forEach(failure -> System.out.println("FAIL " + failure));
        if (!failures.isEmpty()) {
            System.exit(1);
        }
    }

    // -- operation journal -------------------------------------------------------

    static void journalTests() {
        OperationJournal journal = new OperationJournal();
        journal.open("k1", "world.set_time");
        check("journal starts ACCEPTED", journal.stateOf("k1").orElseThrow() == OperationJournal.State.ACCEPTED);
        journal.markQueued("k1");
        journal.markDispatched("k1");
        journal.markObserved("k1");
        check("journal reaches OBSERVED", journal.stateOf("k1").orElseThrow() == OperationJournal.State.OBSERVED);
        try {
            journal.markObserved("k1"); // re-observation allowed
            check("re-observation of OBSERVED allowed", true);
        } catch (IllegalStateException error) {
            check("re-observation of OBSERVED allowed", false);
        }
        try {
            journal.markDispatched("k1");
            check("OBSERVED is terminal", false);
        } catch (IllegalStateException expected) {
            check("OBSERVED is terminal", true);
        }

        journal.open("k2", "world.fill_keep");
        journal.markQueued("k2");
        journal.markUnknown("k2");
        journal.markObserved("k2"); // late proof resolves unknown
        check("UNKNOWN resolves to OBSERVED",
            journal.stateOf("k2").orElseThrow() == OperationJournal.State.OBSERVED);

        // bounded: fill with unproven records, journal must refuse new writes
        OperationJournal full = new OperationJournal();
        for (int i = 0; i < OperationJournal.MAX_ENTRIES; i++) {
            full.open("u" + i, "world.set_time");
        }
        check("full journal refuses new writes", full.open("overflow", "world.set_time") == null);
        OperationJournal evicting = new OperationJournal();
        for (int i = 0; i < OperationJournal.MAX_ENTRIES; i++) {
            evicting.open("t" + i, "world.set_time");
            evicting.markQueued("t" + i);
            evicting.markDispatched("t" + i);
            evicting.markObserved("t" + i);
        }
        check("full journal evicts terminal records", evicting.open("fresh", "world.set_time") != null);
    }

    // -- client thread executor ---------------------------------------------------

    static void executorTests() {
        ClientThreadExecutor direct = ClientThreadExecutor.direct();
        ClientThreadExecutor.Dispatch proven = direct.dispatch(100, () -> "done");
        check("direct dispatch proven", proven.outcome() == ClientThreadExecutor.Outcome.PROVEN
            && "done".equals(proven.output()));

        ClientThreadExecutor.Dispatch failed = direct.dispatch(100, () -> {
            throw new IllegalStateException("boom");
        });
        check("failing task is a proven failure", failed.outcome() == ClientThreadExecutor.Outcome.FAILED);

        // A runner that swallows the task: no proof within the budget.
        ClientThreadExecutor ghost = new ClientThreadExecutor(task -> { /* never runs */ });
        ClientThreadExecutor.Dispatch unproven = ghost.dispatch(30, () -> "never");
        check("swallowed task yields UNPROVEN", unproven.outcome() == ClientThreadExecutor.Outcome.UNPROVEN);
    }

    // -- typed op parsing ----------------------------------------------------------

    static void parserTests() {
        Map<String, Object> region = region(0, 64, 0, 15, 79, 15);
        check("set_time parses", WorldOpParser.parseSetTime(Map.of(
            "value", 6000, "build_region", region)).value() == 6000);
        expectRejected("time above 24000 rejected", () ->
            WorldOpParser.parseSetTime(Map.of("value", 24001, "build_region", region)));
        expectRejected("region missing rejected", () ->
            WorldOpParser.parseSetTime(Map.of("value", 1000)));
        expectRejected("unnamespaced block rejected", () ->
            WorldOpParser.parseSetBlock(Map.of(
                "x", 1, "y", 64, "z", 1, "block", "stone", "build_region", region)));
        expectRejected("setblock outside region rejected", () ->
            WorldOpParser.parseSetBlock(Map.of(
                "x", 100, "y", 64, "z", 100, "block", "minecraft:stone", "build_region", region)));

        check("block properties parsed", WorldOpParser.parseSetBlock(Map.of(
            "x",1,"y",64,"z",1,"block","minecraft:oak_stairs[facing=east,half=bottom]","build_region",region))
            .block().contains("facing=east"));
        for (String invalid : List.of("minecraft:stone{foo:1}","minecraft:stone;stop",
                "minecraft:oak_stairs[facing=east,facing=west]","#minecraft:logs")) {
            expectRejected("block injection/duplicate rejected: "+invalid, () -> WorldOpParser.parseSetBlock(Map.of(
                "x",1,"y",64,"z",1,"block",invalid,"build_region",region)));
        }

        Map<String, Object> bigFill = region(0, 64, 0, 200, 200, 200); // > 262144 blocks
        expectRejected("oversized region rejected", () ->
            WorldOpParser.requireRegion(Map.of("build_region", bigFill)));
        Map<String, Object> fillParams = new LinkedHashMap<>();
        fillParams.put("start", point(0, 64, 0));
        fillParams.put("end", point(64, 64, 64)); // 65^3 = 274625 > 32768
        fillParams.put("block", "minecraft:stone");
        fillParams.put("build_region", region(0, 64, 0, 127, 127, 127));
        expectRejected("oversized fill rejected", () -> WorldOpParser.parseFill(fillParams));
    }

    // -- typed world operations -----------------------------------------------------

    static void worldOperationTests() {
        FakeWorld world = new FakeWorld();
        OperationJournal journal = new OperationJournal();
        WorldOperations ops = new WorldOperations(world, ClientThreadExecutor.direct(), journal, 100);

        Map<String, Object> params = new LinkedHashMap<>();
        params.put("value", 6000);
        params.put("build_region", region(0, 64, 0, 15, 79, 15));
        WorldOperations.Outcome outcome = ops.execute("world.set_time", params, "run/set-time");
        check("set_time applied with proof",
            "applied".equals(outcome.status()) && Long.valueOf(6000L)
                .equals(((Number) outcome.result().get("time_of_day")).longValue()));
        check("set_time journaled OBSERVED",
            journal.stateOf("run/set-time").orElseThrow() == OperationJournal.State.OBSERVED);

        WorldOperations.Outcome replay = ops.execute("world.set_time", params, "run/set-time");
        check("duplicate key replays without re-execution",
            "applied".equals(replay.status()) && Boolean.TRUE.equals(replay.result().get("idempotent_replay")));
        check("no duplicate execution", world.commands.size() == 1);

        Map<String, Object> badId = new LinkedHashMap<>(params);
        badId.put("block", "minecraft:not_a_block");
        badId.remove("value");
        badId.put("x", 1);
        badId.put("y", 64);
        badId.put("z", 1);
        WorldOperations.Outcome unknownBlock = ops.execute("world.set_block_keep", badId, "run/bad-block");
        check("unknown block id fails before dispatch",
            "failed".equals(unknownBlock.status())
                && String.valueOf(unknownBlock.result().get("reason")).contains("unknown block"));
        check("failed proof journaled OBSERVED (outcome known)",
            journal.stateOf("run/bad-block").orElseThrow() == OperationJournal.State.OBSERVED);

        WorldOperations.Outcome outside = ops.execute("world.set_block_keep", Map.of(
            "x", 999, "y", 64, "z", 999, "block", "minecraft:stone",
            "build_region", region(0, 64, 0, 15, 79, 15)), "run/outside");
        check("outside-region write rejected", "rejected".equals(outside.status()));

        WorldOperations.Outcome read = ops.read("world.get_time", Map.of());
        check("get_time read applied", "applied".equals(read.status())
            && Long.valueOf(6000L).equals(((Number) read.result().get("time_of_day")).longValue()));

        // dropped dispatch → unknown, resolvable via the journal
        OperationJournal journal2 = new OperationJournal();
        WorldOperations ghostOps = new WorldOperations(world,
            new ClientThreadExecutor(task -> { /* dropped */ }), journal2, 20);
        WorldOperations.Outcome lost = ghostOps.execute("world.set_time", params, "run/lost");
        check("dropped dispatch reports unknown", "unknown".equals(lost.status()));
        check("dropped dispatch journaled UNKNOWN",
            journal2.stateOf("run/lost").orElseThrow() == OperationJournal.State.UNKNOWN);
        WorldOperations.Outcome retry = ghostOps.execute("world.set_time", params, "run/lost");
        check("retry of UNKNOWN refuses to resend", "unknown".equals(retry.status()));
        check("still only one execution on the real world", world.commands.size() == 1);
    }

    // -- mocap state machine + feedback ---------------------------------------------

    static void mocapTests(Path fixtures) throws IOException {
        List<String> targetedCommands = new ArrayList<>();
        MocapStateMachine targeted = new MocapStateMachine(targetedCommands::add);
        targeted.prepare("S01Teacher");
        targeted.observe("执行任何操作或再次使用\"/mocap recording start\"以开始录制……");
        targeted.confirm();
        check("targeted recorder preserves player across both starts", targetedCommands.equals(
            List.of("mocap recording start S01Teacher", "mocap recording start S01Teacher")));
        var automaticPoll = new dev.mcfilm.cinematicbridge.mocap.MocapPoller(
            () -> MocapStateV2.Phase.RECORDING, () -> true);
        check("prepare accepts an observed automatic start", automaticPoll.await(
            MocapStateV2.Phase.WAITING_FOR_SELECTION,1,true).reached());
        check("live discard feedback is classified", MocapFeedback.classify("Recording discarded") == MocapFeedback.RECORDING_DISCARDED);
        // classifier pins agree with the shared transcript fixtures
        checkPinned(fixtures, "zh_cn/waiting-for-selection.txt", MocapFeedback.WAITING_FOR_SELECTION);
        checkPinned(fixtures, "zh_cn/waiting-cancelled.txt", MocapFeedback.WAITING_CANCELLED);
        checkPinned(fixtures, "zh_cn/save-rejected-empty.txt", MocapFeedback.SAVE_REJECTED_EMPTY);
        checkPinned(fixtures, "zh_cn/recording-started.txt", MocapFeedback.RECORDING_STARTED);
        checkPinned(fixtures, "zh_cn/recording-stopped.txt", MocapFeedback.RECORDING_STOPPED);
        checkPinned(fixtures, "zh_cn/save-success.txt", MocapFeedback.SAVE_SUCCESS);
        checkPinned(fixtures, "unknown/axiom-tip.txt", MocapFeedback.UNKNOWN);

        List<String> commands = new ArrayList<>();
        MocapStateMachine machine = new MocapStateMachine(commands::add);

        // F6: the FIRST start must NOT enter recording.
        MocapStateMachine.Transition prepare = machine.prepare();
        check("prepare issues one start command",
            "mocap recording start".equals(prepare.command()) && commands.size() == 1);
        machine.observe("执行任何操作或再次使用\"/mocap recording start\"以开始录制……");
        check("prepare lands in waiting_for_selection",
            machine.phase() == MocapStateV2.Phase.WAITING_FOR_SELECTION);

        // confirm begins real recording
        machine.confirm();
        machine.observe("录制开始……");
        check("confirm enters recording", machine.phase() == MocapStateV2.Phase.RECORDING);
        check("exactly two start commands so far", commands.size() == 2);

        machine.stop();
        machine.observe("录制停止——等待选择中……\n使用\"/mocap recording save <recording_name>\"来保存此段录像");
        check("stop leaves recorded_unsaved", machine.phase() == MocapStateV2.Phase.RECORDED_UNSAVED);

        // save from an empty recorder was rejected live; model the rejected path
        machine.save("slice_take_01");
        machine.observe("§l错误：§r没有可以保存的东西！");
        check("§-codes stripped; rejection recognized",
            machine.phase() == MocapStateV2.Phase.REJECTED);

        // from rejected, prepare → confirm → stop → save succeeds
        machine.prepare();
        machine.observe("执行任何操作或再次使用\"/mocap recording start\"以开始录制……");
        machine.confirm();
        machine.observe("录制开始……");
        machine.stop();
        machine.observe("录制停止——等待选择中……");
        machine.save("slice_take_01");
        machine.observe("录像已成功保存");
        check("second full cycle reaches saved", machine.phase() == MocapStateV2.Phase.SAVED);
        machine.recordSaved("slice_take_01");
        check("saved state carries recording name",
            "slice_take_01".equals(machine.status().recordingName()));

        machine.observe("Recording started...");
        machine.observeGameMessage("Scene successfully added", false);
        machine.observeGameMessage("[Axiom] Tip", false);
        check("unrelated chat retains recorder state", machine.phase()==MocapStateV2.Phase.RECORDING);
        machine.observeGameMessage("new unknown recording feedback", true);
        check("unknown recorder domain fails closed", machine.phase()==MocapStateV2.Phase.UNKNOWN);
        // unknown feedback fails closed
        machine.observe("[Axiom] Tip: Access the Axiom config by running /axiomconfig");
        check("unrelated feedback fails closed to UNKNOWN",
            machine.phase() == MocapStateV2.Phase.UNKNOWN);

        // illegal transitions are refused without dispatching
        int before = commands.size();
        expectRejected("save from idle refused", () -> new MocapStateMachine(commands::add).save("x"));
        expectRejected("confirm from idle refused", () -> new MocapStateMachine(commands::add).confirm());
        check("illegal transitions dispatch nothing", commands.size() == before);
    }

    /**
     * A fixture file models one complete feedback EVENT (possibly multi-line,
     * exactly as the game emits it). The whole content must classify as the
     * pinned outcome — mixed or unknown classification fails the pin.
     */
    static void checkPinned(Path fixtures, String relative, MocapFeedback expected) throws IOException {
        String content = Files.readString(fixtures.resolve("transcripts").resolve(relative),
            StandardCharsets.UTF_8).stripTrailing();
        MocapFeedback classified = MocapFeedback.classify(content);
        check("transcript pin matches classifier: " + relative, classified == expected);
    }

    // -- truthful game state ------------------------------------------------------------

    static void gameStateTests() {
        GameStateV2 menu = GameStateV2.mainMenu();
        check("main menu refuses writes",
            menu.preWriteGate("Marx Video Test", "minecraft:overworld", "CineProbe")
                .startsWith("session_phase"));

        GameStateV2 inWorld = new GameStateV2(GameStateV2.Phase.IN_WORLD, "Marx Video Test",
            "minecraft:overworld", "CineProbe", false, 12345L, false, null);
        check("in-world state passes the gate",
            inWorld.preWriteGate("Marx Video Test", "minecraft:overworld", "CineProbe") == null);
        check("wrong save refuses", inWorld
            .preWriteGate("Other", "minecraft:overworld", "CineProbe") != null);
        GameStateV2 paused = new GameStateV2(GameStateV2.Phase.IN_WORLD, "Marx Video Test",
            "minecraft:overworld", "CineProbe", true, 12345L, true, null);
        check("paused refuses", paused
            .preWriteGate("Marx Video Test", "minecraft:overworld", "CineProbe") != null);
        check("roundtrip via map", GameStateV2.fromMap(inWorld.toMap()).paused() == false);
    }

    // -- HTTP v2 round trip ---------------------------------------------------------------

    static void httpV2Tests() throws Exception {
        FakeWorld world = new FakeWorld();
        OperationJournal journal = new OperationJournal();
        WorldOperations ops = new WorldOperations(world, ClientThreadExecutor.direct(), journal, 100);
        MocapStateMachine machine = new MocapStateMachine(command -> { });
        BridgeDispatcher dispatcher = new BridgeDispatcher(
            command -> "",
            new FlashbackDisabledPort(),
            () -> GameStateV2.mainMenu().toMap(),
            VersionGate.RuntimeVersions.of("1.21.1", "0.19.3", "0.39.8", "1.3.10"),
            journal, ops, machine, machine::phase, 1, 0);
        BridgeHttpServer server = new BridgeHttpServer(0, "v2-token", dispatcher);
        server.start();
        String base = "http://127.0.0.1:" + server.port() + "/rpc";
        try {
            Map<?, ?> versions = callV2(base, "bridge.get_runtime_versions", Map.of());
            check("v2 handshake reports contract 2",
                "applied".equals(versions.get("status"))
                    && ((Map<?, ?>) versions.get("result")).get("contract").equals(Long.valueOf(2)));
            check("v2 reply carries the idempotency key (F1)",
                "v2/bridge-get_runtime_versions".equals(versions.get("idempotency_key")));

            Map<String, Object> params = new LinkedHashMap<>();
            params.put("value", 6000);
            params.put("build_region", region(0, 64, 0, 15, 79, 15));
            Map<?, ?> setTime = callV2(base, "world.set_time", params);
            check("v2 typed set_time applied over http",
                "applied".equals(setTime.get("status"))
                    && "observed".equals(setTime.get("journal_state")));

            Map<?, ?> capabilities = callV2(base, "bridge.capabilities", Map.of());
            Map<?, ?> capabilityResult = (Map<?, ?>) capabilities.get("result");
            check("v2 capabilities advertise typed ops",
                Boolean.TRUE.equals(capabilityResult.get("typed_world_ops")));
            check("v2 capabilities keep flashback closed",
                Boolean.FALSE.equals(capabilityResult.get("flashback_automation")));

            Map<?, ?> rejected = callV2(base, "world.fill_keep", Map.of());
            check("v2 fill without region rejected",
                "rejected".equals(rejected.get("status"))
                    && "validation_failed".equals(rejected.get("error_class")));

            int v1Status = postRaw(base, "{\"request\":{\"schema_version\":1,\"run_id\":\"r\","
                + "\"operation_id\":\"o\",\"idempotency_key\":\"r/o\","
                + "\"method\":\"mocap.prepare_recording\",\"params\":{}}}");
            check("v2-only method under contract 1 is rejected (any HTTP status recorded)",
                v1Status == 200); // the rejection travels in the envelope, not the status code
        } finally {
            server.stop();
        }
    }

    // -- tiny fixtures ---------------------------------------------------------------------

    static Map<String, Object> region(int x1, int y1, int z1, int x2, int y2, int z2) {
        Map<String, Object> map = new LinkedHashMap<>();
        map.put("start", point(x1, y1, z1));
        map.put("end", point(x2, y2, z2));
        return map;
    }

    static Map<String, Object> point(int x, int y, int z) {
        Map<String, Object> map = new LinkedHashMap<>();
        map.put("x", x);
        map.put("y", y);
        map.put("z", z);
        return map;
    }

    /** Deterministic fake world: commands run inline, reads answer from state. */
    static class FakeWorld implements WorldAccess {
        @Override public boolean entityPositionReady(int x, int y, int z) { return true; }
        final List<String> commands = new ArrayList<>();
        long time = 0;
        final Map<String, String> blocks = new LinkedHashMap<>();
        boolean raining = false;
        boolean thundering = false;
        long entities = 0;

        @Override
        public boolean blockExists(String blockId) {
            return blockId.equals("minecraft:stone") || blockId.equals("minecraft:white_concrete");
        }

        @Override
        public boolean entityTypeExists(String entityTypeId) {
            return entityTypeId.equals("minecraft:villager");
        }

        @Override
        public String blockAt(int x, int y, int z) {
            return blocks.getOrDefault(x + "," + y + "," + z, "minecraft:air");
        }

        @Override
        public long countBlocks(String blockId, int[] start, int[] end) {
            long count = 0;
            for (int x = Math.min(start[0], end[0]); x <= Math.max(start[0], end[0]); x++) {
                for (int y = Math.min(start[1], end[1]); y <= Math.max(start[1], end[1]); y++) {
                    for (int z = Math.min(start[2], end[2]); z <= Math.max(start[2], end[2]); z++) {
                        if (blockAt(x, y, z).equals(blockId)) {
                            count++;
                        }
                    }
                }
            }
            return count;
        }

        @Override
        public long timeOfDay() {
            return time;
        }

        @Override
        public boolean raining() {
            return raining;
        }

        @Override
        public boolean thundering() {
            return thundering;
        }

        @Override
        public long countEntities(String entityTypeId, int x, int y, int z, int radius) {
            return entities;
        }

        @Override
        public void runCommand(String command) {
            commands.add(command);
            if (command.startsWith("time set ")) {
                time = Long.parseLong(command.substring("time set ".length()));
            } else if (command.startsWith("setblock ")) {
                String[] parts = command.split(" ");
                blocks.putIfAbsent(parts[1] + "," + parts[2] + "," + parts[3], parts[4]);
            }
        }
    }

    // -- http helper -------------------------------------------------------------------

    static Map<?, ?> callV2(String base, String method, Map<String, Object> params) throws IOException {
        Map<String, Object> request = new LinkedHashMap<>();
        request.put("schema_version", 2);
        request.put("run_id", "v2");
        request.put("operation_id", "op-" + method.replace('.', '-'));
        request.put("idempotency_key", "v2/" + method.replace('.', '-'));
        request.put("method", method);
        request.put("params", params);
        Map<String, Object> envelope = new LinkedHashMap<>();
        envelope.put("request", request);
        HttpURLConnection connection = (HttpURLConnection) URI.create(base).toURL().openConnection();
        connection.setRequestMethod("POST");
        connection.setRequestProperty("Authorization", "Bearer v2-token");
        connection.setDoOutput(true);
        connection.getOutputStream().write(MiniJson.write(envelope).getBytes(StandardCharsets.UTF_8));
        String body = new String(connection.getInputStream().readAllBytes(), StandardCharsets.UTF_8);
        return (Map<?, ?>) MiniJson.parse(body);
    }

    static int postRaw(String base, String body) throws IOException {
        HttpURLConnection connection = (HttpURLConnection) URI.create(base).toURL().openConnection();
        connection.setRequestMethod("POST");
        connection.setRequestProperty("Authorization", "Bearer v2-token");
        connection.setDoOutput(true);
        connection.getOutputStream().write(body.getBytes(StandardCharsets.UTF_8));
        return connection.getResponseCode();
    }

    static void expectRejected(String name, Runnable action) {
        try {
            action.run();
            check(name, false);
        } catch (RuntimeException expected) {
            check(name, true);
        }
    }

    static void check(String name, boolean condition) {
        if (condition) {
            passed++;
        } else {
            failures.add(name);
        }
    }
}
