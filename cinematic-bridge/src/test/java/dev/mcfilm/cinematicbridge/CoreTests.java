package dev.mcfilm.cinematicbridge;

import dev.mcfilm.cinematicbridge.core.CameraTrackConverter;
import dev.mcfilm.cinematicbridge.core.TickScheduler;
import dev.mcfilm.cinematicbridge.core.TimelineEvent;
import dev.mcfilm.cinematicbridge.core.TimelineModel;
import dev.mcfilm.cinematicbridge.core.VersionGate;
import dev.mcfilm.cinematicbridge.flash.FlashbackDisabledPort;
import dev.mcfilm.cinematicbridge.json.MiniJson;
import dev.mcfilm.cinematicbridge.server.BridgeDispatcher;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * Dependency-free test runner for the pure core (plan §14 P4: pure-logic
 * tests must not need Minecraft). Run: java …CoreTests
 */
public final class CoreTests {

    private static int passed = 0;
    private static final List<String> failures = new ArrayList<>();

    public static void main(String[] args) {
        testMiniJsonRoundTrip();
        testMiniJsonRejectsGarbage();
        testTimelineValidation();
        testTimelineAllowsMocapOnly();
        testTickSchedulerDeterministicOrder();
        testTickSchedulerCancel();
        testPostRollCompletion();
        testVersionGateExactPins();
        testCameraConverterSegments();
        testCameraConverterRejectsRegression();
        testDispatcherMocapTimeline();
        testDispatcherFlashbackGateFailsClosed();
        testDispatcherIdempotentResubmission();
        testDispatcherSingleSession();

        System.out.println("passed: " + passed + ", failed: " + failures.size());
        failures.forEach(failure -> System.out.println("FAIL " + failure));
        if (!failures.isEmpty()) {
            System.exit(1);
        }
    }

    // -- json -----------------------------------------------------------------

    static void testMiniJsonRoundTrip() {
        String literal = "{\"a\":[1,2.5,\"x" + (char) 10 + "\"],\"b\":{\"c\":true,\"d\":null}}";
        Object first = MiniJson.parse(literal);
        String written = MiniJson.write(first);
        check("json round trip", written.equals(MiniJson.write(MiniJson.parse(written))));
        check("json escapes newline", written.contains("x\\n"));
        Map<?, ?> map = (Map<?, ?>) first;
        Object element = ((java.util.List<?>) map.get("a")).get(2);
        check("json newline string survives", element instanceof String s && s.indexOf((char) 10) == 1);
        check("json null round trip", MiniJson.parse(MiniJson.write(null)) == null);
    }

    static void testMiniJsonRejectsGarbage() {
        try {
            MiniJson.parse("{a:1}");
            check("json rejects garbage", false);
        } catch (IllegalArgumentException expected) {
            check("json rejects garbage", true);
        }
    }

    // -- timeline -------------------------------------------------------------

    static List<TimelineEvent> sampleEvents() {
        return List.of(
            new TimelineEvent(0, TimelineEvent.ASSERT_STATE, Map.of("world", "Marx Video Test")),
            new TimelineEvent(0, TimelineEvent.MOCAP_SCENE_CREATE, Map.of("scene", "S01C01")),
            new TimelineEvent(20, TimelineEvent.FLASHBACK_START, Map.of()),
            new TimelineEvent(20, TimelineEvent.MOCAP_SCENE_PLAY, Map.of("scene", "S01C01")),
            new TimelineEvent(120, TimelineEvent.MOCAP_SCENE_STOP, Map.of("scene", "S01C01")),
            new TimelineEvent(140, TimelineEvent.FLASHBACK_STOP, Map.of()));
    }

    static void testTimelineValidation() {
        try {
            TimelineModel.validate(sampleEvents(), 140);
            check("timeline validation accepts sample", true);
        } catch (IllegalArgumentException error) {
            check("timeline validation accepts sample: " + error, false);
        }
        List<TimelineEvent> inverted = List.of(
            new TimelineEvent(0, TimelineEvent.ASSERT_STATE, Map.of("world", "w")),
            new TimelineEvent(50, TimelineEvent.FLASHBACK_START, Map.of()),
            new TimelineEvent(40, TimelineEvent.FLASHBACK_STOP, Map.of()));
        try {
            TimelineModel.validate(inverted, 100);
            check("timeline rejects inverted window", false);
        } catch (IllegalArgumentException expected) {
            check("timeline rejects inverted window", true);
        }
        check("recording window", java.util.Arrays.equals(
            TimelineModel.recordingWindow(sampleEvents()), new int[] {20, 140}));
    }

