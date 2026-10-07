package dev.mcfilm.cinematicbridge.state;

import java.util.Locale;
import java.util.Map;

/**
 * Truthful client state under contract v2 (plan v2 §Phase B; failure F8).
 * ``save_name`` is the integrated-server/save name — a dimension registry
 * key is NEVER reported as a world name. Null means "not applicable or not
 * proven in this phase"; the pre-write gate refuses anything short of
 * in_world + exact save + exact dimension + player + not paused.
 */
public record GameStateV2(
    Phase sessionPhase,
    String saveName,
    String dimension,
    String playerName,
    boolean paused,
    Long clientTick,
    Boolean blockingScreen,
    String screenClass
) {

    public enum Phase {
        MAIN_MENU("main_menu"),
        LOADING_WORLD("loading_world"),
        IN_WORLD("in_world"),
        REPLAY_EDITOR("replay_editor"),
        EXPORTING("exporting");

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
            throw new IllegalArgumentException("unknown session_phase: " + value);
        }
    }

    public static GameStateV2 mainMenu() {
        return new GameStateV2(Phase.MAIN_MENU, null, null, null, true, null, true, null);
    }

    public Map<String, Object> toMap() {
        Map<String, Object> map = new java.util.LinkedHashMap<>();
        map.put("schema_version", 2);
        map.put("session_phase", sessionPhase.json());
        map.put("save_name", saveName);
        map.put("dimension", dimension);
        map.put("player_name", playerName);
        map.put("paused", paused);
        map.put("client_tick", clientTick);
        map.put("blocking_screen", blockingScreen);
        if (screenClass != null) {
            // Diagnostic for unattended runs; absent from the wire when null,
            // so frozen contract-2 consumers see no change.
            map.put("screen_class", screenClass);
        }
        return map;
    }

    public static GameStateV2 fromMap(Map<String, Object> map) {
        Object phase = map.get("session_phase");
        Object paused = map.get("paused");
        if (!(phase instanceof String phaseText) || !(paused instanceof Boolean pausedValue)) {
            throw new IllegalArgumentException("session_phase (string) and paused (boolean) are required");
        }
        return new GameStateV2(
            Phase.fromJson(phaseText),
            optionalString(map.get("save_name")),
            optionalString(map.get("dimension")),
            optionalString(map.get("player_name")),
            pausedValue,
            optionalLong(map.get("client_tick")),
            map.get("blocking_screen") instanceof Boolean screen ? screen : null,
            optionalString(map.get("screen_class")));
    }

    /** Refusal reason, or null when typed world writes are provably safe. */
    public String preWriteGate(String expectedSave, String expectedDimension, String expectedPlayer) {
        if (sessionPhase != Phase.IN_WORLD) {
            return "session_phase is " + sessionPhase.json() + ", expected in_world";
        }
        if (!matches(saveName, expectedSave)) {
            return "save_name is " + quote(saveName) + ", expected " + quote(expectedSave);
        }
        if (!matches(dimension, expectedDimension)) {
            return "dimension is " + quote(dimension) + ", expected " + quote(expectedDimension);
        }
        if (!matches(playerName, expectedPlayer)) {
            return "player_name is " + quote(playerName) + ", expected " + quote(expectedPlayer);
        }
        if (paused) {
            return "game is paused";
        }
        return null;
    }

    private static boolean matches(String actual, String expected) {
        return actual != null && actual.toLowerCase(Locale.ROOT).equals(expected.toLowerCase(Locale.ROOT));
    }

    private static String quote(String value) {
        return value == null ? "null" : "'" + value + "'";
    }

    private static String optionalString(Object value) {
        return value instanceof String text && !text.isEmpty() ? text : null;
    }

    private static Long optionalLong(Object value) {
        return value instanceof Number number ? number.longValue() : null;
    }
}
