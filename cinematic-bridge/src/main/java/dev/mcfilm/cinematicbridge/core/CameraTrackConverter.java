package dev.mcfilm.cinematicbridge.core;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * Deterministic CameraTrack → Flashback keyframe IR conversion (plan §5,
 * "CameraTrack → Flashback 转换器" row, and P4 investigation: Flashback keeps
 * position, rotation and FOV as parallel keyframe tracks).
 *
 * The output is a neutral intermediate representation — three parallel track
 * lists with per-segment interpolation — which the (license-gated) Flashback
 * port would map onto the real 0.39.8 keyframe classes. Pure logic, fully
 * testable without Minecraft.
 */
public final class CameraTrackConverter {
    private CameraTrackConverter() {}

    public enum Interpolation { LINEAR, SMOOTH }

    public record Keyframe(int tick, double x, double y, double z, double yaw, double pitch, double roll, double fov) {}

    public record Segment(String track, Keyframe from, Keyframe to, Interpolation interpolation) {}

    public record ConvertedTrack(List<Segment> position, List<Segment> rotation, List<Segment> fov) {}

    public static Keyframe keyframeOf(Map<String, Object> raw) {
        int tick = (int) asLong(raw.get("tick"), "tick");
        List<?> position = (List<?>) raw.get("position");
        if (position == null || position.size() != 3) {
            throw new IllegalArgumentException("keyframe needs position[3]");
        }
        return new Keyframe(
            tick,
            asDouble(position.get(0), "position.x"),
            asDouble(position.get(1), "position.y"),
            asDouble(position.get(2), "position.z"),
            asDouble(raw.get("yaw"), "yaw"),
            asDouble(raw.get("pitch"), "pitch"),
            asDouble(raw.getOrDefault("roll", 0.0), "roll"),
            asDouble(raw.get("fov"), "fov")
        );
    }

    /** @param interpolation "linear" or "smooth" (contracts/v1/camera-track) */
    public static ConvertedTrack convert(List<Map<String, Object>> keyframes, String interpolation) {
        if (keyframes == null || keyframes.size() < 2) {
            throw new IllegalArgumentException("camera track needs at least 2 keyframes");
        }
        Interpolation mode = switch (interpolation == null ? "smooth" : interpolation) {
            case "linear" -> Interpolation.LINEAR;
            case "smooth" -> Interpolation.SMOOTH;
            default -> throw new IllegalArgumentException("unknown interpolation: " + interpolation);
        };
        List<Keyframe> frames = keyframes.stream().map(CameraTrackConverter::keyframeOf).toList();
        for (int i = 1; i < frames.size(); i++) {
            if (frames.get(i).tick() <= frames.get(i - 1).tick()) {
                throw new IllegalArgumentException("keyframe ticks must be strictly increasing");
            }
        }
        List<Segment> position = new ArrayList<>();
        List<Segment> rotation = new ArrayList<>();
        List<Segment> fov = new ArrayList<>();
        for (int i = 0; i + 1 < frames.size(); i++) {
            Keyframe from = frames.get(i);
            Keyframe to = frames.get(i + 1);
            position.add(new Segment("position", from, to, mode));
            rotation.add(new Segment("rotation", from, to, mode));
            fov.add(new Segment("fov", from, to, mode));
        }
        return new ConvertedTrack(position, rotation, fov);
    }

    private static long asLong(Object value, String field) {
        if (value instanceof Number number) {
            return number.longValue();
        }
        throw new IllegalArgumentException(field + " must be a number");
    }

    private static double asDouble(Object value, String field) {
        if (value instanceof Number number) {
            return number.doubleValue();
        }
        throw new IllegalArgumentException(field + " must be a number");
    }
}
