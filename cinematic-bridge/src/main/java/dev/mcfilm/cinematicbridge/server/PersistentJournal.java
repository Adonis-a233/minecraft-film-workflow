package dev.mcfilm.cinematicbridge.server;

import dev.mcfilm.cinematicbridge.json.MiniJson;

import java.io.IOException;
import java.nio.channels.FileChannel;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.TreeMap;

/**
 * Append-only, fsync-per-transition operation journal (workflow v3 §4.4).
 * The in-memory ledger is rebuilt by replaying the event log; a crashed
 * process loses nothing that was acknowledged, because an event is only
 * reported after its line hit disk.
 *
 * Lifecycle: accepted → queued → running → succeeded | failed | unknown,
 * with late proofs allowed (unknown → succeeded | failed). A record left
 * non-terminal by a crash is recovered as UNKNOWN carrying
 * ``recovered_from`` — it blocks dependents until a status query or a state
 * read converges it.
 *
 * The ledger is NOT in one transaction with the Minecraft world save (v3
 * §4.8): recovery therefore keeps ambiguity visible instead of pretending
 * exactly-once semantics.
 */
public final class PersistentJournal {

    public enum State {
        ACCEPTED, QUEUED, RUNNING, SUCCEEDED, FAILED, UNKNOWN;

        /** snake_case name used on the wire (contract v3 journal_state). */
        public String json() {
            return name().toLowerCase(java.util.Locale.ROOT);
        }
    }

    public static final class Record {
        public final String idempotencyKey;
        public final String method;
        public final long sequence;
        public final String paramsHash;
        private State state;
        private Map<String, Object> proof;
        private String errorClass;
        private String errorMessage;
        private String recoveredFrom;
        private long updatedAt;

        Record(String idempotencyKey, String method, long sequence, String paramsHash, long ts) {
            this.idempotencyKey = idempotencyKey;
            this.method = method;
            this.sequence = sequence;
            this.paramsHash = paramsHash;
            this.state = State.ACCEPTED;
            this.updatedAt = ts;
        }

        public State state() {
            return state;
        }

        public Map<String, Object> proof() {
            return proof;
        }

        public String errorClass() {
            return errorClass;
        }

        public String errorMessage() {
            return errorMessage;
        }

        public String recoveredFrom() {
            return recoveredFrom;
        }

        public long updatedAt() {
            return updatedAt;
        }

        public Map<String, Object> toMap() {
            Map<String, Object> map = new LinkedHashMap<>();
            map.put("idempotency_key", idempotencyKey);
            map.put("method", method);
            map.put("journal_state", state.json());
            map.put("sequence", sequence);
            map.put("params_hash", paramsHash);
            map.put("updated_at", updatedAt);
            if (recoveredFrom != null) {
                map.put("recovered_from", recoveredFrom);
            }
            if (errorClass != null) {
                map.put("error_class", errorClass);
            }
            if (errorMessage != null) {
                map.put("message", errorMessage);
            }
            if (proof != null) {
                map.put("proof", proof);
            }
            return map;
        }
    }

    /** One journaled transition; serialized as a JSONL line. */
    private record Event(long seq, String key, String method, String paramsHash,
                         String event, Map<String, Object> proof,
                         String errorClass, String message, long ts) {
    }

    public static final String FILE_NAME = "operations.jsonl";

    private final Path dir;
    private final FileChannel channel;
    private final LinkedHashMap<String, Record> records = new LinkedHashMap<>();
    private long sequence = 0;

    private PersistentJournal(Path dir, FileChannel channel) {
        this.dir = dir;
        this.channel = channel;
    }

    /** Opens (and recovers) the journal rooted at {@code dir/operations.jsonl}. */
    public static PersistentJournal open(Path dir) throws IOException {
        Files.createDirectories(dir);
        Path file = dir.resolve(FILE_NAME);
        FileChannel channel = FileChannel.open(file,
            StandardOpenOption.CREATE, StandardOpenOption.READ, StandardOpenOption.WRITE);
        PersistentJournal journal = new PersistentJournal(dir, channel);
        journal.recover(channel);
        return journal;
    }

    public Path directory() {
        return dir;
    }

    // -- recovery ---------------------------------------------------------------

