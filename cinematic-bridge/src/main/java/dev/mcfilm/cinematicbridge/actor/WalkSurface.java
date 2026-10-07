package dev.mcfilm.cinematicbridge.actor;

import java.util.List;

/** Choose an actual supported surface, within vanilla's ordinary step height. */
public final class WalkSurface {
    private WalkSurface() {}
    public static double nextHeight(double previous, List<Double> supported) {
        if (!Double.isFinite(previous)) return Double.NaN;
        double best = Double.NaN, change = Double.POSITIVE_INFINITY;
        for (double height : supported) {
            double delta = Math.abs(height - previous);
            if (Double.isFinite(height) && delta <= 0.6001 && delta < change) {
                best = height; change = delta;
            }
        }
        return best;
    }
}
