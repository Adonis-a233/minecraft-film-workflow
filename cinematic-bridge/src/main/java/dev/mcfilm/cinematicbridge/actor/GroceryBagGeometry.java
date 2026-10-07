package dev.mcfilm.cinematicbridge.actor;

import org.joml.Vector3f;

/** Bounds of the two existing classmate elder bag/handle cuboids at scale1.6.
 * This is an open paper bag with four separated upright vanilla sprite slots. */
public final class GroceryBagGeometry {
    public static final int MODEL_ID=72800;
    public static final float SCALE=1.6f,CENTER_Y=.24f,CENTER_Z=.4f;
    public static final float HALF_X=.275f,HALF_Z=.225f,MOUTH_Y=.48f;
    public static final int RELEASE_TICK=680,SETTLED_TICK=685;
    public static final float RELEASE_FOOD_Y=.55f;
    public static Vector3f storedFood(int item){
        if(item<0||item>3)throw new IllegalArgumentException("unregistered grocery slot");
        return new Vector3f(0,.2f,CENTER_Z+(item-1.5f)*.055f);
    }
    public static Vector3f storedHand(int item){return storedFood(item).add(0,GroceryPickupMotion.PALM_OFFSET,0);}
    public static Vector3f depositedFood(int item,int elapsed){
        if(elapsed<0)throw new IllegalArgumentException("bag fall clock before release");
        var p=storedFood(item);p.y=(float)Math.max(p.y,RELEASE_FOOD_Y-.5*GroceryScatterMotion.GRAVITY*elapsed*elapsed);return p;
    }
    public static boolean containsUprightFood(int item,Vector3f p){
        var slot=storedFood(item);
        return p.distance(slot)<.001f&&Math.abs(p.x)+.2f<=HALF_X&&Math.abs(p.z-CENTER_Z)+.0125f<=HALF_Z&&p.y-.2f>=-1e-6f&&p.y+.2f<=MOUTH_Y;
    }
    private GroceryBagGeometry(){}
}
