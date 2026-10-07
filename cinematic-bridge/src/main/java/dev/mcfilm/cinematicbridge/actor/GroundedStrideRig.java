package dev.mcfilm.cinematicbridge.actor;
import org.joml.Vector3f;
import org.joml.Quaternionf;

/** Candidate short steps: ankle XZ stays fixed during stance. Existing shoe
 * cuboids are separate ankle parts in v10 and stay flat on their support. */
public final class GroundedStrideRig {
    public static final int LENGTH=95;
    private static final int[] BOUNDARIES={0,12,25,37,50,62,75};
    public record Leg(Vector3f hip,Vector3f knee,Quaternionf upper,Quaternionf lower,Vector3f ankle,boolean stance) {}
    public static float hip(int n){return n<8?.75f-.12f*smooth(n/7f):n<85?.63f:.63f+.12f*smooth((n-85)/9f);}
    public static float ankleLift(int n){return .1f*(n<8?smooth(n/7f):n<85?1:1-smooth((n-85)/9f));}
    public static Leg leg(Vector3f root,Vector3f from,Vector3f to,int n,int route,boolean left,Quaternionf previous) {
        if(n<0||n>=LENGTH)throw new IllegalArgumentException("stride time outside0..94");
        float sign=left?-1:1;Vector3f anchor=new Vector3f(from).add(sign*.125f,0,0);float lift=0;boolean stance=true;
        for(int step=0;step<6;step++) {
            boolean movesLeft=step%2==1;if(movesLeft!=left)continue;
            int a=BOUNDARIES[step],b=BOUNDARIES[step+1];
            if(n<a)break;
            Vector3f destination=rootAt(from,to,Math.min(b,74),route).add(sign*.125f,0,0);
            if(n>=b)anchor=destination;
            else {float p=(n-a)/(float)(b-a);anchor.lerp(destination,smoother(p));lift=.05f*(float)Math.sin(Math.PI*smoother(p));stance=false;break;}
        }
        if(!left&&n>=75) {
            Vector3f destination=new Vector3f(to).add(sign*.125f,0,0);float p=Math.min(1,(n-75)/9f);
            anchor.lerp(destination,smoother(p));lift=.05f*(float)Math.sin(Math.PI*smoother(p));stance=n>=84;
        }
        Vector3f hipWorld=new Vector3f(root).add(sign*.125f,hip(n),0);
        Vector3f ankle=new Vector3f(anchor);ankle.y=lift+ankleLift(n);
            Vector3f d=new Vector3f(ankle).sub(hipWorld);float length=d.length();
            if(length>.75001f||length<.01f)throw new IllegalArgumentException("stride exceeds original leg reach: "+length+" n="+n);
            d.div(length);Vector3f pole=new Vector3f(0,0,1).sub(new Vector3f(d).mul(d.z)).normalize();
            float radius=(float)Math.sqrt(Math.max(0,.375*.375-length*length/4));
        Vector3f knee=new Vector3f(hipWorld).add(ankle).mul(.5f).add(pole.mul(radius));
        Quaternionf upper=frame(hipWorld,knee,new Quaternionf()),lower=frame(knee,ankle,previous);
        return new Leg(new Vector3f(hipWorld).sub(root),new Vector3f(knee).sub(root),upper,lower,new Vector3f(ankle),stance);
    }
    private static Quaternionf frame(Vector3f a,Vector3f b,Quaternionf prior) {
        Vector3f y=new Vector3f(a).sub(b).normalize();
        return new Quaternionf().rotationTo(new Quaternionf(prior).transform(new Vector3f(0,1,0)),y).mul(prior).normalize();
    }
    public static Vector3f rootAt(Vector3f from,Vector3f to,int n,int route){
        if(route==0)return new Vector3f(from).lerp(to,smooth(n/74f));
        if(route!=1&&route!=2)throw new IllegalArgumentException("unregistered stride route");
        Vector3f bend=route==1?new Vector3f(from.x,0,to.z):new Vector3f(to.x,0,from.z);
        return n<37?new Vector3f(from).lerp(bend,smooth(n/37f)):new Vector3f(bend).lerp(to,smooth((n-37)/37f));
    }
    private static float smooth(float p){p=Math.max(0,Math.min(1,p));return p*p*(3-2*p);}
    private static float smoother(float p){p=Math.max(0,Math.min(1,p));return p*p*p*(p*(p*6-15)+10);}
    private GroundedStrideRig(){}
}
