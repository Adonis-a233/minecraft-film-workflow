package dev.mcfilm.cinematicbridge;
import dev.mcfilm.cinematicbridge.replay.ReplayCameraTimeline;
import com.replaymod.pathing.properties.CameraProperties;
import com.replaymod.pathing.properties.TimestampProperty;
import java.util.List;
import java.util.Map;

public final class ReplayCameraTests {
    public static void main(String[] args) {
        var frames = List.of(
            Map.<String,Object>of("tick",20,"position",List.of(0.,75.,12.),"rotation",List.of(0.,10.,0.),"fov",40.),
            Map.<String,Object>of("tick",220,"position",List.of(10.,75.,12.),"rotation",List.of(90.,10.,0.),"fov",100.));
        var cropped = ReplayCameraTimeline.buildRangeTimeline(frames,"linear",40,200);
        for (var property : List.of(TimestampProperty.PROPERTY,CameraProperties.POSITION,CameraProperties.ROTATION)) {
            String id = (property.getGroup()==null ? "" : property.getGroup().getId()+":")+property.getId();
            if (cropped.getProperty(id)!=property) throw new AssertionError("property would never apply to game: "+id);
        }
        var path = cropped.getPaths().get(0);
        var fov=dev.mcfilm.cinematicbridge.replay.ReplayFovProperty.PROPERTY;
        if (cropped.getProperty("mcfilm_fov")!=fov) throw new AssertionError("FOV never applies to game");
        if (Math.abs(path.getValue(fov,0).orElseThrow()-46)>1e-6) throw new AssertionError("cropped FOV start");
        if (Math.abs(path.getValue(fov,8000).orElseThrow()-94)>1e-6) throw new AssertionError("cropped FOV end");
        dev.mcfilm.cinematicbridge.core.FovState.begin();
        fov.applyToGame(path.getValue(fov,4000).orElseThrow(),null);
        if (Math.abs(dev.mcfilm.cinematicbridge.core.FovState.rendered()-70)>1e-6) throw new AssertionError("FOV render value");
        dev.mcfilm.cinematicbridge.core.FovState.end();
        if (dev.mcfilm.cinematicbridge.core.FovState.rendered()!=null) throw new AssertionError("FOV leaked outside render");
        if (Math.abs(path.getValue(CameraProperties.POSITION,0).orElseThrow().getLeft()-1.)>1e-6)
            throw new AssertionError("cropped start position");
        if (Math.abs(path.getValue(CameraProperties.POSITION,8000).orElseThrow().getLeft()-9.)>1e-6)
            throw new AssertionError("cropped end position");
        if (path.getValue(TimestampProperty.PROPERTY,0).orElseThrow()!=2000)
            throw new AssertionError("replay time offset");
        if (path.getValue(TimestampProperty.PROPERTY,8000).orElseThrow()!=10000)
            throw new AssertionError("replay end offset");
        if (Math.abs(path.getValue(CameraProperties.ROTATION,4000).orElseThrow().getLeft()-45.)>1e-4)
            throw new AssertionError("rotation interpolation");
        ReplayCameraTimeline.buildRangeTimeline(frames,"smooth",20,220);
        try { ReplayCameraTimeline.buildRangeTimeline(frames,"smooth",40,200); throw new AssertionError("smooth crop silently changed curve"); }
        catch (IllegalArgumentException expected) {}
        System.out.println("Replay camera: 15 checks passed");
    }
}
