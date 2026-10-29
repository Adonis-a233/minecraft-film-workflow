package dev.mcfilm.cinematicbridge;
import dev.mcfilm.cinematicbridge.actor.GroceryApproachRig;
import dev.mcfilm.cinematicbridge.actor.GroceryBagGeometry;
import dev.mcfilm.cinematicbridge.json.MiniJson;
import org.joml.Vector3f;
import java.nio.file.*;
import java.util.*;
public final class GroceryApproachRigTests {
    public static void main(String[] args) throws Exception {
        for(int item=0;item<4;item++) {
            Vector3f before=null;
            for(int elapsed=0;elapsed<=200;elapsed++) {
                var food=GroceryBagGeometry.depositedFood(item,elapsed);
                if(elapsed==0&&Math.abs(food.y-GroceryBagGeometry.RELEASE_FOOD_Y)>1e-7)throw new AssertionError("release height discontinuity");
                if(before!=null&&food.y>before.y+1e-7)throw new AssertionError("released food rises");
                if(food.y<.2f-1e-7)throw new AssertionError("food passes bag floor");
                if(elapsed>=5&&food.distance(GroceryBagGeometry.storedFood(item))>1e-7)throw new AssertionError("stored food jitters after contact");
                before=food;
            }
            for(int other=item+1;other<4;other++)if(Math.abs(GroceryBagGeometry.storedFood(item).z-GroceryBagGeometry.storedFood(other).z)<.025f)throw new AssertionError("stored sprites overlap");
        }
        var rig=new GroceryApproachRig();var reachedRig=new GroceryApproachRig();List<String> rows=new ArrayList<>();
        Map<String,org.joml.Quaternionf> prior=new HashMap<>();Vector3f priorRoot=null;
        for(int tick=0;tick<GroceryApproachRig.DURATION;tick++) {
            var f=rig.sample(tick);List<Map<String,Object>> parts=new ArrayList<>();
            if(f.root().distance(GroceryApproachRig.plannedRoot(tick))>1e-6)throw new AssertionError("planned route differs from pose route");
            boolean walking=f.phase().equals("approach")||f.phase().equals("carry");
            // Fully extended legs at a stride boundary have no reach reserve.
            // Exercise arrival offsets during contact; walking boundary errors
            // remain fail-closed instead of stretching either original leg.
            var reached=new Vector3f(f.root()).add(walking?0:.005f,0,walking?0:-.003f);
            var reachedFrame=reachedRig.sample(tick,reached);
            if(reachedFrame.root().distance(reached)>1e-7)throw new AssertionError("actual root ignored");
            int local=GroceryApproachRig.localTick(f.item(),tick);
            if(local==330&&reachedFrame.food().distance(f.food())>1e-5)throw new AssertionError("contact moves floor food with arrival error");
            if(local==679&&Math.abs(reachedFrame.food().y-GroceryBagGeometry.RELEASE_FOOD_Y)>1e-5)throw new AssertionError("bag release moves with arrival error");
            for(var p:f.parts().entrySet())parts.add(Map.of("part",p.getKey(),"local_translation",v(p.getValue().translation()),"local_rotation",List.of((double)p.getValue().rotation().x,(double)p.getValue().rotation().y,(double)p.getValue().rotation().z,(double)p.getValue().rotation().w)));
            for(String side:List.of("l","r")) {
                var a=f.parts().get("arm_"+side);var b=f.parts().get("forearm_"+side);
                Vector3f endpoint=new org.joml.Quaternionf(a.rotation()).transform(new Vector3f(0,-.375f,0)).add(a.translation());
                if(endpoint.distance(b.translation())>1e-5)throw new AssertionError("disconnected elbow");
                if(Math.abs(a.translation().distance(b.translation())-.375)>1e-5)throw new AssertionError("upper arm stretched");
                if(side.equals("r")) {
                    var actual=new org.joml.Quaternionf(b.rotation()).transform(new Vector3f(0,-.375f,0)).add(b.translation()).add(f.root());
                    if(actual.distance(f.hand())>1e-5)throw new AssertionError("hand disconnected");
                }
            }
            for(var p:f.parts().entrySet()) {
                var q=p.getValue().rotation();var before=prior.put(p.getKey(),new org.joml.Quaternionf(q));
                if(before!=null&&2*Math.toDegrees(Math.acos(Math.min(1,Math.abs(before.dot(q)))))>15)throw new AssertionError("candidate joint jump tick="+tick+" part="+p.getKey()+" angle="+2*Math.toDegrees(Math.acos(Math.min(1,Math.abs(before.dot(q))))));
            }
            if(priorRoot!=null&&priorRoot.distance(f.root())>.07)throw new AssertionError("planned root jump");
            priorRoot=new Vector3f(f.root());
            if(f.gripped()&&new Vector3f(f.hand()).add(0,-.17f,0).distance(f.food())>1e-5)throw new AssertionError("food loses contact");
            if(f.stored()&&!GroceryBagGeometry.containsUprightFood(f.item(),f.food()))throw new AssertionError("food not supported in assigned bag slot");
            Map<String,Object> row=new LinkedHashMap<>();
            row.put("planned_tick",tick);row.put("cycle_ticks",GroceryApproachRig.CYCLE);row.put("upright",(double)f.upright());row.put("actor_id","CH06");row.put("x",(double)f.root().x);row.put("y",(double)f.root().y);row.put("z",(double)f.root().z);row.put("yaw",0);row.put("phase",f.phase());row.put("item",f.item());row.put("gripped",f.gripped());row.put("stored",f.stored());row.put("hand",v(f.hand()));row.put("food",v(f.food()));row.put("visual",Map.of("parts",parts));
            row.put("collected_items",f.collectedItems());
            rows.add(MiniJson.write(row));
        }
        var compact=new GroceryApproachRig(true);Vector3f compactPrior=null;
        Map<String,org.joml.Quaternionf> compactJoints=new HashMap<>();
        Set<Integer> contacts=new HashSet<>(),deposits=new HashSet<>();
        float maxSpeed=0;
        for(int tick=0;tick<GroceryApproachRig.COMPACT_DURATION;tick++){
            var f=compact.sample(tick);
            if(f.root().distance(GroceryApproachRig.plannedRoot(tick,GroceryApproachRig.COMPACT_DURATION))>1e-6)throw new AssertionError("compact planned/visual root mismatch");
            if(compactPrior!=null){maxSpeed=Math.max(maxSpeed,compactPrior.distance(f.root()));if(maxSpeed>.05)throw new AssertionError("compact root exceeds live velocity bound");}
            compactPrior=new Vector3f(f.root());
            int local=GroceryApproachRig.localTick(f.item(),tick,GroceryApproachRig.COMPACT_DURATION);
            if(local==330)contacts.add(f.item());if(local==685)deposits.add(f.item());
            for(String side:List.of("l","r")){
                var a=f.parts().get("arm_"+side);var b=f.parts().get("forearm_"+side);
                var elbow=new org.joml.Quaternionf(a.rotation()).transform(new Vector3f(0,-.375f,0)).add(a.translation());
                if(elbow.distance(b.translation())>1e-5)throw new AssertionError("compact elbow disconnected");
                var knee=f.parts().get("shin_"+side);
                if(Math.abs(knee.translation().distance(f.parts().get("leg_"+side).translation())-.375)>.0001)throw new AssertionError("compact leg stretch");
            }
            for(var part:f.parts().entrySet()){
                var q=part.getValue().rotation();var before=compactJoints.put(part.getKey(),new org.joml.Quaternionf(q));
                if(before!=null&&2*Math.toDegrees(Math.acos(Math.min(1,Math.abs(before.dot(q)))))>15)throw new AssertionError("compact joint jump "+tick+" "+part.getKey());
            }
            if(f.gripped()&&new Vector3f(f.hand()).add(0,-.17f,0).distance(f.food())>1e-5)throw new AssertionError("compact loses hand contact");
            if(f.stored()&&!GroceryBagGeometry.containsUprightFood(f.item(),f.food()))throw new AssertionError("compact food unsupported");
        }
        if(contacts.size()!=4||deposits.size()!=4)throw new AssertionError("compact skipped a necessary item");
        System.out.println("Compact:1520 frames; four unique contacts/deposits; max root blocks/tick="+maxSpeed+"; live/visual acceptance pending");
        if(args.length==1)Files.write(Path.of(args[0]),rows);
        System.out.println("GroceryApproachRigTests:"+GroceryApproachRig.DURATION+" complete candidate frames; connected original arms; actual mesh/gait/live acceptance pending");
    }
    private static List<Double> v(Vector3f p){return List.of((double)p.x,(double)p.y,(double)p.z);}
}
