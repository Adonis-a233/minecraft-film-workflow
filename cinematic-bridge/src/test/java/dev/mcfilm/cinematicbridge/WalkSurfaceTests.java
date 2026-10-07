package dev.mcfilm.cinematicbridge;
import dev.mcfilm.cinematicbridge.actor.WalkSurface;
import java.util.List;

public final class WalkSurfaceTests {
    public static void main(String[] args) {
        double height=1;
        for (double actual : new double[]{1,1,.5,.5,0,0}) {
            height=WalkSurface.nextHeight(height,List.of(actual));
            require(height==actual,"downward half-slab profile");
        }
        for (double actual : new double[]{0,.5,.5,1,1}) {
            height=WalkSurface.nextHeight(height,List.of(actual));
            require(height==actual,"upward half-slab profile");
        }
        require(Double.isNaN(WalkSurface.nextHeight(1,List.of(0.0))),"full-block drop rejected");
        require(Double.isNaN(WalkSurface.nextHeight(0,List.of(1.0))),"full-block ascent rejected");
        require(Double.isNaN(WalkSurface.nextHeight(0,List.of())),"gap or obstructed column rejected");
        require(Double.isNaN(WalkSurface.nextHeight(0,List.of(Double.NaN))),"invalid surface rejected");
        require(WalkSurface.nextHeight(0,List.of(0.5,0.0))==0,"nearest supported surface selected");
        System.out.println("WalkSurfaceTests: 16 checks passed");
    }
    private static void require(boolean value,String label) {if(!value)throw new AssertionError(label);}
}
