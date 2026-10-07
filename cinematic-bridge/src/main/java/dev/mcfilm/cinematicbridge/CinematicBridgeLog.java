package dev.mcfilm.cinematicbridge;

/** Tiny logging facade so the pure layer stays dependency-free. */
public final class CinematicBridgeLog {
    private CinematicBridgeLog() {}

    public static void info(String message) {
        System.out.println("[cinematic-bridge] " + message);
    }

    public static void warn(String message) {
        System.out.println("[cinematic-bridge] WARN " + message);
    }
}
