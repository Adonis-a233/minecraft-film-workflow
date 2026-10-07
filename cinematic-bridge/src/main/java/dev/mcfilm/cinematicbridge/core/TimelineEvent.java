package dev.mcfilm.cinematicbridge.core;

import java.util.Map;

/** One validated, tick-stamped event of a {@code TimelinePlan} (contracts/v1). */
public record TimelineEvent(int tick, String type, Map<String, Object> payload) {

    public static final String ASSERT_STATE = "assert_state";
    public static final String FLASHBACK_START = "flashback.start_recording";
    public static final String FLASHBACK_STOP = "flashback.stop_recording";
    public static final String MOCAP_SCENE_CREATE = "mocap.scene_create";
    public static final String MOCAP_SCENE_ADD = "mocap.scene_add";
    public static final String MOCAP_SCENE_PLAY = "mocap.scene_play";
    public static final String MOCAP_SCENE_STOP = "mocap.scene_stop";

    public TimelineEvent {
        payload = payload == null ? Map.of() : Map.copyOf(payload);
    }
}
