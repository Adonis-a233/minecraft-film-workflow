package dev.mcfilm.cinematicbridge.server;

import dev.mcfilm.cinematicbridge.core.CameraTrackConverter;
import dev.mcfilm.cinematicbridge.core.TickScheduler;
import dev.mcfilm.cinematicbridge.core.TimelineEvent;
import dev.mcfilm.cinematicbridge.core.TimelineModel;
import dev.mcfilm.cinematicbridge.core.VersionGate;
import dev.mcfilm.cinematicbridge.flash.FlashbackPort;
import dev.mcfilm.cinematicbridge.mocap.MocapPoller;
import dev.mcfilm.cinematicbridge.mocap.MocapStateMachine;
import dev.mcfilm.cinematicbridge.state.MocapStateV2;
import dev.mcfilm.cinematicbridge.world.WorldOperations;
import dev.mcfilm.cinematicbridge.world.WorldOpParser;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.function.Supplier;

/**
 * Method routing for the bridge protocol (plan §9.2; v2 in plan v2 §Phase B–D).
 *
 * Contract 1 stays frozen (legacy diagnostics; writes there are legacy
 * simulation behavior). Contract 2 is truthful by construction: every write
 * is journaled under its idempotency key, dispatched with a bounded client
 * thread acknowledgement, and reported `applied` only after a proof read.
 * Unproven writes are `unknown`; the controller resolves them via
 * bridge.get_operation_status or a state read — never by resending.
 *
 * Game interaction is injected: {@link CommandSink} (slash commands),
 * {@link WorldOperations} (typed writes + proof reads + journal),
 * {@link MocapStateMachine} (feedback-classified recorder state),
 * {@link FlashbackPort} (fail-closed).
 */
public final class BridgeDispatcher {

    /** Runs a slash command (no leading slash) on the Minecraft main thread. */
    @FunctionalInterface
    public interface CommandSink {
        String run(String command);
    }

    /** Client-side world facts the bridge reports but cannot compute itself. */
    public interface GameStateProvider {
        Map<String, Object> snapshot();

        default Map<String, Object> resourcePacks() {
            return Map.of("enabled_profile_ids", List.of());
        }
    }

    private final CommandSink commands;
    private final FlashbackPort flashback;
    private final GameStateProvider gameState;
    private final VersionGate.RuntimeVersions versions;

    // v2 collaborators (null → pure v1 behavior)
    private final OperationJournal journal;
    private final WorldOperations worldOps;
    private final MocapStateMachine mocap;
    private final MocapPoller mocapPoller;

    // v3 collaborators (null → v2 behavior)
    private final PersistentJournal persistentJournal;
    private final AsyncOperationService asyncOps;
    private final dev.mcfilm.cinematicbridge.replay.ReplayPort replayPort;
    private volatile dev.mcfilm.cinematicbridge.actor.ActorService actorService;

    // Timeline state is guarded by timelineLock (never held across a game-thread
    // wait) and published through volatile reads — END_CLIENT_TICK must never
    // block on the HTTP path (the v2 deadlock: handle() held the monitor while
    // waiting for the client thread, and the tick callback needed the same
    // monitor, freezing every tick until the dispatch timeout).
    private final Object timelineLock = new Object();
    private volatile TickScheduler scheduler;
    private volatile String activeTimelineId;
    private volatile List<Map<String,Object>> replayEventTimes=List.of();
    private volatile List<String> timelineFeedback=List.of();
    private volatile String timelineFeedbackFailure;
    private final Map<String, Map<String, Object>> resolved = new java.util.concurrent.ConcurrentHashMap<>();

    /** Legacy constructor: contract-1 behavior only (simulation, tests). */
    public BridgeDispatcher(CommandSink commands, FlashbackPort flashback,
                            GameStateProvider gameState, VersionGate.RuntimeVersions versions) {
        this(commands, flashback, gameState, versions, null, null, null, null, 1, 0);
    }

    /**
     * Contract-2 constructor. mocapPollSleepMillis == 0 keeps polling
     * synchronous (pure tests); live wiring passes a real sleep.
     */
    public BridgeDispatcher(CommandSink commands, FlashbackPort flashback,
                            GameStateProvider gameState, VersionGate.RuntimeVersions versions,
                            OperationJournal journal, WorldOperations worldOps,
                            MocapStateMachine mocap,
                            Supplier<MocapStateV2.Phase> mocapPhase,
                            int mocapPollAttempts, long mocapPollSleepMillis) {
        this(commands, flashback, gameState, versions, journal, worldOps, mocap, mocapPhase,
            mocapPollAttempts, mocapPollSleepMillis, null, null);
    }

