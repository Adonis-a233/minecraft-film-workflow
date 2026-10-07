package dev.mcfilm.cinematicbridge.world;

import dev.mcfilm.cinematicbridge.server.ClientThreadExecutor;
import dev.mcfilm.cinematicbridge.server.OperationJournal;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Typed world operations facade (plan v2 §Phase C): journal → bounded
 * dispatch → SAME-TASK proof read → truthful outcome. A write is `applied`
 * only when the proof read agrees; a lost dispatch acknowledgement is
 * `unknown` (the task may still land later), never `applied` — failure F5
 * is closed by construction here.
 *
 * Proof protocol (all reads happen on the client thread inside the SAME
 * dispatched task, so no tick can pass between write and proof):
 * - set_time: timeOfDay equals the requested value;
 * - set_weather: raining/thundering match;
 * - set_block_keep: before/after block reads (keep may legitimately no-op
 *   on an occupied target — the reads are recorded either way);
 * - fill_keep: matching-block count before/after;
 * - summon: entity count of that type before/after (must grow by one).
 * Invalid resource ids are caught BEFORE dispatch via WorldAccess.exists
 * checks, so a silently-ignored command can never masquerade as a no-op.
 */
public final class WorldOperations {

    public record Outcome(String status, String errorClass, String message, Map<String, Object> result) {
        public static Outcome applied(Map<String, Object> result) {
            return new Outcome("applied", null, null, result);
        }

        public static Outcome failed(String errorClass, String message, Map<String, Object> result) {
            return new Outcome("failed", errorClass, message, result);
        }

        public static Outcome rejected(String errorClass, String message) {
            return new Outcome("rejected", errorClass, message, new LinkedHashMap<>());
        }

        public static Outcome unknown(String message) {
            return new Outcome("unknown", "operation_timeout_unknown", message, new LinkedHashMap<>());
        }
    }

    private final WorldAccess world;
    private final ClientThreadExecutor executor;
    private final OperationJournal journal;
    private final long dispatchTimeoutMillis;

    public WorldOperations(WorldAccess world, ClientThreadExecutor executor,
                           OperationJournal journal, long dispatchTimeoutMillis) {
        this.world = world;
        this.executor = executor;
        this.journal = journal;
        this.dispatchTimeoutMillis = dispatchTimeoutMillis;
    }

    public Outcome execute(String method, Map<String, Object> params, String idempotencyKey) {
        WorldOp op;
        try {
            op = WorldOpParser.parse(method, params);
        } catch (IllegalArgumentException error) {
            return Outcome.rejected("validation_failed", String.valueOf(error.getMessage()));
        }
        OperationJournal.Record record = journal.stateOf(idempotencyKey).isPresent()
            ? journal.get(idempotencyKey).orElseThrow()
            : journal.open(idempotencyKey, method);
        if (record == null) {
            return Outcome.rejected("operation_rejected",
                "operation journal is full of unproven outcomes; resolve them before new writes");
        }
        if (record.state() != OperationJournal.State.ACCEPTED) {
            // Same key re-submitted: return the recorded outcome, never re-execute.
            return switch (record.state()) {
                case OBSERVED -> record.proofOk() == Boolean.FALSE
                    ? Outcome.failed("operation_failed",
                        "previous attempt under this key failed; see the journaled proof",
                        record.proof() == null ? new LinkedHashMap<>() : record.proof())
                    : Outcome.applied(replayProof(idempotencyKey, op));
                case REJECTED, QUEUED, DISPATCHED, ACCEPTED ->
                    Outcome.rejected("operation_rejected",
                        "idempotency key already journaled in state " + record.state().json());
                case UNKNOWN -> Outcome.unknown(
                    "previous attempt with this key is unproven; resolve it via "
                    + "bridge.get_operation_status before retrying");
            };
        }
        journal.markQueued(idempotencyKey);
        journal.markDispatched(idempotencyKey);
        ClientThreadExecutor.Dispatch dispatch;
        try {
            dispatch = executor.dispatch(dispatchTimeoutMillis,
                () -> executeOnGameThread(op));
        } catch (RuntimeException error) {
            // The runner itself refused (e.g. no integrated server): a proven
            // failure — the task never started, so nothing is unknown here.
            journal.markObservedFailed(idempotencyKey, error.getMessage());
            return Outcome.failed("environment_mismatch", String.valueOf(error.getMessage()),
                new LinkedHashMap<>());
        }
        if (!dispatch.proven() && dispatch.outcome() == ClientThreadExecutor.Outcome.UNPROVEN) {
            journal.markUnknown(idempotencyKey);
            return Outcome.unknown(dispatch.detail());
        }
        if (dispatch.outcome() == ClientThreadExecutor.Outcome.FAILED) {
            journal.markObservedFailed(idempotencyKey, dispatch.detail()); // proven failure: outcome is known
            return Outcome.failed("operation_rejected", dispatch.detail(), new LinkedHashMap<>());
        }
        // PROVEN: dispatch.output() is the proof map serialized on the game thread.
        Map<String, Object> proof;
        try {
            Object parsed = dev.mcfilm.cinematicbridge.json.MiniJson.parse(dispatch.output());
            @SuppressWarnings("unchecked")
            Map<String, Object> proofMap = (Map<String, Object>) parsed;
            proof = proofMap;
        } catch (RuntimeException error) {
            journal.markUnknown(idempotencyKey);
            return Outcome.unknown("dispatch proof was unreadable: " + error);
        }
        if (Boolean.TRUE.equals(proof.get("ok"))) {
            journal.markObserved(idempotencyKey, proof);
            return Outcome.applied(proof);
        }
        // Proven post-condition mismatch stays OBSERVED but is never a success:
        // the journaled proof decides what a later status query reports.
        journal.markObserved(idempotencyKey, proof);
        return Outcome.failed("operation_failed",
            "post-write proof did not match: " + proof.get("reason"), proof);
    }

