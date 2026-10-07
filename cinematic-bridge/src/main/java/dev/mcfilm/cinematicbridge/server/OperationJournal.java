package dev.mcfilm.cinematicbridge.server;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

/**
 * Bounded in-memory operation journal (plan v2 §Phase B). Every write is
 * journaled under its idempotency key before dispatch; the key is the ONLY
 * way a retry may resolve a previous attempt — a resend without consulting
 * the journal is a bug, and a journal answer of UNKNOWN forbids claiming
 * success.
 *
 * Lifecycle: accepted → queued → dispatched → observed | rejected | unknown
 * with late proofs allowed (unknown → observed, unknown → rejected).
 * REJECTED and OBSERVED are terminal; UNKNOWN persists until a status query
 * or a state read resolves it.
 *
 * Bounded: at {@link #MAX_ENTRIES} the journal evicts the oldest terminal
 * records. If no record is terminal, new WRITES are refused — the journal
 * never discards an unproven outcome to make room (a lost proof must stay
 * visible), and the caller maps that refusal to operation_rejected.
 */
public final class OperationJournal {

    public enum State {
        ACCEPTED, QUEUED, DISPATCHED, OBSERVED, REJECTED, UNKNOWN;

        /** snake_case name used on the wire (contract v2 journal_state). */
        public String json() {
            return name().toLowerCase(java.util.Locale.ROOT);
        }
    }

    public static final class Record {
        public final String idempotencyKey;
        public final String method;
        public final long sequence;
        private State state;
        // OBSERVED alone never means success (v3 §2: false-success hole).
        // proofOk == FALSE marks a proven post-condition failure; the status
        // query must report failed, never applied.
        private Boolean proofOk;
        private Map<String, Object> proof;

        Record(String idempotencyKey, String method, long sequence) {
            this.idempotencyKey = idempotencyKey;
            this.method = method;
            this.sequence = sequence;
            this.state = State.ACCEPTED;
        }

        public State state() {
            return state;
        }

        /** null until observed; FALSE means the proof read contradicted the goal. */
        public Boolean proofOk() {
            return proofOk;
        }

        public Map<String, Object> proof() {
            return proof;
        }

        void proof(boolean ok, Map<String, Object> evidence) {
            this.proofOk = ok;
            // Proof maps may legitimately carry nulls (e.g. command: null on a
            // replay), so a plain defensive copy replaces Map.copyOf here.
            this.proof = evidence == null ? null : new LinkedHashMap<>(evidence);
        }

        void transition(State target) {
            if (!OperationJournal.canTransition(this.state, target)) {
                throw new IllegalStateException(
                    "illegal journal transition " + this.state + " -> " + target
                    + " for " + idempotencyKey);
            }
            this.state = target;
        }

        public Map<String, Object> toMap() {
            Map<String, Object> map = new LinkedHashMap<>();
            map.put("idempotency_key", idempotencyKey);
            map.put("method", method);
            map.put("journal_state", state.json());
            map.put("sequence", sequence);
            if (proof != null) {
                map.put("proof", proof);
            }
            return map;
        }
    }

    public static final int MAX_ENTRIES = 1024;

    private final LinkedHashMap<String, Record> records = new LinkedHashMap<>();
    private long sequence = 0;

    /** Journaled lookup BEFORE any retry: returns the recorded outcome. */
    public synchronized Optional<Record> get(String idempotencyKey) {
        return Optional.ofNullable(records.get(idempotencyKey));
    }

    public synchronized Optional<State> stateOf(String idempotencyKey) {
        return get(idempotencyKey).map(Record::state);
    }

    /**
     * Opens a journal entry for a new write. Returns null when the journal is
     * full of unproven outcomes — the caller must refuse the write instead of
     * discarding evidence.
     */
    public synchronized Record open(String idempotencyKey, String method) {
        Record existing = records.get(idempotencyKey);
        if (existing != null) {
            return existing; // idempotent re-entry: never open twice
        }
        if (!evictOverflow()) {
            return null;
        }
        Record record = new Record(idempotencyKey, method, ++sequence);
        records.put(idempotencyKey, record);
        return record;
    }

    public synchronized void markQueued(String key) {
        require(key).transition(State.QUEUED);
    }

    public synchronized void markDispatched(String key) {
        require(key).transition(State.DISPATCHED);
    }

    /** Mocap-style observation: the recorded feedback is the success signal. */
    public synchronized void markObserved(String key) {
        require(key).transition(State.OBSERVED);
        require(key).proof(true, null);
    }

    /** Observation with the proof attached; proof.ok decides applied vs failed. */
    public synchronized void markObserved(String key, Map<String, Object> proof) {
        require(key).transition(State.OBSERVED);
        boolean ok = Boolean.TRUE.equals(proof.get("ok"));
        require(key).proof(ok, proof);
    }

    /** Proven failure without a proof map (dispatch threw before any write). */
    public synchronized void markObservedFailed(String key, String detail) {
        require(key).transition(State.OBSERVED);
        require(key).proof(false, Map.of("error", String.valueOf(detail)));
    }

    public synchronized void markRejected(String key) {
        require(key).transition(State.REJECTED);
    }

    public synchronized void markUnknown(String key) {
        require(key).transition(State.UNKNOWN);
    }

    public synchronized int size() {
        return records.size();
    }

    /** Diagnostics snapshot, oldest first. */
    public synchronized List<Map<String, Object>> snapshot() {
        List<Map<String, Object>> out = new ArrayList<>();
        for (Record record : records.values()) {
            out.add(record.toMap());
        }
        return out;
    }

    private Record require(String key) {
        Record record = records.get(key);
        if (record == null) {
            throw new IllegalArgumentException("no journal entry for " + key);
        }
        return record;
    }

    private boolean evictOverflow() {
        while (records.size() >= MAX_ENTRIES) {
            String evictable = null;
            for (Map.Entry<String, Record> entry : records.entrySet()) {
                State state = entry.getValue().state();
                if (state == State.OBSERVED || state == State.REJECTED) {
                    evictable = entry.getKey();
                    break; // oldest terminal entry wins (insertion order)
                }
            }
            if (evictable == null) {
                return false; // everything unproven: refuse rather than forget
            }
            records.remove(evictable);
        }
        return true;
    }

    static boolean canTransition(State from, State to) {
        if (from == to) {
            return to == State.OBSERVED; // re-observation of a proven outcome is fine
        }
        return switch (from) {
            case ACCEPTED -> to == State.QUEUED || to == State.REJECTED;
            case QUEUED -> to == State.DISPATCHED || to == State.REJECTED || to == State.UNKNOWN;
            case DISPATCHED -> to == State.OBSERVED || to == State.REJECTED || to == State.UNKNOWN;
            case UNKNOWN -> to == State.OBSERVED || to == State.REJECTED;
            case OBSERVED, REJECTED -> false;
        };
    }
}