    /**
     * Contract-3 constructor: adds the persistent journal and the async write
     * pipeline. Null collaborators fall back to v2 behavior per surface.
     */
    public BridgeDispatcher(CommandSink commands, FlashbackPort flashback,
                            GameStateProvider gameState, VersionGate.RuntimeVersions versions,
                            OperationJournal journal, WorldOperations worldOps,
                            MocapStateMachine mocap,
                            Supplier<MocapStateV2.Phase> mocapPhase,
                            int mocapPollAttempts, long mocapPollSleepMillis,
                            PersistentJournal persistentJournal, AsyncOperationService asyncOps) {
        this(commands, flashback, gameState, versions, journal, worldOps, mocap, mocapPhase,
            mocapPollAttempts, mocapPollSleepMillis, persistentJournal, asyncOps, null);
    }

    /**
     * Full contract-3 constructor with the replay-master port (workflow v3
     * §7-P1). A null port installs the fail-closed disabled port.
     */
    public BridgeDispatcher(CommandSink commands, FlashbackPort flashback,
                            GameStateProvider gameState, VersionGate.RuntimeVersions versions,
                            OperationJournal journal, WorldOperations worldOps,
                            MocapStateMachine mocap,
                            Supplier<MocapStateV2.Phase> mocapPhase,
                            int mocapPollAttempts, long mocapPollSleepMillis,
                            PersistentJournal persistentJournal, AsyncOperationService asyncOps,
                            dev.mcfilm.cinematicbridge.replay.ReplayPort replayPort) {
        this.commands = commands;
        this.flashback = flashback;
        this.gameState = gameState;
        this.versions = versions;
        this.journal = journal;
        this.worldOps = worldOps;
        this.mocap = mocap;
        this.persistentJournal = persistentJournal;
        this.asyncOps = asyncOps;
        this.replayPort = replayPort != null ? replayPort : new dev.mcfilm.cinematicbridge.replay.ReplayDisabledPort();
        this.mocapPoller = mocapPhase == null ? null
            : mocapPollSleepMillis == 0
                ? new MocapPoller(mocapPhase, () -> true)
                : MocapPoller.live(mocapPhase, mocapPollSleepMillis);
        this.mocapPollAttempts = Math.max(1, mocapPollAttempts);
    }

    /** Enables the optional, typed actor surface after the loopback server is constructed. */
    public void setActorService(dev.mcfilm.cinematicbridge.actor.ActorService service) {
        this.actorService = service;
    }

    private final int mocapPollAttempts;

    /** Legacy entry (contract 1). */
    public Map<String, Object> handle(String method, Map<String, Object> params) {
        return handle(method, params, 1, null);
    }

    public Map<String, Object> handle(String method, Map<String, Object> params,
                                      int contractVersion, String idempotencyKey) {
        if (contractVersion == 1) {
            return handleV1(method, params);
        }
        if (contractVersion >= 3) {
            return handleV3(method, params, idempotencyKey);
        }
        return handleV2(method, params, idempotencyKey);
    }

    // -- contract 1 routing (frozen) ------------------------------------------

    private Map<String, Object> handleV1(String method, Map<String, Object> params) {
        return switch (method) {
            case "bridge.health" -> Map.of("status", "applied", "result", Map.of("healthy", true));
            case "bridge.capabilities" -> Map.of("status", "applied", "result", Map.of(
                "flashback_automation", flashback.enabled(),
                "flashback_disabled_reason", flashback.enabled() ? "" : flashback.disabledReason(),
                "mocap_commands", true,
                "tick_scheduler", true));
            case "bridge.get_runtime_versions" -> versionsResult(1);
            case "bridge.get_game_state" -> Map.of("status", "applied", "result", gameState.snapshot());
            case "bridge.get_resourcepacks" -> Map.of("status", "applied", "result", gameState.resourcePacks());
            case "bridge.submit_timeline" -> submitTimeline(params, null);
            case "bridge.get_timeline_status" -> timelineStatus();
            case "bridge.cancel_timeline" -> cancelTimeline();
            case "mocap.start_recording" -> command("mocap recording start", params);
            case "mocap.stop_recording" -> command("mocap recording stop", params);
            case "mocap.save_recording" -> command("mocap recording save " + text(params, "name"), params);
            case "mocap.start_scene" -> command("mocap playing start ." + text(params, "scene"), params);
            case "mocap.stop_scene" -> command("mocap playing stopScene ." + text(params, "scene"), params);
            case "mocap.get_status" -> Map.of("status", "applied", "result", gameState.snapshot());
            case "flashback.start_recording" -> flashback.startRecording(text(params, "timeline_id"));
            case "flashback.stop_recording" -> flashback.stopRecording(text(params, "timeline_id"));
            case "flashback.await_replay_saved" -> flashback.awaitReplaySaved(text(params, "timeline_id"));
            case "flashback.open_replay" -> flashback.openReplay(text(params, "timeline_id"));
            case "flashback.replace_camera_track" -> replaceCameraTrack(params);
            case "flashback.start_export" -> startExport(params);
            case "flashback.get_export_status" -> flashback.exportStatus();
            case "flashback.cancel_export" -> flashback.cancelExport();
            default -> reject("validation_failed",
                "unknown method under contract 1: " + method
                + " (v2 methods require schema_version 2)");
        };
    }

