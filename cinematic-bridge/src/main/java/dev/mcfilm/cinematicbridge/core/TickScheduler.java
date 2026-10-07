package dev.mcfilm.cinematicbridge.core;

import java.util.ArrayList;
import java.util.List;

/**
 * Deterministic tick scheduler: the heart of the bridge (plan §9.1).
 *
 * The Minecraft main thread calls {@link #tick(int)} once per client tick
 * with the world's current tick; every event whose plan tick has arrived
 * fires exactly once, in plan order, and is journaled with its planned vs.
 * actual tick. Wall-clock time is never consulted.
 */
public final class TickScheduler {

    public enum State { READY, RUNNING, COMPLETED, CANCELLED }

    public record ExecutedEvent(TimelineEvent event, int actualTick) {}

    @FunctionalInterface
    public interface EventHandler {
        /** Must not throw; the host decides how failures map to bridge errors. */
        void accept(TimelineEvent event);
    }

    private final List<TimelineEvent> events;
    private final EventHandler handler;
    private final int totalTicks;
    private final List<ExecutedEvent> journal = new ArrayList<>();
    private int cursor = 0;
    private State state = State.READY;

    public TickScheduler(List<TimelineEvent> events, int totalTicks, EventHandler handler) {
        TimelineModel.validate(events, totalTicks);
        this.events = List.copyOf(events);
        this.totalTicks = totalTicks;
        this.handler = handler;
    }

    public synchronized List<TimelineEvent> tick(int tick) {
        if (state == State.CANCELLED || state == State.COMPLETED) {
            return List.of();
        }
        state = State.RUNNING;
        List<TimelineEvent> fired = new ArrayList<>();
        while (cursor < events.size() && events.get(cursor).tick() <= tick) {
            TimelineEvent event = events.get(cursor);
            handler.accept(event);
            journal.add(new ExecutedEvent(event, tick));
            fired.add(event);
            cursor++;
        }
        if (cursor >= events.size() && tick >= totalTicks) {
            state = State.COMPLETED;
        }
        return List.copyOf(fired);
    }

    public synchronized void cancel() {
        if (state == State.RUNNING || state == State.READY) {
            state = State.CANCELLED;
        }
    }

    public synchronized State state() {
        return state;
    }

    public synchronized int currentEventIndex() {
        return cursor;
    }

    public synchronized List<ExecutedEvent> journal() {
        return List.copyOf(journal);
    }

    public int totalTicks() {
        return totalTicks;
    }
}
