package dev.mcfilm.cinematicbridge.core;

import java.util.Map;

/** Render-owned optics override; never changes the user's saved FOV setting. */
public final class FovState {
    private static boolean active;
    private static double current = 70, minimum, maximum;
    private static int samples;
    private FovState() {}
    public static void begin() { active=true; current=70; samples=0; minimum=150; maximum=1; }
    public static void set(double value) {
        if (!Double.isFinite(value) || value<1 || value>150) throw new IllegalArgumentException("FOV must be within [1,150]");
        current=value;
    }
    public static Double rendered() {
        if (!active) return null;
        samples++; minimum=Math.min(minimum,current); maximum=Math.max(maximum,current);
        return current;
    }
    public static Map<String,Object> evidence() {
        return Map.of("samples",samples,"minimum_degrees",minimum,"maximum_degrees",maximum);
    }
    public static void end() { active=false; }
}