    // -- contract 2 routing ----------------------------------------------------

    private Map<String, Object> handleV2(String method, Map<String, Object> params, String key) {
        return switch (method) {
            case "bridge.health" -> Map.of("status", "applied", "result", Map.of("healthy", true));
            case "bridge.capabilities" -> Map.of("status", "applied", "result", capabilityPayload());
            case "bridge.get_runtime_versions" -> versionsResult(2);
            case "bridge.get_game_state" -> Map.of("status", "applied", "result", gameState.snapshot());
            case "bridge.get_resourcepacks" -> Map.of("status", "applied", "result", gameState.resourcePacks());
            case "bridge.get_operation_status" -> operationStatus(params, key);
            case "bridge.submit_timeline" -> submitTimeline(params, key);
            case "bridge.get_timeline_status" -> timelineStatus();
            case "bridge.cancel_timeline" -> cancelTimeline();
            case "world.set_time", "world.set_weather", "world.set_block_keep",
                 "world.fill_keep", "world.summon" -> worldWrite(method, params, key);
            case "world.get_block", "world.get_time", "world.get_weather",
                 "world.count_entities" -> worldRead(method, params);
            case "mocap.prepare_recording" -> mocapTransition("prepare", null, key);
            case "mocap.confirm_recording_start" -> mocapTransition("confirm", null, key);
            case "mocap.stop_recording" -> mocapTransition("stop", null, key);
            case "mocap.save_recording" -> mocapTransition("save", text(params, "name"), key);
            case "mocap.discard_recording" -> mocapTransition("discard", null, key);
            case "mocap.get_status" -> Map.of("status", "applied", "result", mocap.status().toMap());
            case "flashback.start_recording" -> flashback.startRecording(text(params, "timeline_id"));
            case "flashback.stop_recording" -> flashback.stopRecording(text(params, "timeline_id"));
            case "flashback.await_replay_saved" -> flashback.awaitReplaySaved(text(params, "timeline_id"));
            case "flashback.open_replay" -> flashback.openReplay(text(params, "timeline_id"));
            case "flashback.replace_camera_track" -> replaceCameraTrack(params);
            case "flashback.start_export" -> startExport(params);
            case "flashback.get_export_status" -> flashback.exportStatus();
            case "flashback.cancel_export" -> flashback.cancelExport();
            default -> reject("validation_failed",
                "unknown method under contract 2: " + method
                + " (the one-shot mocap.start_recording was removed; use the two-step state machine)");
        };
    }

    // -- contract 3 routing (async writes, persistent journal) -------------------

    /**
     * Contract 3 = contract 2 EXCEPT: (a) world writes are accepted onto the
     * persistent async pipeline and never hold the caller; (b)
     * bridge.get_operation_status answers from the persistent journal first.
     * Reads, mocap transitions (client-feedback based), flashback and the
     * timeline keep their v2 semantics.
     */
    private Map<String, Object> handleV3(String method, Map<String, Object> params, String key) {
        if (method.startsWith("replay.") && !method.equals("replay.get_render_status")
            && !method.equals("replay.get_master_status") && !method.equals("replay.await_master_saved")) {
            return replayMutation(method, params, key);
        }
        return routeV3(method, params, key);
    }

    private Map<String,Object> replayMutation(String method, Map<String,Object> params, String key) {
        if (persistentJournal == null || key == null || key.isBlank())
            return reject("validation_failed", "replay writes require persistent journal and key");
        String hash = PersistentJournal.paramsHash(params);
        synchronized (persistentJournal) {
            var old = persistentJournal.get(key).orElse(null);
            if (old != null) {
                if (!old.method.equals(method) || !old.paramsHash.equals(hash))
                    return reject("operation_conflict", "key belongs to another request");
                if (old.proof() != null) return old.proof();
                return Map.of("status", "unknown", "error_class", "operation_timeout_unknown",
                    "message", "replay request is running or recovered; query job before continuing");
            }
            persistentJournal.begin(key, method, hash);
            persistentJournal.markRunning(key);
        }
        try {
            Map<String,Object> answer = routeV3(method, params, key);
            String status = String.valueOf(answer.get("status"));
            if (status.equals("applied")) persistentJournal.markSucceeded(key, answer);
            else if (status.equals("unknown") || status.equals("pending")) persistentJournal.markUnknown(key, "submission outcome unresolved");
            else persistentJournal.markFailed(key, String.valueOf(answer.getOrDefault("error_class", "operation_failed")),
                String.valueOf(answer.getOrDefault("message", "replay failed")), answer);
            return answer;
        } catch (RuntimeException failed) {
            Map<String,Object> answer = reject("operation_failed", failed.toString());
            persistentJournal.markFailed(key, "operation_failed", failed.toString(), answer);
            return answer;
        }
    }

