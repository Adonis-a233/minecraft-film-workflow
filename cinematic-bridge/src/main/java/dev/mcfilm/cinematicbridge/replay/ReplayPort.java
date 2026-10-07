package dev.mcfilm.cinematicbridge.replay;

import java.util.List;
import java.util.Map;

/**
 * The single replay-master integration point (workflow v3 §5/§7-P1).
 *
 * The bridge compiles against ReplayMod only through {@code ReplayModBinding}
 * (pinned 1.21-2.6.27, GPL-3.0-or-later — see docs/licenses.md). Until that
 * binding is wired by the mod entrypoint, only the fail-closed port ships —
 * a disabled port can never be the reason an export "succeeded".
 *
 * A binding reports itself through the v3 capability payload as
 * {@code replay_backend: "replaymod"}.
 */
public interface ReplayPort {

    /** Brand-neutral backend name for the v3 capability payload. */
    String backendName();

    boolean enabled();

    /** Structured reason when {@link #enabled()} is false. */
    String disabledReason();

    Map<String, Object> startRecording(String timelineId);

    Map<String, Object> stopRecording(String timelineId);

    /** Native recording clock, read only on the client thread; -1 if unavailable. */
    default long recordingTimestamp(String timelineId) { return -1; }

    Map<String, Object> awaitMasterSaved(String timelineId);

    Map<String, Object> openMaster(String timelineId);

    default Map<String,Object> masterStatus() {
        return Map.of("status", "rejected", "error_class", "editor_not_ready", "message", "master status unavailable");
    }

    default boolean matchesHash(String timelineId, String hash) { return false; }

    /** Raw compiler keyframes ({tick, position[3], rotation[3], fov}); each
     * binding maps them onto its own camera representation. */
    Map<String, Object> replaceCameraTrack(String timelineId,
                                           List<Map<String, Object>> keyframes,
                                           String interpolation);

    Map<String, Object> startRender(String timelineId, int startTick, int endTick,
                                    int width, int height, int fps, String outputPath);

    Map<String, Object> renderStatus();

    Map<String, Object> cancelRender();
}