    /** Runs on the game thread: command + proof read with no tick in between. */
    private String executeOnGameThread(WorldOp op) {
        Map<String, Object> proof = prove(op);
        return dev.mcfilm.cinematicbridge.json.MiniJson.write(proof);
    }

    /**
     * Proof execution for async dispatch (contract v3): the caller runs this
     * on the authoritative game thread and serializes the returned map. It
     * performs the write AND the same-task verification read.
     */
    public Map<String, Object> prove(WorldOp op) {
        Map<String, Object> proof = new LinkedHashMap<>();
        proof.put("command", WorldCommandBuilder.command(op));
        if (op instanceof WorldOp.SetTime setTime) {
            world.runCommand("time set " + setTime.value());
            long observed = world.timeOfDay();
            proof.put("expected_time_of_day", setTime.value());
            proof.put("time_of_day", observed);
            proof.put("ok", observed == setTime.value());
            if (observed != setTime.value()) {
                proof.put("reason", "time_of_day mismatch after time set");
            }
            return proof;
        }
        if (op instanceof WorldOp.SetWeather weather) {
            world.runCommand(WorldCommandBuilder.command(weather));
            boolean raining = !weather.weather().equals("clear");
            boolean thundering = weather.weather().equals("thunder");
            proof.put("expected_raining", raining);
            proof.put("expected_thundering", thundering);
            proof.put("raining", world.raining());
            proof.put("thundering", world.thundering());
            boolean ok = world.raining() == raining
                && world.thundering() == thundering;
            proof.put("ok", ok);
            if (!ok) {
                proof.put("reason", "weather state mismatch after weather set");
            }
            return proof;
        }
        if (op instanceof WorldOp.SetBlockKeep setBlock) {
            String expected=world.canonicalBlockState(setBlock.block());
            if (expected==null) {
                proof.put("ok", false);
                proof.put("reason", "unknown block id: " + setBlock.block());
                return proof;
            }
            String before = world.blockAt(setBlock.x(), setBlock.y(), setBlock.z());
            if (setBlock.preserveState()) world.setBlockKeepExact(setBlock.x(),setBlock.y(),setBlock.z(),setBlock.block());
            else world.runCommand(WorldCommandBuilder.command(setBlock));
            String after = world.blockAt(setBlock.x(), setBlock.y(), setBlock.z());
            String afterState=world.blockStateAt(setBlock.x(),setBlock.y(),setBlock.z());
            proof.put("before", before);
            proof.put("preserve_state", setBlock.preserveState());
            proof.put("after", after);
            proof.put("changed", !after.equals(before));
            proof.put("after_state",afterState);
            proof.put("expected_state",expected);
            proof.put("ok", expected.equals(afterState));
            if (!expected.equals(afterState)) {
                proof.put("reason", "target still holds " + after + " after keep write");
            }
            return proof;
        }
        if (op instanceof WorldOp.FillKeep fill) {
            if (fill.block().equals("minecraft:air")) {
                proof.put("ok", false);
                proof.put("reason", "fill_keep refuses air as the fill block (it would be a silent no-op)");
                return proof;
            }
            if (!world.blockExists(fill.block())) {
                proof.put("ok", false);
                proof.put("reason", "unknown block id: " + fill.block());
                return proof;
            }
            long before = world.countBlocks(fill.block(), fill.start(), fill.end());
            long airBefore = world.countAir(fill.start(), fill.end());
            if (fill.preserveState()) world.fillKeepExact(fill.start(),fill.end(),fill.block());
            else world.runCommand(WorldCommandBuilder.command(fill));
            long after = world.countBlocks(fill.block(), fill.start(), fill.end());
            long changed = after - before;
            proof.put("matching_before", before);
            proof.put("matching_after", after);
            proof.put("air_before", airBefore);
            proof.put("changed", changed);
            // keep-fill replaces exactly the air positions; the expected change
            // set is therefore exact: changed == air_before. Weak "grew and
            // non-zero" proofs let partial fills pass (v3 §4).
            boolean ok = changed == airBefore && after == before + airBefore;
            proof.put("ok", ok);
            if (!ok) {
                proof.put("reason", "fill changed " + changed + " blocks but keep-fill "
                    + "must place exactly the " + airBefore + " air positions");
            }
            return proof;
        }
        if (op instanceof WorldOp.Summon summon) {
            if (!world.entityPositionReady(summon.x(), summon.y(), summon.z())) {
                proof.put("ok", false);
                proof.put("reason", "actor position is not in an entity-ticking chunk; no summon executed");
                proof.put("write_executed", false);
                return proof;
            }
            if (!world.entityTypeExists(summon.entity())) {
                proof.put("ok", false);
                proof.put("reason", "unknown entity id: " + summon.entity());
                return proof;
            }
            if (summon.tag() != null) {
                return proveSummonWithTag(summon, proof);
            }
            List<String> beforeIds = safeEntityIds(summon);
            long before = beforeIds != null ? beforeIds.size()
                : world.countEntities(summon.entity(), summon.x(), summon.y(), summon.z(), 4);
            world.runCommand(WorldCommandBuilder.command(summon));
            if (beforeIds != null) {
                List<String> afterIds = world.entityIds(summon.entity(), summon.x(), summon.y(),
                    summon.z(), 4);
                List<String> added = new java.util.ArrayList<>(afterIds);
                added.removeAll(beforeIds);
                proof.put("entities_before", beforeIds.size());
                proof.put("entities_after", afterIds.size());
                proof.put("spawned_entity_uuid", added.size() == 1 ? added.get(0) : null);
                boolean ok = afterIds.size() == beforeIds.size() + 1 && added.size() == 1;
                proof.put("ok", ok);
                if (!ok) {
                    proof.put("reason", "entity identity did not grow by exactly one");
                }
                return proof;
            }
            long after = world.countEntities(summon.entity(), summon.x(), summon.y(), summon.z(), 4);
            proof.put("entities_before", before);
            proof.put("entities_after", after);
            proof.put("ok", after == before + 1);
            if (after != before + 1) {
                proof.put("reason", "entity count did not grow by exactly one");
            }
            return proof;
        }
        proof.put("ok", false);
        proof.put("reason", "unhandled op " + op.getClass().getSimpleName());
        return proof;
    }