    private Map<String, Object> routeV3(String method, Map<String, Object> params, String key) {
        if ((method.equals("replay.open_master") || method.equals("replay.replace_camera_track") || method.equals("replay.start_render"))
            && replayPort.enabled() && (!params.containsKey("master_hash")
                || !replayPort.matchesHash(text(params, "timeline_id"), text(params, "master_hash"))))
            return reject("validation_failed", "master hash mismatch");
        return switch (method) {
            case "bridge.capabilities" -> Map.of("status", "applied", "result", capabilityPayloadV3());
            case "bridge.get_runtime_versions" -> versionsResult(3);
            case "world.set_time", "world.set_weather", "world.set_block_keep",
                 "world.fill_keep", "world.summon" -> worldWriteV3(method, params, key);
            case "bridge.get_operation_status" -> v3OperationStatus(params, key);
            case "actor.start_take" -> actorService == null
                ? reject("validation_failed", "actor driver is unavailable")
                : actorService.start(params, key, key, text(params, "run_id"));
            case "actor.get_take_status" -> actorService == null
                ? reject("validation_failed", "actor driver is unavailable")
                : actorService.status(text(params, "take_id"));
            case "actor.get_state" -> actorService == null
                ? reject("validation_failed", "actor driver is unavailable") : actorService.inspect();
            case "actor.cancel_take" -> actorService == null
                ? reject("validation_failed", "actor driver is unavailable")
                : actorService.cancel(text(params, "take_id"), key);
            case "actor.release_owned" -> actorService == null
                ? reject("validation_failed", "actor driver is unavailable")
                : actorService.releaseOwned(text(params, "actor_id"));
            case "mocap.prepare_actor_recording" -> actorService == null
                ? reject("validation_failed", "actor driver is unavailable")
                : prepareActorRecording(params, key);
            case "mocap.prepare_offline_players" -> actorService==null ? reject("validation_failed","actor driver unavailable")
                : actorService.prepareOfflinePlayers((List<?>)params.get("player_names"));
            case "replay.start_recording" -> {
                String master=text(params,"timeline_id");
                Map<String,Object> started=replayPort.startRecording(master);
                if(actorService!=null && "applied".equals(started.get("status")))actorService.bindReplayClock(()->replayPort.recordingTimestamp(master));
                yield started;
            }
            case "replay.stop_recording" -> replayPort.stopRecording(text(params, "timeline_id"));
            case "replay.await_master_saved" -> replayPort.awaitMasterSaved(text(params, "timeline_id"));
            case "replay.open_master" -> replayPort.openMaster(text(params, "timeline_id"));
            case "replay.replace_camera_track" -> replayPort.replaceCameraTrack(
                text(params, "timeline_id"), rawKeyframes(params),
                (String) params.getOrDefault("interpolation", "smooth"));
            case "replay.start_render" -> replayStartRender(params);
            case "replay.get_render_status" -> replayPort.renderStatus();
            case "replay.get_master_status" -> replayPort.masterStatus();
            case "replay.cancel_render" -> replayPort.cancelRender();
            default -> legacyResultV3(method, params, key);
        };
    }

    private Map<String,Object> legacyResultV3(String method, Map<String,Object> params, String key) {
        Map<String,Object> result = new LinkedHashMap<>(handleV2(method, params, key));
        // Legacy observed/rejected/dispatched are not persistent v3 states.
        // Reads and legacy transitions carry their evidence in result only.
        result.remove("journal_state");
        return result;
    }

    private Map<String,Object> prepareActorRecording(Map<String,Object> params, String key) {
        Map<String,Object> result = new LinkedHashMap<>(mocapTransition("prepare",
            actorService.recordingPlayer(text(params, "actor_id")), key));
        result.remove("journal_state");
        return result;
    }

    /**
     * Contract-3 capability payload (contracts/v3/capabilities.schema.json):
     * the v2 shape plus backend-neutral photography names. A disabled replay
     * port advertises "none" — the controller then fails those stages closed
     * instead of guessing.
     */
    private Map<String, Object> capabilityPayloadV3() {
        Map<String, Object> result = new LinkedHashMap<>(capabilityPayload());
        result.put("contract", 3);
        result.put("recorder_backend", mocap != null ? "mocap" : "none");
        String replayBackend = replayPort.enabled() ? replayPort.backendName() : "none";
        result.put("replay_backend", replayBackend);
        result.put("camera_backend", replayBackend);
        result.put("render_backend",
            replayPort.enabled() && "replaymod".equals(replayPort.backendName())
                ? "replaymod" : "none");
        result.put("async_world_writes", asyncOps != null);
        result.put("persistent_journal", persistentJournal != null);
        result.put("actor_backend", actorService != null ? "carpet" : "none");
        return result;
    }

