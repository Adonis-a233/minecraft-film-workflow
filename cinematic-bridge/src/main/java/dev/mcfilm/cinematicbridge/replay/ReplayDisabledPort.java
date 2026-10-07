package dev.mcfilm.cinematicbridge.replay;

import java.util.Map;

/**
 * Fail-closed default (workflow v3 §7-P1): no ReplayMod binding is installed,
 * so every replay-master operation is refused with a structured reason.
 * Shipping this port is deliberate — a missing renderer must surface as a
 * rejection, never as a skipped stage that pretends the pipeline works.
 */
public final class ReplayDisabledPort implements ReplayPort {

    public static final String REASON =
        "replaymod binding not installed; the pinned candidate "
        + "(replaymod-1.21-2.6.27, GPL-3.0-or-later, sha1 3d8c902defdd4834c17af40c3d8b10e9fff44919) "
        + "awaits the P1 candidate-instance acceptance";

    @Override
    public String backendName() {
        return "none";
    }

    @Override
    public boolean enabled() {
        return false;
    }

    @Override
    public String disabledReason() {
        return REASON;
    }

    @Override
    public Map<String, Object> startRecording(String timelineId) {
        return unavailable("replay.start_recording");
    }

    @Override
    public Map<String, Object> stopRecording(String timelineId) {
        return unavailable("replay.stop_recording");
    }

    @Override
    public Map<String, Object> awaitMasterSaved(String timelineId) {
        return unavailable("replay.await_master_saved");
    }

    @Override
    public Map<String, Object> openMaster(String timelineId) {
        return unavailable("replay.open_master");
    }

    @Override
    public Map<String, Object> replaceCameraTrack(String timelineId,
                                                  java.util.List<Map<String, Object>> keyframes,
                                                  String interpolation) {
        return unavailable("replay.replace_camera_track");
    }

    @Override
    public Map<String, Object> startRender(String timelineId, int startTick, int endTick,
                                           int width, int height, int fps, String outputPath) {
        return unavailable("replay.start_render");
    }

    @Override
    public Map<String, Object> renderStatus() {
        return unavailable("replay.get_render_status");
    }

    @Override
    public Map<String, Object> cancelRender() {
        return unavailable("replay.cancel_render");
    }

    private static Map<String, Object> unavailable(String method) {
        return Map.of(
            "status", "rejected",
            "error_class", "manual_intervention_required",
            "message", method + ": " + REASON,
            "result", Map.of("backend", "none"));
    }
}