    /**
     * Tag-identified summon (v3 §4): the tag IS the actor's identity, so an
     * entity that already carries it is this operation's target — replay
     * succeeds WITHOUT summoning again, and no nearby-count heuristic is
     * ever consulted.
     */
    private Map<String, Object> proveSummonWithTag(WorldOp.Summon summon, Map<String, Object> proof) {
        String existing = world.firstEntityWithTag(summon.tag());
        if (existing != null) {
            proof.put("replayed", true);
            proof.put("entity_uuid", existing);
            proof.put("entity_tag", summon.tag());
            proof.put("command", null);
            proof.put("ok", true);
            return proof;
        }
        proof.put("command", WorldCommandBuilder.command(summon));
        world.runCommand(WorldCommandBuilder.command(summon));
        String uuid = world.firstEntityWithTag(summon.tag());
        proof.put("entity_tag", summon.tag());
        proof.put("entity_uuid", uuid);
        boolean ok = uuid != null;
        proof.put("ok", ok);
        if (!ok) {
            proof.put("reason", "no entity carries the ownership tag after summon");
        }
        return proof;
    }

    /** Entity identity reads when the world supports them; null otherwise. */
    private List<String> safeEntityIds(WorldOp.Summon summon) {
        try {
            return world.entityIds(summon.entity(), summon.x(), summon.y(), summon.z(), 4);
        } catch (UnsupportedOperationException unsupported) {
            return null;
        }
    }