    private void recover(FileChannel channel) throws IOException {
        long size = channel.size();
        if (size == 0) {
            return;
        }
        var buffer = java.nio.ByteBuffer.allocate((int) size);
        long readOffset = 0;
        while (buffer.hasRemaining()) {
            int read = channel.read(buffer, readOffset);
            if (read <= 0) throw new IOException("incomplete journal read");
            readOffset += read;
        }
        String content = new String(buffer.array(), StandardCharsets.UTF_8);
        String[] lines = content.split("\n", -1);
        String corruptTail = null;
        long validBytes = 0;
        for (int i = 0; i < lines.length; i++) {
            String line = lines[i].trim();
            if (line.isEmpty()) {
                validBytes += lines[i].getBytes(StandardCharsets.UTF_8).length + (i < lines.length - 1 ? 1 : 0);
                continue;
            }
            Map<String, Object> parsed;
            try {
                parsed = asMap(MiniJson.parse(line));
            } catch (RuntimeException corrupt) {
                if (i == lines.length - 1 || i == lines.length - 2 && lines[lines.length - 1].trim().isEmpty()) {
                    // Torn write from a crash mid-append: drop the tail, keep
                    // every acknowledged earlier event.
                    corruptTail = "dropped torn tail line " + (i + 1);
                    continue;
                }
                throw new IOException("operation journal is corrupt at line " + (i + 1)
                    + " (not a torn tail); refusing to guess", corrupt);
            }
            apply(parsed, null);
            validBytes += lines[i].getBytes(StandardCharsets.UTF_8).length + (i < lines.length - 1 ? 1 : 0);
        }
        // Any record that never reached a terminal state is now UNKNOWN.
        List<Record> inflight = new ArrayList<>();
        for (Record record : records.values()) {
            if (record.state() != State.SUCCEEDED && record.state() != State.FAILED) {
                inflight.add(record);
            }
        }
        for (Record record : inflight) {
            String from = record.state().json();
            record.state = State.UNKNOWN;
            record.recoveredFrom = from;
            record.errorMessage = "process restarted before this operation reached a terminal state";
            record.updatedAt = System.currentTimeMillis();
        }
        sequence = records.values().stream().mapToLong(record -> record.sequence).max().orElse(0);
        if (corruptTail != null) {
            channel.truncate(validBytes);
            channel.force(true);
            append(Map.of("event", "recovery_note", "note", corruptTail,
                "ts", System.currentTimeMillis()));
        }
    }

    // -- lookup / lifecycle -------------------------------------------------------

    public synchronized Optional<Record> get(String idempotencyKey) {
        return Optional.ofNullable(records.get(idempotencyKey));
    }

    /**
     * Opens a fresh ACCEPTED record. Returns null when the key already
     * exists — the caller then replays or reports a conflict (never reopens).
     */
    public synchronized Record begin(String idempotencyKey, String method, String paramsHash) {
        if (records.containsKey(idempotencyKey)) {
            return null;
        }
        Record record = new Record(idempotencyKey, method, ++sequence, paramsHash,
            System.currentTimeMillis());
        Map<String, Object> event = new LinkedHashMap<>();
        event.put("seq", record.sequence);
        event.put("key", idempotencyKey);
        event.put("method", method);
        event.put("params_hash", paramsHash);
        event.put("event", "accepted");
        event.put("ts", record.updatedAt);
        append(event);
        records.put(idempotencyKey, record);
        return record;
    }

    public synchronized void markQueued(String key) {
        transition(key, State.QUEUED, "queued", null, null, null);
    }

    public synchronized void markRunning(String key) {
        transition(key, State.RUNNING, "running", null, null, null);
    }

    public synchronized void markSucceeded(String key, Map<String, Object> proof) {
        transition(key, State.SUCCEEDED, "succeeded", proof, null, null);
    }

    public synchronized void markFailed(String key, String errorClass, String message,
                                        Map<String, Object> proof) {
        transition(key, State.FAILED, "failed", proof, errorClass, message);
    }

    public synchronized void markUnknown(String key, String message) {
        transition(key, State.UNKNOWN, "unknown", null, "operation_timeout_unknown", message);
    }

