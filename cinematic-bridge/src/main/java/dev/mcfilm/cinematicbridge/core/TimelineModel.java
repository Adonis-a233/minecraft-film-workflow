package dev.mcfilm.cinematicbridge.core;

import java.util.List;

/** Structural validation shared by the controller-facing bridge endpoints. */
public final class TimelineModel {
    private TimelineModel() {}

    public static void validate(List<TimelineEvent> events, int totalTicks) {
        if (events == null || events.size() < 2) {
            throw new IllegalArgumentException("timeline needs at least 2 events");
        }
        if (totalTicks < 1 || totalTicks > 24_000) {
            throw new IllegalArgumentException("total_ticks out of range: " + totalTicks);
        }
        int starts = 0;
        int stops = 0;
        int startTick = -1;
        int stopTick = -1;
        int previous = -1;
        for (TimelineEvent event : events) {
            if (event.tick() < 0 || event.tick() > totalTicks) {
                throw new IllegalArgumentException(
                    "event " + event.type() + " tick " + event.tick() + " escapes 0.." + totalTicks);
            }
            if (event.tick() < previous) {
                throw new IllegalArgumentException("timeline events must be in ascending tick order");
            }
            previous = event.tick();
            switch (event.type()) {
                case TimelineEvent.ASSERT_STATE -> {
                    if (event.tick() != 0) {
                        throw new IllegalArgumentException("assert_state must be at tick 0");
                    }
                }
                case TimelineEvent.FLASHBACK_START -> {
                    starts++;
                    startTick = event.tick();
                }
                case TimelineEvent.FLASHBACK_STOP -> {
                    stops++;
                    stopTick = event.tick();
                }
                default -> { }
            }
        }
        if (events.get(0).tick() != 0 || !events.get(0).type().equals(TimelineEvent.ASSERT_STATE)) {
            throw new IllegalArgumentException("timeline must open with assert_state at tick 0");
        }
        if (starts == 0 && stops == 0) {
            // Mocap-only timeline (T5/T6-style playback): legal without Flashback.
            return;
        }
        if (starts != 1 || stops != 1) {
            throw new IllegalArgumentException(
                "timeline must contain exactly one flashback start and stop, got " + starts + "/" + stops);
        }
        if (startTick >= stopTick) {
            throw new IllegalArgumentException("flashback recording window is empty or inverted");
        }
    }

    /** Returns {startTick, stopTick} of the flashback recording window. */
    public static int[] recordingWindow(List<TimelineEvent> events) {
        int start = -1;
        int stop = -1;
        for (TimelineEvent event : events) {
            if (event.type().equals(TimelineEvent.FLASHBACK_START)) {
                start = event.tick();
            } else if (event.type().equals(TimelineEvent.FLASHBACK_STOP)) {
                stop = event.tick();
            }
        }
        if (start < 0 || stop < 0) {
            throw new IllegalArgumentException("timeline has no recording window");
        }
        return new int[] {start, stop};
    }

    public static boolean touchesFlashback(List<TimelineEvent> events) {
        return events.stream().anyMatch(e
            -> e.type().equals(TimelineEvent.FLASHBACK_START)
            || e.type().equals(TimelineEvent.FLASHBACK_STOP));
    }
}
