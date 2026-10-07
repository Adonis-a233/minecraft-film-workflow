package dev.mcfilm.cinematicbridge.mocap;

import dev.mcfilm.cinematicbridge.state.MocapStateV2;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Mocap recorder state machine (plan v2 §Phase D):
 *
 *   idle → waiting_for_selection → recording → recorded_unsaved → saved
 *   with discarded / rejected / unknown exits.
 *
 * Dispatching a command is NEVER a transition: each transition method only
 * checks legality and runs the command; the phase moves when classified
 * feedback arrives through {@link #observe(String)} (wired to client chat
 * events). The controller therefore polls get_status after every transition
 * instead of trusting the dispatch.
 */
public final class MocapStateMachine {

    /** Runs a slash command on the client thread; feedback arrives separately. */
    @FunctionalInterface
    public interface CommandRunner {
        void run(String command);
    }

    /** A legal transition: the command to run and the phase it should produce. */
    public record Transition(String command, MocapStateV2.Phase expectedPhase) {}

    private final CommandRunner commands;
    private MocapStateV2.Phase phase = MocapStateV2.Phase.IDLE;
    private String recordingName;
    private String lastFeedback;
    private String selectedPlayer;

    public MocapStateMachine(CommandRunner commands) {
        this.commands = commands;
    }

    public synchronized MocapStateV2.Phase phase() {
        return phase;
    }

    public synchronized MocapStateV2 status() {
        return new MocapStateV2(phase, recordingName, lastFeedback, null, null);
    }

    /** First `start`: idle → waiting_for_selection (proven two-step start, F6). */
    public synchronized Transition prepare() {
        return prepare(null);
    }

    public synchronized Transition prepare(String player) {
        require(player == null || player.matches("[A-Za-z0-9_]{1,16}"), "invalid recording player name");
        require(phase == MocapStateV2.Phase.IDLE
                || phase == MocapStateV2.Phase.SAVED
                || phase == MocapStateV2.Phase.DISCARDED
                || phase == MocapStateV2.Phase.REJECTED,
            "prepare_recording requires an idle recorder, current phase: " + phase.json());
        selectedPlayer = player;
        return run(startCommand(), MocapStateV2.Phase.WAITING_FOR_SELECTION);
    }

    /** Second `start`: waiting_for_selection → recording. */
    public synchronized Transition confirm() {
        require(phase == MocapStateV2.Phase.WAITING_FOR_SELECTION,
            "confirm_recording_start requires waiting_for_selection, current phase: " + phase.json());
        return run(startCommand(), MocapStateV2.Phase.RECORDING);
    }

    public synchronized Transition stop() {
        require(phase == MocapStateV2.Phase.RECORDING
                || phase == MocapStateV2.Phase.WAITING_FOR_SELECTION,
            "stop_recording requires recording or waiting_for_selection, current phase: " + phase.json());
        return run("mocap recording stop", phase == MocapStateV2.Phase.RECORDING
            ? MocapStateV2.Phase.RECORDED_UNSAVED
            : MocapStateV2.Phase.IDLE);
    }

    public synchronized Transition save(String name) {
        require(phase == MocapStateV2.Phase.RECORDED_UNSAVED,
            "save_recording requires recorded_unsaved, current phase: " + phase.json());
        require(name != null && name.matches("[A-Za-z0-9_-]{1,64}"),
            "recording name must match [A-Za-z0-9_-]{1,64}");
        return run("mocap recording save " + name, MocapStateV2.Phase.SAVED);
    }

    public synchronized Transition discard() {
        require(phase == MocapStateV2.Phase.RECORDED_UNSAVED
                || phase == MocapStateV2.Phase.WAITING_FOR_SELECTION,
            "discard_recording requires recorded_unsaved or waiting_for_selection, current phase: "
                + phase.json());
        return run("mocap recording stop", phase == MocapStateV2.Phase.WAITING_FOR_SELECTION
            ? MocapStateV2.Phase.IDLE : MocapStateV2.Phase.DISCARDED);
    }

    /** Unknown recording feedback fails closed; other message domains are ignored. */
    public synchronized void observeGameMessage(String rawLine, boolean recordingDomain) {
        if (recordingDomain || MocapFeedback.classify(rawLine)!=MocapFeedback.UNKNOWN) observe(rawLine);
    }

    /** Called for every observed client feedback line; UNKNOWN fails closed. */
    public synchronized void observe(String rawLine) {
        MocapFeedback feedback = MocapFeedback.classify(rawLine);
        lastFeedback = MocapFeedback.stripFormatting(rawLine);
        switch (feedback) {
            case WAITING_FOR_SELECTION -> phase = MocapStateV2.Phase.WAITING_FOR_SELECTION;
            case RECORDING_STARTED -> phase = MocapStateV2.Phase.RECORDING;
            case RECORDING_STOPPED -> phase = MocapStateV2.Phase.RECORDED_UNSAVED;
            case RECORDING_DISCARDED -> phase = MocapStateV2.Phase.DISCARDED;
            case SAVE_SUCCESS -> phase = MocapStateV2.Phase.SAVED;
            case WAITING_CANCELLED -> phase = MocapStateV2.Phase.IDLE;
            case SAVE_REJECTED_EMPTY -> phase = MocapStateV2.Phase.REJECTED;
            case UNKNOWN -> phase = MocapStateV2.Phase.UNKNOWN;
        }
    }

    /** Explicitly records a successful save's artifact name (set by the dispatcher). */
    public synchronized void recordSaved(String name) {
        require(phase == MocapStateV2.Phase.SAVED, "recordSaved requires the saved phase");
        this.recordingName = name;
    }

    public synchronized Map<String, Object> evidence() {
        Map<String, Object> map = new LinkedHashMap<>();
        map.put("state", status().toMap());
        return map;
    }

    private String startCommand() {
        return "mocap recording start" + (selectedPlayer == null ? "" : " " + selectedPlayer);
    }

    private Transition run(String command, MocapStateV2.Phase expectedPhase) {
        commands.run(command);
        return new Transition(command, expectedPhase);
    }

    private static void require(boolean condition, String message) {
        if (!condition) {
            throw new IllegalStateException(message);
        }
    }
}