    /** The compiler's raw keyframe list, passed through untouched (each port
     * maps it onto its own camera representation). */
    @SuppressWarnings("unchecked")
    private static List<Map<String, Object>> rawKeyframes(Map<String, Object> params) {
        Object keyframes = params.get("keyframes");
        if (!(keyframes instanceof List) || ((List<?>) keyframes).isEmpty()) {
            throw new IllegalArgumentException("params.keyframes must be a non-empty list");
        }
        return (List<Map<String, Object>>) keyframes;
    }

    private Map<String, Object> replayStartRender(Map<String, Object> params) {
        @SuppressWarnings("unchecked")
        Map<String, Object> range = (Map<String, Object>) params.get("range");
        if (range == null) {
            return reject("validation_failed", "params.range is required");
        }
        return replayPort.startRender(
            text(params, "timeline_id"),
            (int) asLong(range.get("start_tick"), "start_tick"),
            (int) asLong(range.get("end_tick"), "end_tick"),
            (int) asLong(params.getOrDefault("width", 1280L), "width"),
            (int) asLong(params.getOrDefault("height", 720L), "height"),
            (int) asLong(params.getOrDefault("fps", 30L), "fps"),
            (String) params.getOrDefault("output_path", ""));
    }

    private Map<String, Object> worldWriteV3(String method, Map<String, Object> params, String key) {
        if (asyncOps == null) {
            // v3 requested without the async pipeline wired: fail closed
            // rather than silently degrading to v2 semantics.
            return reject("validation_failed",
                "contract 3 async writes are not available in this bridge mode");
        }
        if (key == null || key.isBlank()) {
            return reject("validation_failed", "idempotency_key is required");
        }
        Map<String, Object> reply = new LinkedHashMap<>(asyncOps.submit(method, params, key));
        if (key != null && !reply.containsKey("idempotency_key")) {
            reply.put("idempotency_key", key);
        }
        return reply;
    }

    /** Persistent journal first, volatile v2 journal second — never a guess. */
    private Map<String, Object> v3OperationStatus(Map<String, Object> params, String fallbackKey) {
        String key = params.get("idempotency_key") instanceof String text && !text.isBlank()
            ? text : fallbackKey;
        if (key == null) {
            return reject("validation_failed", "idempotency_key is required");
        }
        if (persistentJournal != null) {
            var replay = persistentJournal.get(key).orElse(null);
            if (replay != null && replay.method.startsWith("replay.")) {
                String status = switch (replay.state()) {
                    case SUCCEEDED -> "succeeded";
                    case FAILED -> "failed";
                    case UNKNOWN -> "unknown";
                    default -> "pending";
                };
                return Map.of("status", status, "result", replay.toMap());
            }
        }
        if (asyncOps != null && asyncOps.knows(key)) {
            return asyncOps.status(key);
        }
        return operationStatus(params, key);
    }

    private Map<String, Object> versionsResult(int contract) {        Map<String, Object> result = new LinkedHashMap<>();
        result.put("minecraft", versions.minecraft());
        result.put("fabric_loader", versions.fabricLoader());
        result.put("flashback", versions.flashback());
        result.put("mocap", versions.mocap());
        result.put("bridge", versions.bridge());
        result.put("contract", contract);
        return Map.of("status", "applied", "result", result);
    }

    /** The bare capability payload (contract 2); callers wrap the envelope. */
    private Map<String, Object> capabilityPayload() {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("contract", 2);
        result.put("minecraft", versions.minecraft());
        result.put("fabric_loader", versions.fabricLoader());
        result.put("flashback", versions.flashback());
        result.put("mocap", versions.mocap());
        result.put("bridge", versions.bridge());
        result.put("typed_world_ops", worldOps != null);
        result.put("world_reads", worldOps != null);
        result.put("mocap_state_machine", mocap != null);
        result.put("tick_scheduler", true);
        result.put("pause_gated_scheduler", true);
        result.put("flashback_automation", flashback.enabled());
        result.put("flashback_disabled_reason", flashback.enabled() ? "" : flashback.disabledReason());
        Map<String, Object> limits = new LinkedHashMap<>();
        limits.put("max_per_fill", WorldOpParser.MAX_PER_FILL);
        limits.put("max_region_blocks", WorldOpParser.MAX_REGION_BLOCKS);
        result.put("world_write_limits", limits);
        return result;
    }

