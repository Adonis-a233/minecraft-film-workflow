package dev.mcfilm.cinematicbridge.actor;

/** Ballistic travel followed by inelastic floor contact; time is in 20 Hz ticks. */
public final class GroceryScatterMotion {
    public static final double RELEASE_HEIGHT=.75, FLOOR_HEIGHT=.0125;
    // Explicit shot parameters, not an assertion about vanilla entity physics.
    public static final double GRAVITY=.04, UPWARD_SPEED=.06;
    public static final double LANDING_TICK=(UPWARD_SPEED+Math.sqrt(UPWARD_SPEED*UPWARD_SPEED+2*GRAVITY*(RELEASE_HEIGHT-FLOOR_HEIGHT)))/GRAVITY;
    public record Sample(double x,double y,double z,boolean grounded) {}
    public static Sample fromOpening(double sx,double sy,double sz,double dx,double dz,double elapsed) {
        if(!Double.isFinite(sx)||!Double.isFinite(sy)||!Double.isFinite(sz)||!Double.isFinite(dx)||!Double.isFinite(dz)||!Double.isFinite(elapsed)||elapsed<0||sy<FLOOR_HEIGHT||sy>2.1)
            throw new IllegalArgumentException("invalid grocery release opening");
        double landing=(UPWARD_SPEED+Math.sqrt(UPWARD_SPEED*UPWARD_SPEED+2*GRAVITY*(sy-FLOOR_HEIGHT)))/GRAVITY;
        if(elapsed>=landing)return new Sample(dx,FLOOR_HEIGHT,dz,true);
        double travel=elapsed/landing;
        return new Sample(sx+(dx-sx)*travel,sy+UPWARD_SPEED*elapsed-.5*GRAVITY*elapsed*elapsed,sz+(dz-sz)*travel,false);
    }
    public static Sample sample(double dx,double dz,double elapsed) {
        if(!Double.isFinite(dx)||!Double.isFinite(dz)||!Double.isFinite(elapsed)||elapsed<0)
            throw new IllegalArgumentException("invalid grocery scatter sample");
        if(elapsed>=LANDING_TICK)return new Sample(dx,FLOOR_HEIGHT,dz,true);
        double travel=elapsed/LANDING_TICK;
        return new Sample(dx*travel,RELEASE_HEIGHT+UPWARD_SPEED*elapsed-.5*GRAVITY*elapsed*elapsed,dz*travel,false);
    }
    private GroceryScatterMotion() {}
}
