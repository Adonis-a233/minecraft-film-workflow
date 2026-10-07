package dev.mcfilm.cinematicbridge.actor;

/** Twelve server ticks of visible loss of balance, then a stable seated pose. */
public final class FallMotion {
    public static float progress(int elapsed) {
        if(elapsed<0)throw new IllegalArgumentException("negative fall clock");
        float p=Math.min(1,(elapsed+1)/12f);
        return p*p*(3-2*p);
    }
    private FallMotion() {}
}