    /** Journal answer for a key, or unknown when nothing was ever journaled. */
    private Map<String, Object> operationStatus(Map<String, Object> params, String fallbackKey) {
        String key = params.get("idempotency_key") instanceof String text && !text.isBlank()
            ? text : fallbackKey;
        if (key == null) {
            return reject("validation_failed", "idempotency_key is required");
        }
        OperationJournal.Record record = journal.get(key).orElse(null);
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("idempotency_key", key);
        if (record == null) {
            result.put("journal_state", "unknown");
            result.put("message", "no journaled operation under this key; a restart erases volatile proof");
            return Map.of("status", "unknown", "error_class", "operation_timeout_unknown",
                "result", result);
        }
        result.put("method", record.method);
        result.put("journal_state", record.state().json());
        // OBSERVED alone never means success: a journaled proof with ok=false
        // is a FAILED operation (v3 §2: the false-success hole).
        boolean proofFailed = record.state() == OperationJournal.State.OBSERVED
            && record.proofOk() == Boolean.FALSE;
        if (record.proof() != null) {
            result.put("proof", record.proof());
        }
        String status = proofFailed ? "failed"
            : switch (record.state()) {
                case OBSERVED -> "applied";
                case REJECTED -> "rejected";
                default -> "unknown";
            };
        if (status.equals("unknown")) {
            return Map.of("status", "unknown", "error_class", "operation_timeout_unknown",
                "result", result);
        }
        if (status.equals("failed")) {
            return Map.of("status", "failed", "error_class", "operation_failed",
                "message", "journaled proof contradicts the operation goal",
                "result", result);
        }
        return Map.of("status", status, "result", result);
    }

    // -- world writes/reads ------------------------------------------------------

    private Map<String, Object> worldWrite(String method, Map<String, Object> params, String key) {
        if (worldOps == null) {
            return reject("validation_failed", "typed world ops are not available in this bridge mode");
        }
        return fromOutcome(worldOps.execute(method, params, key));
    }

    private Map<String, Object> worldRead(String method, Map<String, Object> params) {
        if (worldOps == null) {
            return reject("validation_failed", "typed world reads are not available in this bridge mode");
        }
        return fromOutcome(worldOps.read(method, params));
    }

    private static Map<String, Object> fromOutcome(WorldOperations.Outcome outcome) {
        Map<String, Object> map = new LinkedHashMap<>();
        map.put("status", outcome.status());
        map.put("journal_state", switch (outcome.status()) {
            case "applied", "failed", "observed" -> "observed";
            case "rejected" -> "rejected";
            case "unknown" -> "unknown";
            default -> "dispatched";
        });
        if (outcome.errorClass() != null) {
            map.put("error_class", outcome.errorClass());
        }
        if (outcome.message() != null) {
            map.put("message", outcome.message());
        }
        map.put("result", outcome.result());
        return map;
    }

    // -- mocap transitions --------------------------------------------------------

    private Map<String, Object> mocapTransition(String action, String name, String key) {
        OperationJournal.Record record = journal.get(key).isPresent()
            ? journal.get(key).orElseThrow()
            : journal.open(key, "mocap." + action);
        if (record == null) {
            return reject("operation_rejected",
                "operation journal is full of unproven outcomes; resolve them before new writes");
        }
        if (record.state() != OperationJournal.State.ACCEPTED) {
            return replayedMocapOutcome(record, action);
        }
        MocapStateMachine.Transition transition;
        try {
            transition = switch (action) {
                case "prepare" -> mocap.prepare(name);
                case "confirm" -> mocap.confirm();
                case "stop" -> mocap.stop();
                case "save" -> mocap.save(name);
                case "discard" -> mocap.discard();
                default -> throw new IllegalStateException("unknown mocap transition " + action);
            };
        } catch (IllegalStateException error) {
            journal.markRejected(key);
            return reject("validation_failed", String.valueOf(error.getMessage()));
        }
        journal.markQueued(key);
        journal.markDispatched(key);
        // Feedback arrives through observe(); the dispatch itself is not proof.
        MocapPoller.Result result = mocapPoller.await(transition.expectedPhase(), mocapPollAttempts, "prepare".equals(action));
        if (result.reached()) {
            journal.markObserved(key);
            Map<String, Object> payload = new LinkedHashMap<>(mocap.status().toMap());
            payload.put("command", transition.command());
            payload.put("expected_phase", transition.expectedPhase().json());
            if ("save".equals(action)) {
                mocap.recordSaved(name);
                payload.put("recording_name", name);
            }
            return Map.of("status", "applied", "journal_state", "observed", "result", payload);
        }
        journal.markUnknown(key);
        String errorClass = result.observedPhase() == MocapStateV2.Phase.UNKNOWN
            ? "mocap_feedback_unknown" : "operation_timeout_unknown";
        return Map.of("status", "unknown",
            "journal_state", "unknown",
            "error_class", errorClass,
            "message", "transition feedback not observed; resolve via get_status before retrying",
            "result", mocap.status().toMap());
    }

