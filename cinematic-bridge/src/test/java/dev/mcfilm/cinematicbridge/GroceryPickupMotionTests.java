package dev.mcfilm.cinematicbridge;
import dev.mcfilm.cinematicbridge.actor.*;
import org.joml.Quaternionf;
import org.joml.Vector3f;
public final class GroceryPickupMotionTests {
    public static void main(String[] args){
        double maximum=0;
        for(int i=0;i<4;i++){var frame=new GroceryPickupMotion.ElbowFrame();for(int n=0;n<=1000;n++){
            float p=n/1000f;var s=GroceryPickupMotion.shoulder(GroceryPickupMotion.left(i));var h=GroceryPickupMotion.hand(i,p);var e=frame.solve(s,h);
            double d=distance(s,h);maximum=Math.max(maximum,d);
            if(Math.abs(distance(s,e)-.375)>1e-5||Math.abs(distance(e,h)-.375)>1e-5)throw new AssertionError("original arm segments changed");
            if(p<.3&&!GroceryPickupMotion.item(i,p).equals(GroceryPickupMotion.source(i)))throw new AssertionError("item moved before contact");
            if(GroceryPickupMotion.gripped(p)&&Math.abs(distance(h,GroceryPickupMotion.item(i,p))-GroceryPickupMotion.PALM_OFFSET)>1e-5)throw new AssertionError("item lost palm contact offset");
            if(h.y()<.01874)throw new AssertionError("hand below supporting plane");
        }}
        for(int i=0;i<4;i++)if(!GroceryPickupMotion.hand(i,0).equals(GroceryPickupMotion.rest(GroceryPickupMotion.left(i)))||!GroceryPickupMotion.hand(i,1).equals(GroceryPickupMotion.rest(GroceryPickupMotion.left(i))))throw new AssertionError("hand cycle endpoints differ");
        for(int i=0;i<4;i++){
            if(distance(GroceryPickupMotion.item(i,.8f),GroceryPickupMotion.bag())>1e-5)throw new AssertionError("item not inside bag before storing");
            if(GroceryPickupMotion.upright(.65f)!=1||GroceryPickupMotion.collected(.799f)||!GroceryPickupMotion.collected(.8f))throw new AssertionError("storage precedes upright deposit");
        }
        double maxStep=0;
        for(int i=0;i<4;i++){
            Quaternionf[] previous=new Quaternionf[2];
            var frame=new GroceryPickupMotion.ElbowFrame();
            for(int n=0;n<GroceryPickupMotion.CYCLE;n++){
                float p=n/(float)(GroceryPickupMotion.CYCLE-1);var s=GroceryPickupMotion.shoulder(GroceryPickupMotion.left(i));var h=GroceryPickupMotion.hand(i,p);var e=frame.solve(s,h);
                var rotations=new Quaternionf[]{GroceryPickupMotion.rotation(vec(s),vec(e),previous[0]==null?new Quaternionf():new Quaternionf(previous[0])),GroceryPickupMotion.rotation(vec(e),vec(h),previous[1]==null?new Quaternionf():new Quaternionf(previous[1]))};
                for(int j=0;j<2;j++){
                    Vector3f actual=rotations[j].transform(new Vector3f(0,-.375f,0)).add(j==0?vec(s):vec(e));
                    if(actual.distance(j==0?vec(e):vec(h))>1e-5)throw new AssertionError("bone frame lost endpoint");
                    if(previous[j]!=null){double step=2*Math.toDegrees(Math.acos(Math.min(1,Math.abs(previous[j].dot(rotations[j])))));maxStep=Math.max(maxStep,step);if(step>30)throw new AssertionError("arm frame twitch: "+step+" item="+i+" sample="+n+" bone="+j+" shoulder="+s+" elbow="+e+" hand="+h);}
                    previous[j]=rotations[j];
                }
            }
        }
        System.out.println("GroceryPickupMotionTests:360 discrete arm frames passed; max angle/tick="+maxStep);
        System.out.println("GroceryPickupMotionTests:4004 contact/arm/floor samples passed; max reach="+maximum);
    }
    private static double distance(BagPackingMotion.Point a,BagPackingMotion.Point b){return Math.sqrt(Math.pow(a.x()-b.x(),2)+Math.pow(a.y()-b.y(),2)+Math.pow(a.z()-b.z(),2));}
    private static Vector3f vec(BagPackingMotion.Point p){return new Vector3f(p.x(),p.y(),p.z());}
}
