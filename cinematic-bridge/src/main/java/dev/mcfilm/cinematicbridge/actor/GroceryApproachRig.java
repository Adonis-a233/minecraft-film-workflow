package dev.mcfilm.cinematicbridge.actor;

import org.joml.Quaternionf;
import org.joml.Vector3f;
import java.util.*;

/** Pure candidate rig. Planned root waypoints must be reached by the actor service,
 * never copied into a live player's position. No Minecraft or display dependency. */
public final class GroceryApproachRig {
    public static final int ENTRY=20,WALK=3*GroundedStrideRig.LENGTH,CYCLE=750,DURATION=ENTRY+4*CYCLE+20;
    // Compact route removes two redundant waypoint strides per leg. All reach,
    // crouch, lift, release and withdrawal clocks retain their original duration.
    public static final int COMPACT_CYCLE=370,COMPACT_DURATION=ENTRY+4*COMPACT_CYCLE+20;
    private final boolean compact;
    public GroceryApproachRig(){this(false);}
    public GroceryApproachRig(boolean compact){this.compact=compact;}
    public static boolean supportedDuration(int duration){return duration==DURATION||duration==COMPACT_DURATION;}
    private int sourceTick(int tick){
        if(!compact)return tick;
        if(tick<0||tick>=COMPACT_DURATION)throw new IllegalArgumentException("compact clock outside bounds");
        if(tick<ENTRY)return tick;
        if(tick>=ENTRY+4*COMPACT_CYCLE)return ENTRY+4*CYCLE+tick-(ENTRY+4*COMPACT_CYCLE);
        int sequence=(tick-ENTRY)/COMPACT_CYCLE,n=(tick-ENTRY)%COMPACT_CYCLE;
        int source=n<95?n:n<180?n+190:n<275?n+190:n+380;
        return ENTRY+sequence*CYCLE+source;
    }
    private static final float[][] FOOD={{-.55f,.0125f,-.35f},{1.1f,.0125f,0},{.55f,.0125f,.35f},{-1.9f,.0125f,.25f}};
    private static final int[] ORDER={0,3,1,2};
    public record Part(Vector3f translation,Quaternionf rotation) {}
    public record Frame(Vector3f root,String phase,int item,boolean gripped,boolean stored,
                        Vector3f hand,Vector3f food,float upright,List<Integer> collectedItems,Map<String,Part> parts) {}
    private final Map<String,Quaternionf> previous=new HashMap<>();
    public Frame sample(int tick) {
        return sample(tick,null);
    }
    public Frame sample(int tick,Vector3f reachedRoot) {
        tick=sourceTick(tick);
        if(tick<0||tick>=DURATION)throw new IllegalArgumentException("approach rig clock outside bounds");
        int sequence=Math.max(0,Math.min(3,(tick-ENTRY)/CYCLE)),index=ORDER[sequence];
        int n=tick<ENTRY?-1:tick>=ENTRY+4*CYCLE?CYCLE:((tick-ENTRY)%CYCLE);
        Vector3f bagRoot=new Vector3f(-.8f,0,GroceryBagGeometry.CENTER_Z-.1f),pickRoot=new Vector3f(FOOD[index][0]-.65f,0,FOOD[index][2]-.6f);
        Vector3f from=sequence==0?new Vector3f(0,0,-.4f):new Vector3f(bagRoot);
        Vector3f[] approach=compact?direct(from,pickRoot):approach(index,from,pickRoot),carrying=compact?direct(pickRoot,bagRoot):carrying(index,pickRoot,bagRoot);
        Vector3f root=n<0?from:n<WALK?walkRoot(approach,n):n<370?pickRoot:n<655?walkRoot(carrying,n-370):bagRoot;
        if(reachedRoot!=null)root=new Vector3f(reachedRoot);
        float squat=n<WALK?0:n<315?smooth((n-285)/29f):n<345?1:n<370?1-smooth((n-345)/24f):n<655?0:n<680?.9f*smooth((n-655)/24f):n<720?.9f:.9f*(1-smooth((n-720)/19f));
        if(n>=CYCLE)squat=0;
        float upper=(float)Math.acos((.25-.1375)/.375)*squat,lower=(float)Math.PI/2*squat;
        float support=.375f*(float)Math.cos(lower)+.1375f*(float)Math.sin(lower);
        float hip=support+.375f*(float)Math.cos(upper),lean=(float)Math.toRadians(45)*squat;
        boolean walking=n>=0&&n<WALK||n>=370&&n<655;
        int walkElapsed=n<WALK?n:n-370,stride=walking?walkElapsed%GroundedStrideRig.LENGTH:0;
        Vector3f[] path=n<WALK?approach:carrying;
        int segment=walking?walkElapsed/GroundedStrideRig.LENGTH:0;
        if(walking)hip=GroundedStrideRig.hip(stride);
        Map<String,Part> parts=new LinkedHashMap<>();
        parts.put("body",part(new Vector3f(0,hip,0),new Quaternionf().rotateX(lean)));
        parts.put("head",part(new Vector3f(0,hip+.75f*(float)Math.cos(lean),.75f*(float)Math.sin(lean)),new Quaternionf().rotateX((float)Math.toRadians(10)*squat)));
        Vector3f selected=null;
        for(boolean left:new boolean[]{true,false}) {
            String side=left?"l":"r";float sign=left?-1:1;
            parts.put("leg_"+side,part(new Vector3f(sign*.125f,hip,0),new Quaternionf().rotateX(-upper)));
            parts.put("shin_"+side,part(new Vector3f(sign*.125f,support,.375f*(float)Math.sin(upper)),new Quaternionf().rotateX(lower)));
            if(walking) {
                var leg=GroundedStrideRig.leg(root,path[segment],path[segment+1],stride,0,left,previous.getOrDefault("shin_"+side,new Quaternionf()));
                parts.put("leg_"+side,part(leg.hip(),leg.upper()));parts.put("shin_"+side,part(leg.knee(),leg.lower()));
                parts.put("foot_"+side,part(new Vector3f(leg.ankle()).sub(root).add(0,-GroundedStrideRig.ankleLift(stride),0),new Quaternionf()));
            }else{
                var shin=parts.get("shin_"+side);
                parts.put("foot_"+side,part(new Quaternionf(shin.rotation()).transform(new Vector3f(0,-.375f,0)).add(shin.translation()),new Quaternionf(shin.rotation())));
            }
            previous.put("shin_"+side,new Quaternionf(parts.get("shin_"+side).rotation()));
            Vector3f shoulder=new Vector3f(sign*.375f,hip+.6875f*(float)Math.cos(lean),.6875f*(float)Math.sin(lean));
            Vector3f rest=new Vector3f(sign*.5f,shoulder.y-.70f,shoulder.z+.08f);
            if(squat>.7f)rest.y=Math.max(.22f,rest.y);
            if(tick<ENTRY)rest=mix(new Vector3f(sign*.375f,shoulder.y-.75f,shoulder.z),rest,tick/19f);
            if(tick>=ENTRY+4*CYCLE)rest=mix(rest,new Vector3f(sign*.375f,shoulder.y-.75f,shoulder.z),(tick-(ENTRY+4*CYCLE))/19f);
            Vector3f hand=new Vector3f(rest);
            if(!left&&n>=315&&n<CYCLE) {
                Vector3f contact=new Vector3f(FOOD[index]).sub(root).add(0,.17f,0),lift=new Vector3f(contact).add(0,.2f,0),carry=new Vector3f(.55f,.94f,.22f);
                Vector3f entry=GroceryBagGeometry.storedFood(index);entry.y=.72f;entry.sub(root);
                Vector3f outside=new Vector3f(-.4f,.72f,GroceryBagGeometry.storedFood(index).z).sub(root);
                if(n<330)hand=mix(rest,contact,(n-315)/14f);
                else if(n<345)hand=mix(contact,lift,(n-330)/14f);
                else if(n<370)hand=mix(lift,carry,(n-345)/24f);
                else if(n<655)hand=carry;
                else if(n<680)hand=mix(carry,entry,(n-655)/24f);
                else if(n<700)hand=entry;
                else if(n<720)hand=mix(entry,outside,(n-700)/19f);
                else if(n<740)hand=outside;
                else hand=mix(outside,rest,(n-740)/9f);
            }
            Vector3f elbow;
            try{elbow=elbow(shoulder,hand,sign,0);}catch(IllegalArgumentException e){throw new IllegalArgumentException("tick="+tick+" n="+n+" side="+side+" shoulder="+shoulder+" hand="+hand+": "+e.getMessage(),e);}
            parts.put("arm_"+side,part(shoulder,bone("arm_"+side,shoulder,elbow)));
            parts.put("forearm_"+side,part(elbow,bone("forearm_"+side,elbow,hand)));
            if(!left)selected=hand;
        }
        boolean gripped=n>=330&&n<GroceryBagGeometry.RELEASE_TICK,stored=n>=GroceryBagGeometry.SETTLED_TICK;
        Vector3f food=gripped?new Vector3f(selected).add(root).add(0,-GroceryPickupMotion.PALM_OFFSET,0):n>=GroceryBagGeometry.RELEASE_TICK?GroceryBagGeometry.depositedFood(index,n-GroceryBagGeometry.RELEASE_TICK):new Vector3f(FOOD[index]);
        String phase=n<0?"entry":n<WALK?"approach":n<315?"crouch":n<330?"reach":n<345?"lift":n<370?"rise-held":n<655?"carry":n<680?"bag-approach":n<690?"deposit":n<700?"withdraw-up":n<720?"withdraw-out":n<740?"rise-empty":n<CYCLE?"return-hand":"exit";
        List<Integer> collected=new ArrayList<>();for(int i=0;i<sequence;i++)collected.add(ORDER[i]);if(stored)collected.add(index);
        return new Frame(root,phase,index,gripped,stored,new Vector3f(selected).add(root),food,smooth((n-345)/24f),List.copyOf(collected),parts);
    }
    public static Vector3f plannedRoot(int tick,int duration){return duration==COMPACT_DURATION?new GroceryApproachRig(true).compactRoot(tick):plannedRoot(tick);}
    private Vector3f compactRoot(int tick){
        int source=sourceTick(tick),sequence=Math.max(0,Math.min(3,(source-ENTRY)/CYCLE)),index=ORDER[sequence];
        int n=source<ENTRY?-1:source>=ENTRY+4*CYCLE?CYCLE:(source-ENTRY)%CYCLE;
        Vector3f bag=p(-.8f,GroceryBagGeometry.CENTER_Z-.1f),pick=p(FOOD[index][0]-.65f,FOOD[index][2]-.6f),from=sequence==0?p(0,-.4f):new Vector3f(bag);
        return n<0?from:n<95?walkRoot(direct(from,pick),n):n<370?pick:n<465?walkRoot(direct(pick,bag),n-370):bag;
    }
    public static int localTick(int item,int elapsed,int duration){return duration==COMPACT_DURATION?localTick(item,new GroceryApproachRig(true).sourceTick(elapsed)):localTick(item,elapsed);}
    private static Vector3f[] direct(Vector3f from,Vector3f to){return new Vector3f[]{from,to};}
    public static Vector3f plannedRoot(int tick){
        if(tick<0||tick>=DURATION)throw new IllegalArgumentException("pickup root clock outside bounds");
        int sequence=Math.max(0,Math.min(3,(tick-ENTRY)/CYCLE)),index=ORDER[sequence];
        int n=tick<ENTRY?-1:tick>=ENTRY+4*CYCLE?CYCLE:(tick-ENTRY)%CYCLE;
        Vector3f bag=p(-.8f,GroceryBagGeometry.CENTER_Z-.1f),pick=p(FOOD[index][0]-.65f,FOOD[index][2]-.6f),from=sequence==0?p(0,-.4f):new Vector3f(bag);
        return n<0?from:n<WALK?walkRoot(approach(index,from,pick),n):n<370?pick:n<655?walkRoot(carrying(index,pick,bag),n-370):bag;
    }
    public static int localTick(int item,int elapsed){for(int sequence=0;sequence<ORDER.length;sequence++)if(ORDER[sequence]==item)return elapsed-ENTRY-sequence*CYCLE;throw new IllegalArgumentException("unregistered food");}
    public static float uprightAt(int local){return smooth((local-345)/24f);}
    private static Vector3f p(float x,float z){return new Vector3f(x,0,z);}
    private static Vector3f[] approach(int index,Vector3f from,Vector3f to){
        return switch(index){
            case 0->new Vector3f[]{from,p(0,-.7f),p(-.8f,-.7f),to};
            case 1->new Vector3f[]{from,p(-.8f,-.6f),p(-.2f,-.6f),to};
            case 2->new Vector3f[]{from,p(-.8f,-.25f),p(-.45f,-.25f),to};
            case 3->new Vector3f[]{from,p(-1.3f,-.35f),p(-1.9f,-.35f),to};
            default->throw new IllegalArgumentException("unregistered grocery");
        };
    }
    private static Vector3f[] carrying(int index,Vector3f from,Vector3f to){
        if(index==3)return new Vector3f[]{from,new Vector3f(from).lerp(to,1/3f),new Vector3f(from).lerp(to,2/3f),to};
        if(index==1)return new Vector3f[]{from,p(-.8f,-.6f),p(-.8f,-.15f),to};
        if(index==2)return new Vector3f[]{from,p(-.8f,-.25f),p(-.8f,(from.z+to.z)/2),to};
        return new Vector3f[]{from,p(-1.3f,from.z),p(-1.3f,to.z),to};
    }
    private static Vector3f walkRoot(Vector3f[] path,int n){int segment=n/GroundedStrideRig.LENGTH;return GroundedStrideRig.rootAt(path[segment],path[segment+1],n%GroundedStrideRig.LENGTH,0);}
    private Quaternionf bone(String name,Vector3f a,Vector3f b) {
        Vector3f y=new Vector3f(a).sub(b).normalize();Quaternionf old=previous.getOrDefault(name,new Quaternionf());
        Quaternionf q=new Quaternionf().rotationTo(new Quaternionf(old).transform(new Vector3f(0,1,0)),y).mul(old).normalize();
        Vector3f target=new Vector3f(1,0,0).sub(new Vector3f(y).mul(y.x));
        if(target.lengthSquared()>.02f) {
            target.normalize();Vector3f x=new Quaternionf(q).transform(new Vector3f(1,0,0));
            float roll=(float)Math.atan2(y.dot(new Vector3f(x).cross(target)),x.dot(target));
            roll=Math.max(-(float)Math.toRadians(8),Math.min((float)Math.toRadians(8),roll));
            q=new Quaternionf().fromAxisAngleRad(y,roll).mul(q).normalize();
        }
        previous.put(name,new Quaternionf(q));return q;
    }
    private static Vector3f elbow(Vector3f shoulder,Vector3f hand,float sign,float upward) {
        Vector3f d=new Vector3f(hand).sub(shoulder);float length=d.length();
        if(!Float.isFinite(length)||length<.01f||length>.75001f)throw new IllegalArgumentException("approach rig exceeds original arm reach: "+length);
        d.div(length);Vector3f pole=new Vector3f(sign*(1-upward),upward,0);pole.sub(new Vector3f(d).mul(pole.dot(d)));
        if(pole.lengthSquared()<.01f)throw new IllegalArgumentException("lateral elbow pole singular");
        float r=(float)Math.sqrt(Math.max(0,.375*.375-length*length/4));
        return new Vector3f(shoulder).add(hand).mul(.5f).add(pole.normalize().mul(r));
    }
    private static Part part(Vector3f v,Quaternionf q){return new Part(v,q);}
    private static float smooth(float t){t=Math.max(0,Math.min(1,t));return t*t*(3-2*t);}
    private static Vector3f mix(Vector3f a,Vector3f b,float t){return new Vector3f(a).lerp(b,smooth(t));}
}