    static void testTimelineAllowsMocapOnly() {
        List<TimelineEvent> mocapOnly = List.of(
            new TimelineEvent(0, TimelineEvent.ASSERT_STATE, Map.of("world", "w")),
            new TimelineEvent(0, TimelineEvent.MOCAP_SCENE_CREATE, Map.of("scene", "A")),
            new TimelineEvent(10, TimelineEvent.MOCAP_SCENE_PLAY, Map.of("scene", "A")),
            new TimelineEvent(20, TimelineEvent.MOCAP_SCENE_STOP, Map.of("scene", "A")));
        try {
            TimelineModel.validate(mocapOnly, 30);
            check("timeline allows mocap-only", true);
        } catch (IllegalArgumentException error) {
            check("timeline allows mocap-only: " + error, false);
        }
    }

    // -- scheduler ------------------------------------------------------------

    static void testTickSchedulerDeterministicOrder() {
        List<String> fired = new ArrayList<>();
        TickScheduler scheduler = new TickScheduler(sampleEvents(), 140, event -> fired.add(event.type()));
        // Stuttering clock: events fire once, in plan order, on arrival ticks.
        for (int tick : new int[] {0, 1, 19, 20, 21, 119, 140}) {
            scheduler.tick(tick);
        }
        check("scheduler event order", fired.equals(List.of(
            TimelineEvent.ASSERT_STATE,
            TimelineEvent.MOCAP_SCENE_CREATE,
            TimelineEvent.FLASHBACK_START,
            TimelineEvent.MOCAP_SCENE_PLAY,
            TimelineEvent.MOCAP_SCENE_STOP,
            TimelineEvent.FLASHBACK_STOP)));
        check("scheduler completes", scheduler.state() == TickScheduler.State.COMPLETED);
        check("scheduler journals actual ticks", scheduler.journal().stream()
            .allMatch(e -> e.actualTick() >= e.event().tick()));
        check("scheduler idempotent after completion", scheduler.tick(141).isEmpty());
    }

    static void testPostRollCompletion() {
        TickScheduler scheduler=new TickScheduler(List.of(
            new TimelineEvent(0,TimelineEvent.ASSERT_STATE,Map.of()),
            new TimelineEvent(10,TimelineEvent.MOCAP_SCENE_STOP,Map.of())),20,event -> {});
        scheduler.tick(10);
        check("last event does not discard post-roll",scheduler.state()==TickScheduler.State.RUNNING);
        scheduler.tick(19);
        check("post-roll still runs before its boundary",scheduler.state()==TickScheduler.State.RUNNING);
        scheduler.tick(20);
        check("post-roll completes at total_ticks",scheduler.state()==TickScheduler.State.COMPLETED);
    }

    static void testTickSchedulerCancel() {
        TickScheduler scheduler = new TickScheduler(sampleEvents(), 140, event -> { });
        scheduler.tick(20);
        scheduler.cancel();
        check("cancel stops firing", scheduler.tick(140).isEmpty());
        check("cancel sets state", scheduler.state() == TickScheduler.State.CANCELLED);
    }

    // -- version gate ---------------------------------------------------------

    static void testVersionGateExactPins() {
        check("gate accepts exact pins", VersionGate.mismatches(
            VersionGate.RuntimeVersions.of("1.21.1", "0.19.3", "0.39.8", "1.3.10")).isEmpty());
        check("gate rejects near miss", VersionGate.mismatches(
            VersionGate.RuntimeVersions.of("1.21.1", "0.19.3", "0.39.9", "1.3.10")).size() == 1);
        check("gate rejects everything wrong", VersionGate.mismatches(
            VersionGate.RuntimeVersions.of("1.20", "0.15", "0.1", "1.0")).size() == 4);
    }

    // -- camera -----------------------------------------------------------------