    private Map<String, Object> replayedMocapOutcome(OperationJournal.Record record, String action) {
        Map<String, Object> payload = new LinkedHashMap<>(mocap.status().toMap());
        payload.put("replayed", true);
        payload.put("journal_state", record.state().json());
        return switch (record.state()) {
            case OBSERVED -> Map.of("status", "applied", "journal_state", "observed",
                "message", "idempotent retry: recorder state follows", "result", payload);
            case REJECTED -> Map.of("status", "rejected", "journal_state", "rejected",
                "error_class", "operation_rejected",
                "message", "previous transition under this key was rejected", "result", payload);
            default -> Map.of("status", "unknown", "journal_state", "unknown",
                "error_class", "operation_timeout_unknown",
                "message", "previous transition under this key is unproven; resolve before retrying",
                "result", payload);
        };
    }

    // -- timeline lifecycle (shared by contracts) ---------------------------------

    private Map<String, Object> submitTimeline(Map<String, Object> params, String envelopeKey) {
        String key = params.get("idempotency_key") instanceof String text && !text.isBlank()
            ? text
            : envelopeKey != null ? envelopeKey : null;
        if (key == null) {
            throw new IllegalArgumentException("idempotency_key must be a non-blank string");
        }
        Map<String, Object> previous = resolved.get(key);
        if (previous != null) {
            if ("unknown".equals(previous.get("status"))) {
                Map<String, Object> applied = new LinkedHashMap<>(previous);
                applied.put("status", "applied");
                applied.put("message", previous.get("message") + " (idempotent retry: already applied)");
                return applied;
            }
            return previous;
        }
        @SuppressWarnings("unchecked")
        Map<String, Object> timeline = (Map<String, Object>) params.get("timeline");
        if (timeline == null) {
            return reject("validation_failed", "params.timeline is required");
        }
        String timelineId = text(timeline, "timeline_id");
        int totalTicks = (int) asLong(timeline.get("total_ticks"), "total_ticks");
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> rawEvents = (List<Map<String, Object>>) timeline.get("events");
        List<TimelineEvent> events = new ArrayList<>();
        for (Map<String, Object> raw : rawEvents) {
            events.add(new TimelineEvent(
                (int) asLong(raw.get("tick"), "tick"),
                text(raw, "type"),
                (Map<String, Object>) raw.getOrDefault("payload", Map.of())));
        }
        try {
            TimelineModel.validate(events, totalTicks);
        } catch (IllegalArgumentException error) {
            return reject("validation_failed", error.getMessage());
        }
        if (TimelineModel.touchesFlashback(events) && !flashback.enabled()) {
            return reject("manual_intervention_required", flashback.disabledReason());
        }
        synchronized (timelineLock) {
            if (scheduler != null
                && (scheduler.state() == TickScheduler.State.RUNNING)) {
                return reject("operation_rejected", "another timeline is running; single-session bridge");
            }
            List<TimelineEvent> ordered = List.copyOf(events);
            replayEventTimes=List.of(); timelineFeedback=List.of(); timelineFeedbackFailure=null;
            scheduler = new TickScheduler(ordered, totalTicks, this::dispatchEvent);
            activeTimelineId = timelineId;
        }        Map<String, Object> result = Map.of(
            "status", "applied",
            "result", Map.of("timeline_id", timelineId, "total_ticks", totalTicks));
        resolved.put(key, result);
        return result;
    }

    /** Runs one event now; the Minecraft main thread owns the tick clock. */
    private void dispatchEvent(TimelineEvent event) {
        long stamp=replayPort.recordingTimestamp(activeTimelineId);
        if (stamp>=0) {
            List<Map<String,Object>> stamps=new ArrayList<>(replayEventTimes);
            stamps.add(Map.of("type",event.type(),"planned_tick",event.tick(),"timestamp_ms",stamp));
            replayEventTimes=List.copyOf(stamps);
        }
        switch (event.type()) {
            case TimelineEvent.MOCAP_SCENE_CREATE ->
                commands.run("mocap scenes add " + event.payload().get("scene"));
            case TimelineEvent.MOCAP_SCENE_ADD -> {
                Map<String, Object> payload = event.payload();
                Map<String, Object> offset = castMap(payload.get("offset"));
                String skin = payload.get("skin_file") instanceof String s ? s : null;
                if (skin != null && !skin.matches("[A-Za-z0-9_-]{1,64}"))
                    throw new IllegalArgumentException("skin_file must name a registered local skin without a path or extension");
                commands.run("mocap scenes addTo " + payload.get("scene")
                    + " " + payload.get("recording")
                    + " " + asLong(payload.getOrDefault("delay_ticks", 0L), "delay")
                    + " " + asLong(offset.getOrDefault("x", 0L), "x")
                    + " " + asLong(offset.getOrDefault("y", 0L), "y")
                    + " " + asLong(offset.getOrDefault("z", 0L), "z")
                    + " " + payload.get("player_name")
                    + (skin == null ? "" : " from_file " + skin));
            }
            case TimelineEvent.MOCAP_SCENE_PLAY ->
                commands.run("mocap playing start ." + event.payload().get("scene"));
            case TimelineEvent.MOCAP_SCENE_STOP -> commands.run("mocap playing stopScene ." + event.payload().get("scene"));
            case TimelineEvent.FLASHBACK_START -> flashback.startRecording(activeTimelineId);
            case TimelineEvent.FLASHBACK_STOP -> flashback.stopRecording(activeTimelineId);
            default -> { }
        }
    }

