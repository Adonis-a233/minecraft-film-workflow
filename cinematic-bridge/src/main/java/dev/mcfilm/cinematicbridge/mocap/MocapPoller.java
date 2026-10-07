package dev.mcfilm.cinematicbridge.mocap;

import dev.mcfilm.cinematicbridge.state.MocapStateV2;

import java.util.function.BooleanSupplier;
import java.util.function.Supplier;

/**
 * Bounded observation loop for Mocap transitions (plan v2 §Phase D): after a
 * transition is dispatched, the phase is POLLED until it matches the expected
 * phase or the budget runs out — the dispatch itself never counts as proof.
 * The sleeper is injected so tests stay deterministic (no real waiting).
 */
public final class MocapPoller {

    public record Result(boolean reached, MocapStateV2.Phase observedPhase, int polls) {}

    private final Supplier<MocapStateV2.Phase> phaseSupplier;
    private final BooleanSupplier sleeper;

    public MocapPoller(Supplier<MocapStateV2.Phase> phaseSupplier, BooleanSupplier sleeper) {
        this.phaseSupplier = phaseSupplier;
        this.sleeper = sleeper;
    }

    /** Polls until phase == expected; `maxPolls` attempts, sleeping between them. */
    public Result await(MocapStateV2.Phase expected, int maxPolls) {
        return await(expected,maxPolls,false);
    }

    /** The selected actor can trigger Mocap's automatic start between two polls. */
    public Result await(MocapStateV2.Phase expected, int maxPolls, boolean allowAutomaticStart) {
        MocapStateV2.Phase observed = phaseSupplier.get();
        for (int poll = 1; poll <= maxPolls; poll++) {
            if (observed == expected || (allowAutomaticStart && observed == MocapStateV2.Phase.RECORDING)) {
                return new Result(true, observed, poll);
            }
            if (observed == MocapStateV2.Phase.UNKNOWN) {
                return new Result(false, observed, poll); // fail closed immediately
            }
            if (poll < maxPolls && !sleeper.getAsBoolean()) {
                return new Result(false, observed, poll); // sleeper aborted (interrupt)
            }
            observed = phaseSupplier.get();
        }
        return new Result(false, observed, maxPolls);
    }

    public static MocapPoller live(Supplier<MocapStateV2.Phase> phaseSupplier, long sleepMillis) {
        return new MocapPoller(phaseSupplier, () -> {
            try {
                Thread.sleep(sleepMillis);
                return true;
            } catch (InterruptedException error) {
                Thread.currentThread().interrupt();
                return false;
            }
        });
    }
}
