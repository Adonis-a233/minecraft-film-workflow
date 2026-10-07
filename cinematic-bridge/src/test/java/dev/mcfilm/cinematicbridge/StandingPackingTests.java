package dev.mcfilm.cinematicbridge;
import dev.mcfilm.cinematicbridge.actor.*;
import dev.mcfilm.cinematicbridge.json.MiniJson;
import java.nio.file.*;
import java.util.Map;
public final class StandingPackingTests {
    public static void main(String[] args)throws Exception {
        String valid=Files.readString(Path.of("../contracts/v3/fixtures/actor/valid-standing-packing.json"));
        ActorPlan.parse(parse(valid));
        reject(valid.replace("classmate:chen","classmate:zhou"));
        reject(valid.replace("\"action\": \"idle\"","\"action\": \"sit\""));
        reject(valid.replace("\"duration_ticks\": 160","\"duration_ticks\": 159").replace("\"start_tick\": 180","\"start_tick\": 179").replace("\"duration_ticks\": 100","\"duration_ticks\": 101"));
        var shoulder=new BagPackingMotion.Point(-.375f,1.4375f,0);
        for(int duration:new int[]{80,120,160,200}){
            var rig=new PackingArmPose();org.joml.Quaternionf upper=null,lower=null;double max=0;
            for(int t=0;t<duration;t++){
                var h=StandingPackingMotion.hand(t/(float)(duration-1));var pose=rig.sample(new org.joml.Vector3f(shoulder.x(),shoulder.y(),shoulder.z()),new org.joml.Vector3f(h.x(),h.y(),h.z()));
                if(upper!=null){max=Math.max(max,angle(upper,pose.upper()));max=Math.max(max,angle(lower,pose.lower()));}
                upper=pose.upper();lower=pose.lower();
            }
            System.out.println("Packing continuous pose duration="+duration+" max angle/tick="+max+" exit angle="+angle(lower,new org.joml.Quaternionf()));
            if(duration>=160&&(max>15||angle(lower,new org.joml.Quaternionf())>.1||angle(upper,new org.joml.Quaternionf())>.1))throw new AssertionError("continuous packing arm jump or exit discontinuity");
        }
        if(args.length==1){
            var registry=parse(Files.readString(Path.of("../assets/actors/classmate-20261004/visual-binding-v10.json")));
            var roles=(Map<String,Object>)registry.get("roles");var chen=(Map<String,Object>)roles.get("chen");var poses=(Map<String,Object>)chen.get("poses");var stand=(Map<String,Object>)poses.get("stand");
            var rig=new PackingArmPose();var rows=new java.util.ArrayList<String>();
            for(int tick=0;tick<200;tick++){
                float progress=Math.max(0,Math.min(1,(tick-20)/159f));var hand=StandingPackingMotion.hand(progress);var pose=rig.sample(new org.joml.Vector3f(shoulder.x(),shoulder.y(),shoulder.z()),new org.joml.Vector3f(hand.x(),hand.y(),hand.z()));
                var parts=new java.util.ArrayList<Map<String,Object>>();
                for(var entry:stand.entrySet()){
                    var part=(Map<String,Object>)entry.getValue();var translation=part.get("translation");var rotation=part.get("left_rotation");
                    if(tick>=20&&tick<180&&entry.getKey().equals("arm_l")){translation=vec(pose.shoulder());rotation=quat(pose.upper());}
                    if(tick>=20&&tick<180&&entry.getKey().equals("forearm_l")){translation=vec(pose.elbow());rotation=quat(pose.lower());}
                    parts.add(Map.of("part",entry.getKey(),"local_translation",translation,"local_rotation",rotation));
                }
                var bag=StandingPackingMotion.bag(progress);var book=StandingPackingMotion.book(progress);
                rows.add(MiniJson.write(Map.of("planned_tick",tick,"x",0,"y",0,"z",0,"yaw",0,"progress",(double)progress,"bag",java.util.List.of((double)bag.x(),(double)bag.y(),(double)bag.z()),"book",java.util.List.of((double)book.x(),(double)book.y(),(double)book.z()),"visual",Map.of("parts",parts))));
            }
            Files.write(Path.of(args[0]),rows);
        }
        for(int i=0;i<=1000;i++) {
            float p=i/1000f;var h=StandingPackingMotion.hand(p);var e=BagPackingMotion.elbowLateral(shoulder,h);
            if(Math.abs(dist(shoulder,e)-.375)>.00001||Math.abs(dist(e,h)-.375)>.00001)throw new AssertionError("arm length");
            var b=StandingPackingMotion.bag(p);var book=StandingPackingMotion.book(p);
            // Desk begins .3blocks ahead; a .4block prop must clear it before lowering.
            if(b.z()+.2>.30001&&b.y()-.2<.99999)throw new AssertionError("bag intersects desk");
            if(b.y()<.19999)throw new AssertionError("bag below floor");
            if(p>=.18&&!BagPackingMotion.stored(p)&&dist(book,h)>.00001)throw new AssertionError("book contact");
            if(p>=.72&&p<.92&&dist(b,h)>.00001)throw new AssertionError("bag contact");
        }
        if(!StandingPackingMotion.hand(0).equals(StandingPackingMotion.REST)||!StandingPackingMotion.hand(1).equals(StandingPackingMotion.REST))throw new AssertionError("rest continuity");
        if(dist(StandingPackingMotion.bag(1),StandingPackingMotion.FLOOR)>.00001)throw new AssertionError("floor endpoint");
        System.out.println("StandingPackingTests:4plans,1001arm/contact/desk/floor samples passed");
    }
    private static double dist(BagPackingMotion.Point a,BagPackingMotion.Point b){return Math.sqrt(Math.pow(a.x()-b.x(),2)+Math.pow(a.y()-b.y(),2)+Math.pow(a.z()-b.z(),2));}
    private static double angle(org.joml.Quaternionf a,org.joml.Quaternionf b){return 2*Math.toDegrees(Math.acos(Math.min(1,Math.abs(a.dot(b)))));}
    private static java.util.List<Double> vec(org.joml.Vector3f v){return java.util.List.of((double)v.x,(double)v.y,(double)v.z);}
    private static java.util.List<Double> quat(org.joml.Quaternionf q){return java.util.List.of((double)q.x,(double)q.y,(double)q.z,(double)q.w);}
    @SuppressWarnings("unchecked")private static Map<String,Object> parse(String s){return (Map<String,Object>)MiniJson.parse(s);}
    private static void reject(String s){try{ActorPlan.parse(parse(s));}catch(IllegalArgumentException expected){return;}throw new AssertionError("unsafe plan accepted");}
}