    /** The recorded proof of an already-observed write (idempotent replay). */
    private Map<String, Object> replayProof(String idempotencyKey, WorldOp op) {
        Map<String, Object> map = new LinkedHashMap<>();
        map.put("idempotent_replay", true);
        map.put("journal_key", idempotencyKey);
        map.put("command", WorldCommandBuilder.command(op));
        return map;
    }

    // -- typed reads ------------------------------------------------------------

    public Outcome read(String method, Map<String, Object> params) {
        try {
            ClientThreadExecutor.Dispatch dispatch = executor.dispatch(dispatchTimeoutMillis, () -> {
                Map<String, Object> result = new LinkedHashMap<>();
                switch (method) {
                    case "world.get_block" -> {
                        int[] position = WorldOpParser.requirePoint(params);
                        result.put("block", world.blockAt(position[0], position[1], position[2]));
                        result.put("block_state",world.blockStateAt(position[0],position[1],position[2]));
                        if (params.containsKey("validate_block")) {
                            String state=WorldOpParser.requireBlockState(params,"validate_block");
                            String canonical=world.canonicalBlockState(state);
                            result.put("block_state_valid",canonical!=null);
                            if (canonical!=null) result.put("canonical_state",canonical);
                        }
                    }
                    case "world.get_time" -> result.put("time_of_day", world.timeOfDay());
                    case "world.get_weather" -> {
                        result.put("raining", world.raining());
                        result.put("thundering", world.thundering());
                        result.put("rain_gradient", world.rainGradient());
                        result.put("thunder_gradient", world.thunderGradient());
                    }
                    case "world.count_entities" -> {
                        String entity = WorldOpParser.requireResource(params, "entity");
                        int[] position = WorldOpParser.requirePoint(params);
                        int radius = (int) WorldOpParser.requireLong(params, "radius");
                        result.put("count", world.countEntities(entity, position[0], position[1],
                            position[2], radius));
                    }
                    default -> throw new IllegalArgumentException("unknown world read: " + method);
                }
                return dev.mcfilm.cinematicbridge.json.MiniJson.write(result);
            });
            if (dispatch.outcome() == ClientThreadExecutor.Outcome.UNPROVEN) {
                return Outcome.unknown("world read could not be dispatched: " + dispatch.detail());
            }
            if (dispatch.outcome() == ClientThreadExecutor.Outcome.FAILED) {
                return Outcome.failed("operation_rejected", dispatch.detail(), new LinkedHashMap<>());
            }
            Object parsed = dev.mcfilm.cinematicbridge.json.MiniJson.parse(dispatch.output());
            @SuppressWarnings("unchecked")
            Map<String, Object> result = (Map<String, Object>) parsed;
            return Outcome.applied(result);
        } catch (IllegalArgumentException error) {
            return Outcome.rejected("validation_failed", String.valueOf(error.getMessage()));
        }
    }
}