    static void testCameraConverterSegments() {
        List<Map<String, Object>> keyframes = List.of(
            Map.of("tick", 0, "position", List.of(110.0, 69.0, 118.0),
                "yaw", 142.0, "pitch", -14.0, "roll", 0.0, "fov", 55.0),
            Map.of("tick", 120, "position", List.of(103.5, 66.8, 108.0),
                "yaw", 158.0, "pitch", -7.0, "roll", 0.0, "fov", 42.0));
        CameraTrackConverter.ConvertedTrack track = CameraTrackConverter.convert(keyframes, "smooth");
        check("converter emits three parallel tracks",
            track.position().size() == 1 && track.rotation().size() == 1 && track.fov().size() == 1);
        check("converter marks smooth interpolation",
            track.position().get(0).interpolation() == CameraTrackConverter.Interpolation.SMOOTH);
    }

    static void testCameraConverterRejectsRegression() {
        List<Map<String, Object>> regressing = List.of(
            Map.of("tick", 10, "position", List.of(0.0, 0.0, 0.0), "yaw", 0.0, "pitch", 0.0, "roll", 0.0, "fov", 50.0),
            Map.of("tick", 10, "position", List.of(1.0, 0.0, 0.0), "yaw", 0.0, "pitch", 0.0, "roll", 0.0, "fov", 50.0));
        try {
            CameraTrackConverter.convert(regressing, "linear");
            check("converter rejects non-increasing ticks", false);
        } catch (IllegalArgumentException expected) {
            check("converter rejects non-increasing ticks", true);
        }
    }

    // -- dispatcher ---------------------------------------------------------------

    static BridgeDispatcher newDispatcher(List<String> commands, boolean flashbackEnabled) {
        return new BridgeDispatcher(
            command -> {
                commands.add(command);
                return "";
            },
            flashbackEnabled ? new AlwaysEnabledFlashback() : new FlashbackDisabledPort(),
            () -> Map.of("world", "Marx Video Test"),
            VersionGate.RuntimeVersions.of("1.21.1", "0.19.3", "0.39.8", "1.3.10"));
    }

    static Map<String, Object> envelope(String key, List<TimelineEvent> events, int totalTicks) {
        List<Map<String, Object>> raw = new ArrayList<>();
        for (TimelineEvent event : events) {
            raw.add(Map.of("tick", event.tick(), "type", event.type(), "payload", event.payload()));
        }
        return Map.of(
            "idempotency_key", key,
            "timeline", Map.of("timeline_id", "S01C01-take-001", "total_ticks", totalTicks, "events", raw));
    }

    static List<TimelineEvent> mocapTimeline(String scene) {
        return List.of(
            new TimelineEvent(0, TimelineEvent.ASSERT_STATE, Map.of("world", "w")),
            new TimelineEvent(0, TimelineEvent.MOCAP_SCENE_CREATE, Map.of("scene", scene)),
            new TimelineEvent(0, TimelineEvent.MOCAP_SCENE_ADD,
                Map.of("scene", scene, "recording", "test_take", "delay_ticks", 5,
                    "offset", Map.of("x", 4, "y", 0, "z", -2), "player_name", "Worker")),
            new TimelineEvent(10, TimelineEvent.MOCAP_SCENE_PLAY, Map.of("scene", scene)),
            new TimelineEvent(110, TimelineEvent.MOCAP_SCENE_STOP, Map.of("scene", scene)));
    }

    static void testDispatcherMocapTimeline() {
        List<String> commands = new ArrayList<>();
        BridgeDispatcher dispatcher = newDispatcher(commands, false);
        Map<String, Object> result = dispatcher.handle("bridge.submit_timeline",
            envelope("run-x/record/S01C01", mocapTimeline("S01C01"), 120));
        check("mocap-only timeline accepted", "applied".equals(result.get("status")));
        TickScheduler scheduler = dispatcher.activeScheduler();
        for (int tick : new int[] {0, 10, 120}) {
            scheduler.tick(tick);
        }
        check("mocap scene add compiled", commands.stream()
            .anyMatch(c -> c.startsWith("mocap scenes addTo S01C01 test_take 5 4 0 -2 Worker")));
        check("scene play dispatched", commands.stream().anyMatch(c -> c.equals("mocap playing start .S01C01")));
        check("stop targets owned scene", commands.stream().anyMatch(c -> c.equals("mocap playing stopScene .S01C01")));
        check("scheduler completed", scheduler.state() == TickScheduler.State.COMPLETED);
        Map<String, Object> status = dispatcher.handle("bridge.get_timeline_status", Map.of());
        @SuppressWarnings("unchecked")
        Map<String, Object> body = (Map<String, Object>) status.get("result");
        check("status reports completion", "COMPLETED".equals(body.get("state")));
    }

