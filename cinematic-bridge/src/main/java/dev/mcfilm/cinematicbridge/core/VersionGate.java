package dev.mcfilm.cinematicbridge.core;

import java.util.ArrayList;
import java.util.List;

/**
 * Exact-pin version gate (architecture spec §6): any drift — including a
 * near-miss like 0.39.9 — disables Flashback automation. Fail closed.
 */
public final class VersionGate {
    public static final String MINECRAFT = "1.21.1";
    public static final String FABRIC_LOADER = "0.19.3";
    public static final String FLASHBACK = "0.39.8";
    public static final String MOCAP = "1.3.10";
    public static final int CONTRACT = 1;

    private VersionGate() {}

    public record RuntimeVersions(
        String minecraft,
        String fabricLoader,
        String flashback,
        String mocap,
        String bridge,
        int contract
    ) {
        public static RuntimeVersions of(String minecraft, String fabricLoader, String flashback, String mocap) {
            return new RuntimeVersions(minecraft, fabricLoader, flashback, mocap, "0.1.0", CONTRACT);
        }
    }

    public static List<String> mismatches(RuntimeVersions versions) {
        List<String> issues = new ArrayList<>();
        if (!MINECRAFT.equals(versions.minecraft())) {
            issues.add("minecraft: expected " + MINECRAFT + ", bridge reports " + versions.minecraft());
        }
        if (!FABRIC_LOADER.equals(versions.fabricLoader())) {
            issues.add("fabric_loader: expected " + FABRIC_LOADER + ", bridge reports " + versions.fabricLoader());
        }
        if (!FLASHBACK.equals(versions.flashback())) {
            issues.add("flashback: expected " + FLASHBACK + ", bridge reports " + versions.flashback());
        }
        if (!MOCAP.equals(versions.mocap())) {
            issues.add("mocap: expected " + MOCAP + ", bridge reports " + versions.mocap());
        }
        if (versions.contract() != CONTRACT) {
            issues.add("contract: expected " + CONTRACT + ", bridge reports " + versions.contract());
        }
        return issues;
    }

    public static boolean automationAllowed(RuntimeVersions versions) {
        return mismatches(versions).isEmpty();
    }
}
