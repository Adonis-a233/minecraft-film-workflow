package dev.mcfilm.cinematicbridge.actor;

import org.joml.Quaternionf;
import org.joml.Vector3f;
import java.util.HashMap;
import java.util.Map;

/** Continuous original-length arm orientation, without rotationTo antipodal roll flips. */
public final class PackingArmPose {
    public record Pose(Vector3f shoulder,Vector3f elbow,Vector3f hand,Quaternionf upper,Quaternionf lower) {}
    private final Map<String,Quaternionf> previous=new HashMap<>();
    public Pose sample(Vector3f shoulder,Vector3f hand){
        return sample(shoulder,hand,true);
    }
    public Pose sample(Vector3f shoulder,Vector3f hand,boolean lateral){
        var s=new BagPackingMotion.Point(shoulder.x,shoulder.y,shoulder.z);var h=new BagPackingMotion.Point(hand.x,hand.y,hand.z);
        var joint=lateral?BagPackingMotion.elbowLateral(s,h):BagPackingMotion.elbow(s,h);
        var elbow=new Vector3f(joint.x(),joint.y(),joint.z());
        return new Pose(new Vector3f(shoulder),elbow,new Vector3f(hand),bone("upper",shoulder,elbow),bone("lower",elbow,hand));
    }
    private Quaternionf bone(String name,Vector3f a,Vector3f b){
        var y=new Vector3f(a).sub(b).normalize();var old=previous.getOrDefault(name,new Quaternionf());
        var q=new Quaternionf().rotationTo(new Quaternionf(old).transform(new Vector3f(0,1,0)),y).mul(old).normalize();
        var target=new Vector3f(1,0,0).sub(new Vector3f(y).mul(y.x));
        if(target.lengthSquared()>.02f){
            target.normalize();var x=new Quaternionf(q).transform(new Vector3f(1,0,0));
            float roll=(float)Math.atan2(y.dot(new Vector3f(x).cross(target)),x.dot(target));
            roll=Math.max(-(float)Math.toRadians(8),Math.min((float)Math.toRadians(8),roll));
            q=new Quaternionf().fromAxisAngleRad(y,roll).mul(q).normalize();
        }
        previous.put(name,new Quaternionf(q));return q;
    }
}
