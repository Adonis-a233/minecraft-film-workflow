package dev.mcfilm.cinematicbridge.actor;

/** Deterministic lowering followed by concealment; does not simulate a pocket. */
public final class PhonePutAwayMotion {
    private PhonePutAwayMotion() {}
    public static float progress(int elapsed,int duration) {
        if(duration<30||duration>60||elapsed<0||elapsed>=duration)
            throw new IllegalArgumentException("put-away requires30..60ticks and bounded elapsed");
        return elapsed/(float)(duration-1);
    }
    public static float lowering(float progress) {
        check(progress);
        float t=Math.min(1f,progress/.65f);
        return t*t*(3-2*t);
    }
    public static boolean visible(float progress) {check(progress);return progress<.75f;}
    private static void check(float progress) {
        if(!Float.isFinite(progress)||progress<0||progress>1)
            throw new IllegalArgumentException("put-away progress outside0..1");
    }
}