    private void transition(String key, State target, String event, Map<String, Object> proof,
                            String errorClass, String message) {
        Record record = records.get(key);
        if (record == null) {
            throw new IllegalArgumentException("no journal entry for " + key);
        }
        if (!canTransition(record.state, target)) {
            throw new IllegalStateException("illegal journal transition " + record.state
                + " -> " + target + " for " + key);
        }
        record.state = target;
        record.updatedAt = System.currentTimeMillis();
        if (proof != null) {
            record.proof = new LinkedHashMap<>(proof); // proof maps may carry nulls
        }
        record.errorClass = errorClass;
        record.errorMessage = message;
        Map<String, Object> line = new LinkedHashMap<>();
        line.put("seq", record.sequence);
        line.put("key", key);
        line.put("method", record.method);
        line.put("params_hash", record.paramsHash);
        line.put("event", event);
        line.put("ts", record.updatedAt);
        if (proof != null) {
            line.put("proof", proof);
        }
        if (errorClass != null) {
            line.put("error_class", errorClass);
        }
        if (message != null) {
            line.put("message", message);
        }
        append(line);
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

    // -- internals -----------------------------------------------------------------

    private void apply(Map<String, Object> event, String note) {
        String key = (String) event.get("key");
        String kind = (String) event.get("event");
        if (key == null || kind == null) {
            return;
        }
        long seq = event.get("seq") instanceof Number number ? number.longValue() : 0;
        long ts = event.get("ts") instanceof Number number ? number.longValue() : 0;
        if ("accepted".equals(kind)) {
            Record record = new Record(key, (String) event.get("method"), seq,
                (String) event.get("params_hash"), ts);
            records.put(key, record);
            return;
        }
        Record record = records.get(key);
        if (record == null) {
            return;
        }
        record.updatedAt = ts > 0 ? ts : record.updatedAt;
        switch (kind) {
            case "queued" -> record.state = State.QUEUED;
            case "running" -> record.state = State.RUNNING;
            case "succeeded" -> {
                record.state = State.SUCCEEDED;
                record.proof = asMap(event.get("proof"));
            }
            case "failed" -> {
                record.state = State.FAILED;
                record.proof = asMap(event.get("proof"));
                record.errorClass = (String) event.get("error_class");
                record.errorMessage = (String) event.get("message");
            }
            case "unknown" -> {
                record.state = State.UNKNOWN;
                record.errorClass = (String) event.get("error_class");
                record.errorMessage = (String) event.get("message");
            }
            default -> { /* recovery notes etc. */ }
        }
    }

    private void append(Map<String, Object> event) {
        try {
            byte[] line = (MiniJson.write(event) + "\n").getBytes(StandardCharsets.UTF_8);
            channel.write(java.nio.ByteBuffer.wrap(line), channel.size());
            channel.force(false); // acknowledged == on disk
        } catch (IOException error) {
            throw new IllegalStateException("operation journal append failed; "
                + "refusing to acknowledge any outcome", error);
        }
    }

    private void close() throws IOException {
        channel.close();
    }

    static boolean canTransition(State from, State to) {
        if (from == to) {
            return to == State.SUCCEEDED || to == State.FAILED; // idempotent re-proof
        }
        return switch (from) {
            case ACCEPTED -> to == State.QUEUED || to == State.RUNNING
                || to == State.FAILED || to == State.UNKNOWN;
            case QUEUED -> to == State.RUNNING || to == State.FAILED || to == State.UNKNOWN;
            case RUNNING -> to == State.SUCCEEDED || to == State.FAILED || to == State.UNKNOWN;
            case UNKNOWN -> to == State.SUCCEEDED || to == State.FAILED;
            case SUCCEEDED, FAILED -> false;
        };
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> asMap(Object value) {
        return value instanceof Map ? (Map<String, Object>) value : null;
    }

    // -- canonical parameter fingerprint -------------------------------------------

    /**
     * Canonical SHA-256 of the request params: keys sorted recursively,
     * integral numbers normalized. The same key with a different fingerprint
     * is a conflict, never a replay.
     */
    public static String paramsHash(Map<String, Object> params) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            byte[] bytes = MiniJson.write(canonical(params)).getBytes(StandardCharsets.UTF_8);
            StringBuilder hex = new StringBuilder();
            for (byte b : digest.digest(bytes)) {
                hex.append(String.format("%02x", b));
            }
            return "sha256:" + hex;
        } catch (NoSuchAlgorithmException impossible) {
            throw new IllegalStateException("SHA-256 missing", impossible);
        }
    }

    private static Map<String, Object> canonical(Map<String, Object> params) {
        Map<String, Object> sorted = new TreeMap<>();
        for (Map.Entry<String, Object> entry : params.entrySet()) {
            sorted.put(entry.getKey(), canonicalValue(entry.getValue()));
        }
        return sorted;
    }

    private static Object canonicalValue(Object value) {
        if (value instanceof Map<?, ?> map) {
            @SuppressWarnings("unchecked")
            Map<String, Object> cast = (Map<String, Object>) map;
            return canonical(cast);
        }
        if (value instanceof List<?> list) {
            List<Object> out = new ArrayList<>();
            for (Object item : list) {
                out.add(canonicalValue(item));
            }
            return out;
        }
        if (value instanceof Number number) {
            double raw = number.doubleValue();
            if (raw == Math.rint(raw) && !Double.isInfinite(raw)
                && Math.abs(raw) <= 9_007_199_254_740_992L) {
                return number.longValue();
            }
            return raw;
        }
        return value;
    }
}
