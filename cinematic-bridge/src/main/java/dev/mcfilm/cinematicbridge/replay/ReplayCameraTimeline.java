package dev.mcfilm.cinematicbridge.replay;
import com.replaymod.pathing.properties.CameraProperties;
import com.replaymod.pathing.properties.TimestampProperty;
import com.replaymod.replaystudio.pathing.interpolation.*;
import com.replaymod.replaystudio.pathing.path.Keyframe;
import com.replaymod.replaystudio.pathing.path.Timeline;
import com.replaymod.lib.org.apache.commons.lang3.tuple.Triple;
import dev.mcfilm.cinematicbridge.core.CameraTrackConverter;
import java.util.*;
/** Camera interpolation and range cropping against the pinned ReplayStudio API. */
public final class ReplayCameraTimeline {
    private ReplayCameraTimeline() {}
    public static Timeline buildTimeline(List<Map<String, Object>> rawKeyframes, String interpolation) {
        if (rawKeyframes == null || rawKeyframes.size() < 2) {
            throw new IllegalArgumentException("a camera track needs at least two keyframes");
        }
        Timeline timeline = new com.replaymod.replaystudio.pathing.impl.TimelineImpl();
        registerTimelineProperties(timeline);
        com.replaymod.replaystudio.pathing.path.Path path = timeline.createPath();
        path.setActive(true);
        long previousTime = -1;
        for (Map<String, Object> raw : rawKeyframes) {
            // Contract v3 keyframes carry rotation:[yaw,pitch,roll] and an
            // optional fov; the shared IR wants top-level yaw/pitch/roll/fov.
            Map<String, Object> normalized = new LinkedHashMap<>(raw);
            if (raw.get("rotation") instanceof List<?> rotation && rotation.size() == 3) {
                normalized.put("yaw", ((Number) rotation.get(0)).doubleValue());
                normalized.put("pitch", ((Number) rotation.get(1)).doubleValue());
                normalized.put("roll", ((Number) rotation.get(2)).doubleValue());
            }
            normalized.putIfAbsent("fov", 70.0);
            CameraTrackConverter.Keyframe keyframe = CameraTrackConverter.keyframeOf(normalized);
            if (!Double.isFinite(keyframe.fov()) || keyframe.fov()<1 || keyframe.fov()>150)
                throw new IllegalArgumentException("FOV must be within [1,150]");
            long timeMs = keyframe.tick() * 50L;
            if (timeMs <= previousTime) {
                throw new IllegalArgumentException("keyframe ticks must strictly increase");
            }
            previousTime = timeMs;
            Keyframe inserted = path.insert(timeMs);
            inserted.setValue(ReplayFovProperty.PROPERTY,keyframe.fov());
            inserted.setValue(TimestampProperty.PROPERTY, (int) timeMs);
            inserted.setValue(CameraProperties.POSITION, Triple.of(
                keyframe.x(), keyframe.y(), keyframe.z()));
            inserted.setValue(CameraProperties.ROTATION, Triple.of(
                (float) keyframe.yaw(), (float) keyframe.pitch(), (float) keyframe.roll()));
        }
        Interpolator interpolator = "linear".equalsIgnoreCase(interpolation)
            ? new LinearInterpolator()
            : new CatmullRomSplineInterpolator(0.5);
        registerCameraProperties(interpolator);
        path.getSegments().forEach(segment -> segment.setInterpolator(interpolator));
        path.updateAll();
        return timeline;
    }

    public static Timeline buildRangeTimeline(List<Map<String,Object>> frames, String interpolation, int start, int end) {
        Timeline full = buildTimeline(frames, interpolation);
        var path = full.getPaths().get(0);
        long first = ((Number) frames.get(0).get("tick")).longValue();
        long last = ((Number) frames.get(frames.size()-1).get("tick")).longValue();
        if (first > start || last < end) throw new IllegalArgumentException("camera does not cover render range");
        if (!"linear".equalsIgnoreCase(interpolation) && (first != start || last != end))
            throw new IllegalArgumentException("smooth camera must be compiled with exact range boundaries");
        Timeline cropped = new com.replaymod.replaystudio.pathing.impl.TimelineImpl();
        registerTimelineProperties(cropped);
        var target = cropped.createPath();
        target.setActive(true);
        var ticks = new java.util.TreeSet<Integer>();
        ticks.add(start); ticks.add(end);
        for (var frame : frames) { int tick = ((Number) frame.get("tick")).intValue(); if (tick > start && tick < end) ticks.add(tick); }
        for (int tick : ticks) {
            var k = target.insert((tick - start) * 50L);
            k.setValue(ReplayFovProperty.PROPERTY,path.getValue(ReplayFovProperty.PROPERTY,tick * 50L).orElseThrow());
            k.setValue(TimestampProperty.PROPERTY, tick * 50);
            k.setValue(CameraProperties.POSITION, path.getValue(CameraProperties.POSITION, tick * 50L).orElseThrow());
            k.setValue(CameraProperties.ROTATION, path.getValue(CameraProperties.ROTATION, tick * 50L).orElseThrow());
        }
        Interpolator i = "linear".equalsIgnoreCase(interpolation) ? new LinearInterpolator() : new CatmullRomSplineInterpolator(0.5);
        registerCameraProperties(i);
        target.getSegments().forEach(segment -> segment.setInterpolator(i));
        target.updateAll();
        return cropped;
    }

    private static void registerCameraProperties(Interpolator interpolator) {
        interpolator.registerProperty(TimestampProperty.PROPERTY);
        interpolator.registerProperty(ReplayFovProperty.PROPERTY);
        interpolator.registerProperty(CameraProperties.POSITION);
        interpolator.registerProperty(CameraProperties.ROTATION);
    }

    private static void registerTimelineProperties(Timeline timeline) {
        // Interpolator registration makes values readable; timeline registration
        // is separately required for ReplayStudio to apply them to the game.
        timeline.registerProperty(TimestampProperty.PROPERTY);
        timeline.registerProperty(ReplayFovProperty.PROPERTY);
        timeline.registerProperty(CameraProperties.POSITION);
        timeline.registerProperty(CameraProperties.ROTATION);
    }

}
