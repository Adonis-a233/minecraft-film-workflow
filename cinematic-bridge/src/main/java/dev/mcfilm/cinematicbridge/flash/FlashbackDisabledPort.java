package dev.mcfilm.cinematicbridge.flash;

import java.util.Map;

/**
 * Fail-closed default. Every Flashback method returns a structured
 * rejection carrying the license-review reason instead of touching the
 * installed Flashback jar. See docs/licenses.md ("Flashback 许可证边界").
 */
public final class FlashbackDisabledPort implements FlashbackPort {

    public static final String REASON =
        "flashback automation disabled: Flashback license review pending "
        + "(docs/licenses.md); automation requires exact version 0.39.8";

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
        return rejected();
    }

    @Override
    public Map<String, Object> stopRecording(String timelineId) {
        return rejected();
    }

    @Override
    public Map<String, Object> awaitReplaySaved(String timelineId) {
        return rejected();
    }

    @Override
    public Map<String, Object> openReplay(String timelineId) {
        return rejected();
    }

    @Override
    public Map<String, Object> replaceCameraTrack(String timelineId, Object convertedTrack) {
        return rejected();
    }

    @Override
    public Map<String, Object> startExport(String timelineId, int startTick, int endTick,
                                           int width, int height, int fps, String outputPath) {
        return rejected();
    }

    @Override
    public Map<String, Object> exportStatus() {
        return rejected();
    }

    @Override
    public Map<String, Object> cancelExport() {
        return rejected();
    }

    private Map<String, Object> rejected() {
        return Map.of(
            "status", "rejected",
            "error_class", "manual_intervention_required",
            "message", REASON
        );
    }
}
