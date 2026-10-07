package dev.mcfilm.cinematicbridge.flash;

import dev.mcfilm.cinematicbridge.core.VersionGate;

import java.util.List;
import java.util.Map;

/**
 * The single Flashback integration point. Per docs/licenses.md the bridge
 * does NOT compile against Flashback and ships only the fail-closed port
 * until the license review re-opens; a future implementation would live
 * behind this interface, guarded by {@link VersionGate#automationAllowed}.
 */
public interface FlashbackPort {

    boolean enabled();

    /** Structured reason when {@link #enabled()} is false. */
    String disabledReason();

    Map<String, Object> startRecording(String timelineId);

    Map<String, Object> stopRecording(String timelineId);

    Map<String, Object> awaitReplaySaved(String timelineId);

    Map<String, Object> openReplay(String timelineId);

    Map<String, Object> replaceCameraTrack(String timelineId, Object convertedTrack);

    Map<String, Object> startExport(String timelineId, int startTick, int endTick,
                                    int width, int height, int fps, String outputPath);

    Map<String, Object> exportStatus();

    Map<String, Object> cancelExport();

    static List<String> unavailableResult() {
        return List.of("flashback automation is disabled");
    }
}