    /** Volatile read: the client tick thread must never block on the HTTP path. */
    public TickScheduler activeScheduler() {
        return scheduler;
    }

    public String activeTimelineId() {
        return activeTimelineId;
    }

    /** Called by the client message callback, never waits for the HTTP thread. */
    public void observeTimelineFeedback(String raw) {
        TickScheduler current=scheduler;
        if (current==null || current.state()!=TickScheduler.State.RUNNING) return;
        String line=dev.mcfilm.cinematicbridge.mocap.MocapFeedback.stripFormatting(raw);
        if (line==null) return;
        if (line.startsWith("Error:")) { timelineFeedbackFailure=line; current.cancel(); }
        if (List.of("Scene successfully added","Element successfully added to scene","Playing started...",
                "Playing stopped","Owned scene already completed","Playing of all scenes stopped").contains(line)) {
            List<String> feedback=new ArrayList<>(timelineFeedback); feedback.add(line);
            timelineFeedback=List.copyOf(feedback);
        }
    }

    private Map<String, Object> timelineStatus() {
        if (scheduler == null) {
            return Map.of("status", "unknown", "error_class", "operation_timeout_unknown",
                "message", "no timeline has been submitted");
        }
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("timeline_id", activeTimelineId);
        result.put("state", scheduler.state().name());
        result.put("events_executed", scheduler.currentEventIndex());
        result.put("feedback",timelineFeedback);
        if (!replayEventTimes.isEmpty()) {
            result.put("replay_start_ms",replayEventTimes.get(0).get("timestamp_ms"));
            result.put("replay_event_times",replayEventTimes);
        }
        if (timelineFeedbackFailure!=null) {
            result.put("state","failed"); result.put("failure",timelineFeedbackFailure);
        }
        result.put("total_ticks", scheduler.totalTicks());
        return Map.of("status", "applied", "result", result);
    }

    private Map<String, Object> cancelTimeline() {
        TickScheduler current = scheduler;
        if (current == null) {
            return reject("operation_rejected", "no active timeline");
        }
        current.cancel();
        return Map.of("status", "applied", "result", Map.of("state", current.state().name()));
    }

    // -- flashback-gated operations -------------------------------------------

    private Map<String, Object> replaceCameraTrack(Map<String, Object> params) {
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> keyframes = (List<Map<String, Object>>) params.get("keyframes");
        String interpolation = (String) params.getOrDefault("interpolation", "smooth");
        Object converted;
        try {
            converted = CameraTrackConverter.convert(keyframes, interpolation);
        } catch (IllegalArgumentException error) {
            return reject("validation_failed", error.getMessage());
        }
        return flashback.replaceCameraTrack(text(params, "timeline_id"), converted);
    }

    private Map<String, Object> startExport(Map<String, Object> params) {
        @SuppressWarnings("unchecked")
        Map<String, Object> range = (Map<String, Object>) params.get("range");
        if (range == null) {
            return reject("validation_failed", "params.range is required");
        }
        return flashback.startExport(
            text(params, "timeline_id"),
            (int) asLong(range.get("start_tick"), "start_tick"),
            (int) asLong(range.get("end_tick"), "end_tick"),
            (int) asLong(params.getOrDefault("width", 1280L), "width"),
            (int) asLong(params.getOrDefault("height", 720L), "height"),
            (int) asLong(params.getOrDefault("fps", 30L), "fps"),
            (String) params.getOrDefault("output_path", ""));
    }

    // -- helpers ---------------------------------------------------------------

    private Map<String, Object> command(String command, Map<String, Object> params) {
        String output = commands.run(command);
        return Map.of("status", "applied", "result", Map.of("command", command, "output", output == null ? "" : output));
    }

    private static Map<String, Object> reject(String errorClass, String message) {
        return Map.of("status", "rejected", "error_class", errorClass, "message", message);
    }

    private static String text(Map<String, Object> params, String key) {
        Object value = params.get(key);
        if (!(value instanceof String string) || string.isBlank()) {
            throw new IllegalArgumentException(key + " must be a non-blank string");
        }
        return string;
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> castMap(Object value) {
        return value == null ? Map.of() : (Map<String, Object>) value;
    }

    private static long asLong(Object value, String field) {
        if (value instanceof Number number) {
            return number.longValue();
        }
        throw new IllegalArgumentException(field + " must be a number");
    }
}
