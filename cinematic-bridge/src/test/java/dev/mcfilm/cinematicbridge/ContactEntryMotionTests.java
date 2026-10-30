package dev.mcfilm.cinematicbridge;
import dev.mcfilm.cinematicbridge.actor.ContactEntryMotion;
import org.joml.Vector3f;
public final class ContactEntryMotionTests {
    public static void main(String[] args){
        for(int duration:new int[]{6,20,40}){
            Vector3f shoulder=new Vector3f(.375f,1.4375f,0),elbow=new Vector3f(shoulder).add(0,-.375f,0),hand=new Vector3f(shoulder).add(0,-.75f,0);
            Vector3f to=new Vector3f(.35f,1.1f,.3f),toShoulder=new Vector3f(.375f,1.4375f,0);
            Vector3f targetElbow=new Vector3f(.6f,1.15f,.08f);
            Vector3f prior=null;
            for(int tick=0;tick<duration;tick++){
                var f=ContactEntryMotion.sample(shoulder,elbow,hand,toShoulder,targetElbow,to,tick/(float)(duration-1));
                if(Math.abs(f.shoulder().distance(f.elbow())-.375)>1e-5||Math.abs(f.elbow().distance(f.hand())-.375)>1e-5)throw new AssertionError("contact stretched a bone");
                if(tick==0&&f.hand().distance(hand)>1e-6)throw new AssertionError("entry hand discontinuity");
                if(tick==duration-1&&f.hand().distance(to)>1e-6)throw new AssertionError("contact never reached");
                if(prior!=null&&duration>=20&&prior.distance(f.hand())>.08)throw new AssertionError("hand approach jumps");
                prior=f.hand();
            }
        }
        try{ContactEntryMotion.sample(new Vector3f(),new Vector3f(0,-.375f,0),new Vector3f(0,-.75f,0),new Vector3f(),new Vector3f(),new Vector3f(2,0,0),1);throw new AssertionError("unreachable contact accepted");}catch(IllegalArgumentException expected){}
        System.out.println("ContactEntryMotionTests: exact start/end and fixed original bones; unreachable fails closed");
    }
}
