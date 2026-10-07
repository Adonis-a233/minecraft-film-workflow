package dev.mcfilm.cinematicbridge.state;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Observed Motion Capture recorder state under contract v2 (failures F6/F7).
 * The live run proved the two-step start: the FIRST start lands in
 * waiting_for_selection, only a SECOND start begins recording. State changes
 * come from classified client feedback — command dispatch alone is never a
 * transition, and unrecognized feedback maps to UNKNOWN (fail closed).
 */
public record MocapStateV2(
    Phase state,
    String recordingName,
    String lastFeedback,
    String lastFeedbackKey,
    Artifact artifact
) {

    public enum Phase {
        IDLE("idle"),
        WAITING_FOR_SELECTION("waiting_for_selection"),
        RECORDING("recording"),
        RECORDED_UNSAVED("recorded_unsaved"),
        SAVED("saved"),
        DISCARDED("discarded"),
        REJECTED("rejected"),
        UNKNOWN("unknown");

        private final String json;

        Phase(String json) {
            this.json = json;
        }

        public String json() {
            return json;
        }

        public static Phase fromJson(String value) {
            for (Phase phase : values()) {
                if (phase.json.equals(value)) {
                    return phase;
                }
            }
            throw new IllegalArgumentException("unknown mocap state: " + value);
        }
    }

    public record Artifact(String name, long bytes, String sha256) {
        public Map<String, Object> toMap() {
            Map<String, Object> map = new LinkedHashMap<>();
            map.put("name", name);
            map.put("bytes", bytes);
            if (sha256 != null) {
                map.put("sha256", sha256);
            }
            return map;
        }
    }

    public MocapStateV2 {
        if (state == null) {
            throw new IllegalArgumentException("mocap state is required");
        }
    }

    public static MocapStateV2 unknown() {
        return new MocapStateV2(Phase.UNKNOWN, null, null, null, null);
    }

    public Map<String, Object> toMap() {
        Map<String, Object> map = new LinkedHashMap<>();
        map.put("schema_version", 2);
        map.put("state", state.json());
        map.put("recording_name", recordingName);
        map.put("last_feedback", lastFeedback);
        map.put("last_feedback_key", lastFeedbackKey);
        map.put("artifact", artifact == null ? null : artifact.toMap());
        return map;
    }

    @SuppressWarnings("unchecked")
    public static MocapStateV2 fromMap(Map<String, Object> map) {
        Object state = map.get("state");
        if (!(state instanceof String stateText)) {
            throw new IllegalArgumentException("state (string) is required");
        }
        Artifact artifact = null;
        if (map.get("artifact") instanceof Map<?, ?> rawArtifact) {
            Map<String, Object> artifactMap = (Map<String, Object>) rawArtifact;
            artifact = new Artifact(
                String.valueOf(artifactMap.get("name")),
                artifactMap.get("bytes") instanceof Number number ? number.longValue() : 0,
                artifactMap.get("sha256") == null ? null : String.valueOf(artifactMap.get("sha256")));
        }
        return new MocapStateV2(
            Phase.fromJson(stateText),
            map.get("recording_name") == null ? null : String.valueOf(map.get("recording_name")),
            map.get("last_feedback") == null ? null : String.valueOf(map.get("last_feedback")),
            map.get("last_feedback_key") == null ? null : String.valueOf(map.get("last_feedback_key")),
            artifact);
    }
}