    static void testDispatcherFlashbackGateFailsClosed() {
        BridgeDispatcher dispatcher = newDispatcher(new ArrayList<>(), false);
        Map<String, Object> result = dispatcher.handle("bridge.submit_timeline",
            envelope("run-x/record/S01C01", sampleEvents(), 140));
        check("flashback timeline rejected while port disabled",
            "rejected".equals(result.get("status"))
                && "manual_intervention_required".equals(result.get("error_class")));
        Map<String, Object> direct = dispatcher.handle("flashback.start_recording", Map.of("timeline_id", "x"));
        check("direct flashback call rejected", "rejected".equals(direct.get("status")));
        @SuppressWarnings("unchecked")
        Map<String, Object> caps = (Map<String, Object>) dispatcher.handle("bridge.capabilities", Map.of()).get("result");
        check("disabled reason mentions license", String.valueOf(caps.get("flashback_disabled_reason"))
            .contains("license review pending"));
    }

    static void testDispatcherIdempotentResubmission() {
        BridgeDispatcher dispatcher = newDispatcher(new ArrayList<>(), false);
        Map<String, Object> first = dispatcher.handle("bridge.submit_timeline",
            envelope("run-x/record/S01C01", mocapTimeline("S01C01"), 120));
        check("first submission applied", "applied".equals(first.get("status")));
        // Cancel so a resubmission is not blocked by the single-session rule.
        dispatcher.handle("bridge.cancel_timeline", Map.of());
        Map<String, Object> second = dispatcher.handle("bridge.submit_timeline",
            envelope("run-x/record/S01C01", mocapTimeline("S01C01"), 120));
        check("idempotent resubmission applied", "applied".equals(second.get("status")));
    }

    static void testDispatcherSingleSession() {
        BridgeDispatcher dispatcher = newDispatcher(new ArrayList<>(), false);
        Map<String, Object> first = dispatcher.handle("bridge.submit_timeline",
            envelope("k1", mocapTimeline("A"), 120));
        check("first session accepted", "applied".equals(first.get("status")));
        dispatcher.activeScheduler().tick(0);
        Map<String, Object> second = dispatcher.handle("bridge.submit_timeline",
            envelope("k2", mocapTimeline("B"), 120));
        check("second session rejected while running", "rejected".equals(second.get("status")));
    }

    // -- harness ---------------------------------------------------------------

    static void check(String name, boolean condition) {
        if (condition) {
            passed++;
        } else {
            failures.add(name);
        }
    }

    static final class AlwaysEnabledFlashback implements dev.mcfilm.cinematicbridge.flash.FlashbackPort {
        @Override public boolean enabled() { return true; }
        @Override public String disabledReason() { return ""; }
        @Override public Map<String, Object> startRecording(String timelineId) { return Map.of("status", "applied"); }
        @Override public Map<String, Object> stopRecording(String timelineId) { return Map.of("status", "applied"); }
        @Override public Map<String, Object> awaitReplaySaved(String timelineId) { return Map.of("status", "applied"); }
        @Override public Map<String, Object> openReplay(String timelineId) { return Map.of("status", "applied"); }
        @Override public Map<String, Object> replaceCameraTrack(String timelineId, Object track) { return Map.of("status", "applied"); }
        @Override public Map<String, Object> startExport(String t, int a, int b, int w, int h, int f, String o) { return Map.of("status", "applied"); }
        @Override public Map<String, Object> exportStatus() { return Map.of("status", "applied"); }
        @Override public Map<String, Object> cancelExport() { return Map.of("status", "applied"); }
    }
}
