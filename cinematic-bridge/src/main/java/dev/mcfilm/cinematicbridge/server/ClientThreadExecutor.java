package dev.mcfilm.cinematicbridge.server;

import java.util.concurrent.Callable;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;

/**
 * CompletableFuture-based client-thread executor (plan v2 §Phase B). The old
 * ``runOnClientThread`` returned BEFORE the scheduled task proved execution,
 * which let writes be acknowledged as applied with no evidence (failure F5).
 *
 * The HTTP thread may wait only for a bounded dispatch acknowledgement:
 * - PROVEN: the task ran on the client thread and returned a value;
 * - FAILED: the task ran and threw (a proven failure — safe to report);
 * - UNPROVEN: no acknowledgement within the budget — the outcome is UNKNOWN.
 *   The task may still execute later, so the caller must record UNKNOWN in
 *   the journal and resolve it via a status query, never by resending.
 *
 * Pure JDK: the Minecraft binding injects {@link Runner} = client::execute.
 */
public final class ClientThreadExecutor {

    /** Submits a runnable onto the Minecraft client thread (e.g. client.execute). */
    @FunctionalInterface
    public interface Runner {
        void execute(Runnable task);
    }

    public enum Outcome { PROVEN, FAILED, UNPROVEN }

    public record Dispatch(Outcome outcome, String output, String detail) {
        public static Dispatch proven(String output) {
            return new Dispatch(Outcome.PROVEN, output, null);
        }

        public static Dispatch failed(String detail) {
            return new Dispatch(Outcome.FAILED, null, detail);
        }

        public static Dispatch unproven(String detail) {
            return new Dispatch(Outcome.UNPROVEN, null, detail);
        }

        public boolean proven() {
            return outcome == Outcome.PROVEN;
        }
    }

    /** Runs the task inline (tests, and calls already on the client thread). */
    public static ClientThreadExecutor direct() {
        return new ClientThreadExecutor(Runnable::run);
    }

    private final Runner runner;

    public ClientThreadExecutor(Runner runner) {
        this.runner = runner;
    }

    public Dispatch dispatch(long timeoutMillis, Callable<String> task) {
        CompletableFuture<String> future = new CompletableFuture<>();
        try {
            runner.execute(() -> {
                try {
                    future.complete(task.call());
                } catch (Throwable error) {
                    future.completeExceptionally(error);
                }
            });
        } catch (Throwable rejected) {
            // The runner refused the task before it ever started (e.g. no
            // integrated server). That is a PROVEN failure — the task cannot
            // land later, so UNKNOWN would be a lie.
            return Dispatch.failed("runner refused the task: " + rejected);
        }
        try {
            return Dispatch.proven(future.get(timeoutMillis, TimeUnit.MILLISECONDS));
        } catch (TimeoutException timeout) {
            return Dispatch.unproven("no dispatch acknowledgement within " + timeoutMillis + " ms");
        } catch (ExecutionException error) {
            return Dispatch.failed(String.valueOf(error.getCause()));
        } catch (InterruptedException error) {
            Thread.currentThread().interrupt();
            return Dispatch.unproven("dispatch wait interrupted");
        }
    }
}
