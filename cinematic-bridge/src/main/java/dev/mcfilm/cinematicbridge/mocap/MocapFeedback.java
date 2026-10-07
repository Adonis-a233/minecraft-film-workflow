package dev.mcfilm.cinematicbridge.mocap;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Classifier for Motion Capture client feedback (plan v2 §Phase D).
 *
 * The Motion Capture license permits command-surface invocation but no blind
 * success claims, so the bridge observes the mod's own feedback. Pins are
 * exact matches distilled from the real live session (see
 * contracts/v2/fixtures/transcripts/) — the fixture tests keep this table and
 * those files in lockstep. ANY unmatched line classifies as UNKNOWN and fails
 * closed: changed wording must break a test, never fake a success.
 */
public enum MocapFeedback {
    WAITING_FOR_SELECTION,
    WAITING_CANCELLED,
    SAVE_REJECTED_EMPTY,
    RECORDING_STARTED,
    RECORDING_STOPPED,
    RECORDING_DISCARDED,
    SAVE_SUCCESS,
    UNKNOWN;

    // zh_cn pins (live log 2026-09-03, work/logs/game-live-20260903-160200.log)
    private static final String ZH_WAITING_PREFIX =
        "执行任何操作或再次使用\"/mocap recording start\"以开始录制";
    private static final String ZH_WAITING_CANCELLED = "已停止等待选择";
    private static final String ZH_SAVE_REJECTED_EMPTY = "没有可以保存的东西";
    private static final String ZH_NEED_RECORDING_FIRST = "你需要先开始录制";
    private static final String ZH_STARTED = "录制开始……";
    private static final String ZH_STOPPED_PREFIX = "录制停止——等待选择中";
    private static final String ZH_SAVE_SUCCESS = "录像已成功保存";

    // en_us pins from the locked Mocap 1.3.10 language resources and live recording.
    private static final String EN_WAITING_PREFIX =
        "Take any action or use \"/mocap recording start\" again to start recording";
    private static final String EN_WAITING_CANCELLED = "No longer waiting for action";
    private static final String EN_SAVE_REJECTED_EMPTY = "there is nothing to save!";
    private static final String EN_NEED_RECORDING_FIRST = "You need to start recording first";
    private static final String EN_STARTED = "Recording started...";
    private static final String EN_STOPPED_PREFIX = "Recording stopped - waiting for decision";
    private static final String EN_SAVE_SUCCESS = "Recording successfully saved";

    public static MocapFeedback classify(String rawLine) {
        String line = stripFormatting(rawLine);
        if (line == null || line.isBlank()) {
            return UNKNOWN;
        }
        if (line.startsWith(ZH_WAITING_PREFIX) || line.startsWith(EN_WAITING_PREFIX)) {
            return WAITING_FOR_SELECTION;
        }
        if (line.equals(ZH_WAITING_CANCELLED) || line.equals(EN_WAITING_CANCELLED)) {
            return WAITING_CANCELLED;
        }
        if (line.contains(ZH_SAVE_REJECTED_EMPTY) || line.contains(EN_SAVE_REJECTED_EMPTY)) {
            return SAVE_REJECTED_EMPTY;
        }
        if (line.contains(ZH_NEED_RECORDING_FIRST) || line.contains(EN_NEED_RECORDING_FIRST)) {
            return SAVE_REJECTED_EMPTY; // second line of the same rejection
        }
        if (line.equals(ZH_STARTED) || line.equals(EN_STARTED)) {
            return RECORDING_STARTED;
        }
        if (line.startsWith(ZH_STOPPED_PREFIX) || line.startsWith(EN_STOPPED_PREFIX)) {
            return RECORDING_STOPPED;
        }
        if (line.equals(ZH_SAVE_SUCCESS) || line.equals(EN_SAVE_SUCCESS)) {
            return SAVE_SUCCESS;
        }
        if (line.equals("Recording discarded")) return RECORDING_DISCARDED;
        return UNKNOWN;
    }

    /** Evidence bundle for a classified line (feeds MocapStateV2 fields). */
    public static Map<String, Object> evidence(String rawLine) {
        MocapFeedback feedback = classify(rawLine);
        Map<String, Object> map = new LinkedHashMap<>();
        map.put("feedback", feedback.name());
        map.put("line", truncate(stripFormatting(rawLine), 500));
        return map;
    }

    /**
     * Removes legacy formatting codes (§l §r §a …) so pins do not depend on
     * styling. Everything else — including order — must match exactly.
     */
    public static String stripFormatting(String line) {
        if (line == null) {
            return null;
        }
        return line.replaceAll("§.", "").trim();
    }

    private static String truncate(String value, int maxLength) {
        if (value == null || value.length() <= maxLength) {
            return value;
        }
        return value.substring(0, maxLength);
    }
}
