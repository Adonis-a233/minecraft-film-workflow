package dev.mcfilm.cinematicbridge.actor;

import net.minecraft.client.render.model.json.ModelTransformationMode;
import net.minecraft.entity.EntityType;
import net.minecraft.entity.decoration.DisplayEntity;
import net.minecraft.item.ItemStack;
import net.minecraft.item.Items;
import net.minecraft.component.DataComponentTypes;
import net.minecraft.component.type.CustomModelDataComponent;
import net.minecraft.server.world.ServerWorld;
import net.minecraft.util.math.AffineTransformation;
import net.minecraft.util.math.BlockPos;
import net.minecraft.util.math.Vec3d;
import org.joml.Quaternionf;
import org.joml.Vector3f;
import java.util.*;

/** Four fixed vanilla groceries; bounded scatter and explicit owned pickup. */
final class GroceryProps {
    private static final double[][] OFFSETS={{-.55,-.35},{1.1,0},{.55,.35},{-1.9,.25}};
    private DisplayEntity.ItemDisplayEntity bag;
    private final List<Float> rotations=new ArrayList<>();
    private final List<DisplayEntity.ItemDisplayEntity> items=new ArrayList<>();
    private final List<Vec3d> resting=new ArrayList<>();
    private final boolean[] stored=new boolean[4];
    private final List<String> refs=List.of("minecraft:apple","minecraft:bread","minecraft:carrot","minecraft:potato");
    final ActorPlan.Point center;
    final int scatteredAt;
    int pickupAt=-1,lastTick=-1,pickupDuration;
    String collector;
    private Vec3d hand;
    private final ActorVisuals.GroceryRelease release;
    private boolean bagLanded;
    GroceryProps(ServerWorld world,ActorPlan.Point center,int tick,String takeId,ActorVisuals.GroceryRelease release){
        this.release=release;
        double releaseHeight=release.center().y-center.y();
        if(releaseHeight<GroceryBagGeometry.CENTER_Y-.001||releaseHeight>2)throw new IllegalArgumentException("bag release cannot clear supporting floor");
        this.center=center;scatteredAt=tick;
        var types=List.of(Items.APPLE,Items.BREAD,Items.CARROT,Items.POTATO);
        List<double[]> footprints=new ArrayList<>(Arrays.asList(OFFSETS));footprints.add(new double[]{0,GroceryBagGeometry.CENTER_Z});
        for(var offset:footprints){
            BlockPos support=BlockPos.ofFloored(center.x()+offset[0],center.y()-1,center.z()+offset[1]);
            if(!world.shouldTickEntity(support)||world.getBlockState(support).getCollisionShape(world,support).isEmpty())
                throw new IllegalStateException("groceries require a loaded supporting floor");
            for(int y=(int)Math.floor(center.y());y<=(int)Math.ceil(center.y()+1.3);y++)
                if(!world.getBlockState(new BlockPos(support.getX(),y,support.getZ())).isAir())
                    throw new IllegalStateException("grocery scatter column obstructed");
        }
        try{
            bag=new DisplayEntity.ItemDisplayEntity(EntityType.ITEM_DISPLAY,world);
            var bagStack=new ItemStack(Items.STICK);bagStack.set(DataComponentTypes.CUSTOM_MODEL_DATA,new CustomModelDataComponent(72802));
            bag.setItemStack(bagStack);bag.setTransformationMode(ModelTransformationMode.NONE);
            bag.setTransformation(new AffineTransformation(new Vector3f(),release.rotation(),new Vector3f(1),new Quaternionf()));
            bag.setPosition(release.center());bag.setTeleportDuration(1);bag.setInterpolationDuration(1);bag.setDisplayWidth(1);bag.setDisplayHeight(1);bag.setViewRange(2);
            bag.addCommandTag("mcfilm_grocery_prop");bag.addCommandTag("mcfilm_"+takeId);
            if(!world.spawnEntity(bag))throw new IllegalStateException("grocery bag spawn failed");
            for(int i=0;i<4;i++){
                var display=new DisplayEntity.ItemDisplayEntity(EntityType.ITEM_DISPLAY,world);
                display.setItemStack(new ItemStack(types.get(i)));display.setTransformationMode(ModelTransformationMode.NONE);
                display.setTransformation(new AffineTransformation(new Vector3f(),new Quaternionf().rotateX((float)-Math.PI/2),new Vector3f(.4f),new Quaternionf()));
                display.setDisplayWidth(1);display.setDisplayHeight(1);display.setViewRange(2);
                display.setTeleportDuration(1);display.addCommandTag("mcfilm_grocery_prop");display.addCommandTag("mcfilm_"+takeId);
                display.setPosition(release.opening());
                if(!world.spawnEntity(display))throw new IllegalStateException("grocery display spawn failed");
                items.add(display);rotations.add((float)-Math.PI/2);resting.add(new Vec3d(center.x()+OFFSETS[i][0],center.y()+.0125,center.z()+OFFSETS[i][1]));
            }
        }catch(Throwable error){discard();throw error;}
    }
    void startPickup(String actor,int tick,Vec3d hand,int duration){
        if(pickupAt>=0)throw new IllegalStateException("groceries already have an owned collector");
        collector=actor;pickupAt=tick;pickupDuration=duration;this.hand=hand;
    }
    void updateHand(String actor,Vec3d hand){if(Objects.equals(actor,collector))this.hand=hand;}
    void tick(int tick){
        if(tick==lastTick)return;lastTick=tick;
        if(!bagLanded){
            double elapsed=tick-scatteredAt;
            var target=new Vec3d(center.x(),center.y()+GroceryBagGeometry.CENTER_Y,center.z()+GroceryBagGeometry.CENTER_Z);
            double landing=Math.sqrt(Math.max(0,2*(release.center().y-target.y)/GroceryScatterMotion.GRAVITY));
            double t=landing==0?1:Math.min(1,elapsed/landing);
            var pos=new Vec3d(release.center().x+(target.x-release.center().x)*t,Math.max(target.y,release.center().y-.5*GroceryScatterMotion.GRAVITY*elapsed*elapsed),release.center().z+(target.z-release.center().z)*t);
            if(!bag.getPos().equals(pos))bag.setPosition(pos);
            bag.setTransformation(new AffineTransformation(new Vector3f(),new Quaternionf(release.rotation()).slerp(new Quaternionf(),(float)t),new Vector3f(1),new Quaternionf()));bag.setStartInterpolation(0);
            if(t>=1){
                var stack=new ItemStack(Items.STICK);stack.set(DataComponentTypes.CUSTOM_MODEL_DATA,new CustomModelDataComponent(GroceryBagGeometry.MODEL_ID));bag.setItemStack(stack);
                bag.setTransformation(new AffineTransformation(new Vector3f(),new Quaternionf(),new Vector3f(GroceryBagGeometry.SCALE),new Quaternionf()));bag.setStartInterpolation(0);bagLanded=true;
            }
        }
        for(int i=0;i<items.size();i++){
            var item=items.get(i);
            if(item.isRemoved())throw new IllegalStateException("owned grocery vanished; stored contents must remain visible");
            if(stored[i])continue;
            Vec3d pos;
            if(pickupAt<0){
                var opening=release.opening();
                var sample=GroceryScatterMotion.fromOpening(opening.x-center.x(),opening.y-center.y(),opening.z-center.z(),OFFSETS[i][0],OFFSETS[i][1],tick-scatteredAt);
                pos=new Vec3d(center.x()+sample.x(),center.y()+sample.y(),center.z()+sample.z());
            }else{
                int local=GroceryApproachRig.localTick(i,Math.min(tick-pickupAt,pickupDuration-1),pickupDuration);
                if(local>=GroceryBagGeometry.SETTLED_TICK){
                    var prior=GroceryBagGeometry.depositedFood(i,local-GroceryBagGeometry.RELEASE_TICK-1);
                    if(item.getPos().distanceTo(new Vec3d(center.x()+prior.x,center.y()+prior.y,center.z()+prior.z))>1e-5)
                        throw new IllegalStateException("owned grocery diverged from bag fall before landing");
                    var landing=GroceryBagGeometry.depositedFood(i,local-GroceryBagGeometry.RELEASE_TICK);
                    var supported=new Vec3d(center.x()+landing.x,center.y()+landing.y,center.z()+landing.z);
                    if(!item.getPos().equals(supported))item.setPosition(supported);
                    var v=item.getPos();
                    if(!GroceryBagGeometry.containsUprightFood(i,new Vector3f((float)(v.x-center.x()),(float)(v.y-center.y()),(float)(v.z-center.z()))))
                        throw new IllegalStateException("grocery cannot be stored before entering the bag volume");
                    stored[i]=true;continue;
                }
                // Before touch the prop stays on the floor. Once gripped it is
                // attached to the moving hand, with no attraction toward it.
                if(local>=GroceryBagGeometry.RELEASE_TICK){
                    var p=GroceryBagGeometry.depositedFood(i,local-GroceryBagGeometry.RELEASE_TICK);
                    pos=new Vec3d(center.x()+p.x,center.y()+p.y,center.z()+p.z);
                }else pos=local<330?resting.get(i):hand.add(0,-GroceryPickupMotion.PALM_OFFSET,0);
                float angle=(float)(-Math.PI/2*(1-GroceryApproachRig.uprightAt(local)));
                if(Float.compare(rotations.get(i),angle)!=0){
                    item.setTransformation(new AffineTransformation(new Vector3f(),new Quaternionf().rotateX(angle),new Vector3f(.4f),new Quaternionf()));
                    item.setInterpolationDuration(1);item.setStartInterpolation(0);rotations.set(i,angle);
                }
            }
            // A settled or stationary held prop must not restart display interpolation.
            if(!item.getPos().equals(pos))item.setPosition(pos);
        }
    }
    boolean complete(){return pickupAt>=0&&stored[0]&&stored[1]&&stored[2]&&stored[3];}
    Map<String,Object> proof(){
        List<Map<String,Object>> parts=new ArrayList<>();
        for(int i=0;i<items.size();i++){
            var item=items.get(i);parts.add(Map.of("uuid",item.getUuidAsString(),"item",refs.get(i),"x",item.getX(),"y",item.getY(),"z",item.getZ(),"collected",stored[i],"entity_removed",item.isRemoved()));
        }
        Map<String,Object> out=new LinkedHashMap<>();out.put("scattered_at_tick",scatteredAt);out.put("pickup_at_tick",pickupAt);out.put("collector",collector);out.put("items",parts);out.put("bag",Map.of("uuid",bag.getUuidAsString(),"x",bag.getX(),"y",bag.getY(),"z",bag.getZ(),"item","classmate:elder-grocery-bag","custom_model_data",bagLanded?GroceryBagGeometry.MODEL_ID:72802,"scale",bagLanded?(double)GroceryBagGeometry.SCALE:1.0,"temporary_flat_sprite",false));out.put("bag_landed",bagLanded);out.put("release_center",Map.of("x",release.center().x,"y",release.center().y,"z",release.center().z));out.put("release_opening",Map.of("x",release.opening().x,"y",release.opening().y,"z",release.opening().z));out.put("complete",complete());return out;
    }
    void discard(){for(var item:items)if(!item.isRemoved())item.discard();if(bag!=null&&!bag.isRemoved())bag.discard();}
}
