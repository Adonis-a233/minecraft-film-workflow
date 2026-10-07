package dev.mcfilm.cinematicbridge.server;

import dev.mcfilm.cinematicbridge.json.MiniJson;
import dev.mcfilm.cinematicbridge.world.WorldOp;
import dev.mcfilm.cinematicbridge.world.WorldOpParser;
import dev.mcfilm.cinematicbridge.world.WorldOperations;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.LinkedBlockingQueue;

/**
 * Asynchronous write pipeline (workflow v3 §4.1): the HTTP thread validates,
 * journals (fsync) and enqueues — it NEVER waits for the game thread. A
 * single worker owns execution; every terminal outcome lands in the
 * persistent journal regardless of whether any HTTP client is still
 * connected, so a timed-out caller resolves the truth through a status
 * query instead of resending.
 *
 * Idempotency: the key is generated once upstream and travels unchanged; a
 * repeat submit with the same canonical params hash replays the recorded
 * outcome, a different hash is a CONFLICT and is refused.
 */
public final class AsyncOperationService {

    private record Job(String key, WorldOp op) {
    }

    private final PersistentJournal journal;
    private final WorldOperations worldOps;
    private final ClientThreadExecutor executor;
    private final long dispatchTimeoutMillis;
    private final LinkedBlockingQueue<Job> queue = new LinkedBlockingQueue<>();
    private final Thread worker;

    public AsyncOperationService(PersistentJournal journal, WorldOperations worldOps,
                                 ClientThreadExecutor executor, long dispatchTimeoutMillis) {
        this.journal = journal;
        this.worldOps = worldOps;
        this.executor = executor;
        this.dispatchTimeoutMillis = dispatchTimeoutMillis;
        this.worker = new Thread(this::drainForever, "cinematic-bridge-jobs");
        this.worker.setDaemon(true);
        this.worker.start();
    }

    /** Fast path: validate → journal → enqueue. Returns immediately. */
    public Map<String, Object> submit(String method, Map<String, Object> params, String key) {
        String hash = PersistentJournal.paramsHash(params);
        PersistentJournal.Record existing = journal.get(key).orElse(null);
        if (existing != null) {
            if (!method.equals(existing.method) || !hash.equals(existing.paramsHash)) {
                Map<String, Object> result = new LinkedHashMap<>();
                result.put("idempotency_key", key);
                result.put("submitted_params_hash", hash);
                result.put("journaled_params_hash", existing.paramsHash);
                return Map.of("status", "rejected", "error_class", "operation_conflict",
                    "message", "same idempotency key with different parameters; resolve the "
                        + "journaled operation first",
                    "result", result);
            }
            return status(key, true);
        }
        WorldOp op;
        try {
            op = WorldOpParser.parse(method, params);
        } catch (IllegalArgumentException error) {
            return Map.of("status", "rejected", "error_class", "validation_failed",
                "message", String.valueOf(error.getMessage()));
        }
        PersistentJournal.Record record = journal.begin(key, method, hash);
        if (record == null) {
            return submit(method, params, key); // re-check the winning method and parameters
        }
        journal.markQueued(key);
        queue.add(new Job(key, op));
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("idempotency_key", key);
        result.put("method", method);
        result.put("params_hash", hash);
        result.put("journal_state", "queued");
        return Map.of("status", "accepted", "result", result);
    }

    /** Faithful status: the journal is the answer, never a projection of it. */
    public Map<String, Object> status(String key) {
        return status(key, false);
    }

    private Map<String, Object> status(String key, boolean replayed) {
        PersistentJournal.Record record = journal.get(key).orElse(null);
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("idempotency_key", key);
        if (record == null) {
            result.put("journal_state", "unknown");
            result.put("message", "no journaled operation under this key");
            return Map.of("status", "unknown", "error_class", "operation_timeout_unknown",
                "result", result);
        }
        result.put("method", record.method);
        result.put("journal_state", record.state().json());
        result.put("params_hash", record.paramsHash);
        if (record.recoveredFrom() != null) {
            result.put("recovered_from", record.recoveredFrom());
        }
        if (record.proof() != null) {
            result.put("proof", record.proof());
        }
        if (replayed) {
            result.put("replayed", true);
        }
        return switch (record.state()) {
            case SUCCEEDED -> {
                if (record.errorClass() != null) {
                    result.put("message", record.errorMessage());
                }
                yield Map.of("status", "succeeded", "result", result);
            }
            case FAILED -> Map.of("status", "failed",
                "error_class", record.errorClass() == null ? "operation_failed" : record.errorClass(),
                "message", record.errorMessage() == null ? "operation failed" : record.errorMessage(),
                "result", result);
            case UNKNOWN -> Map.of("status", "unknown", "error_class", "operation_timeout_unknown",
                "message", record.errorMessage() == null
                    ? "unproven outcome; resolve before retrying" : record.errorMessage(),
                "result", result);
            case ACCEPTED, QUEUED, RUNNING -> Map.of("status", "pending", "result", result);
        };
    }

    /** Journal lookup shared with the dispatcher's status routing. */
    public boolean knows(String key) {
        return journal.get(key).isPresent();
    }

    // -- worker ------------------------------------------------------------------

    private void drainForever() {
        try {
            while (true) {
                executeJob(queue.take());
            }
        } catch (InterruptedException done) {
            Thread.currentThread().interrupt();
        }
    }

    /** Runs on the worker thread; the game thread executes, the journal records. */
    private void executeJob(Job job) {
        String key = job.key();
        journal.markRunning(key);
        ClientThreadExecutor.Dispatch dispatch;
        try {
            dispatch = executor.dispatch(dispatchTimeoutMillis,
                () -> MiniJson.write(worldOps.prove(job.op())));
        } catch (RuntimeException error) {
            journal.markFailed(key, "environment_mismatch", String.valueOf(error),
                Map.of("error", String.valueOf(error)));
            return;
        }
        if (dispatch.outcome() == ClientThreadExecutor.Outcome.UNPROVEN) {
            journal.markUnknown(key, dispatch.detail());
            return;
        }
        if (dispatch.outcome() == ClientThreadExecutor.Outcome.FAILED) {
            journal.markFailed(key, "operation_failed", dispatch.detail(),
                Map.of("error", String.valueOf(dispatch.detail())));
            return;
        }
        Map<String, Object> proof;
        try {
            proof = asMap(MiniJson.parse(dispatch.output()));
        } catch (RuntimeException error) {
            journal.markUnknown(key, "dispatch proof was unreadable: " + error);
            return;
        }
        if (Boolean.TRUE.equals(proof.get("ok"))) {
            journal.markSucceeded(key, proof);
        } else {
            journal.markFailed(key, "operation_failed",
                "post-write proof did not match: " + proof.get("reason"), proof);
        }
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> asMap(Object value) {
        return value instanceof Map ? (Map<String, Object>) value : new LinkedHashMap<>();
    }
}
