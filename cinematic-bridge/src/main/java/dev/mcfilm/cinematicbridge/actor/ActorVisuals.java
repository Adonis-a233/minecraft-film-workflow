package dev.mcfilm.cinematicbridge.actor;

import dev.mcfilm.cinematicbridge.json.MiniJson;
import net.minecraft.component.DataComponentTypes;
import net.minecraft.component.type.CustomModelDataComponent;
import net.minecraft.entity.EntityType;
import net.minecraft.entity.decoration.DisplayEntity;
import net.minecraft.item.ItemStack;
import net.minecraft.item.Items;
import net.minecraft.server.network.ServerPlayerEntity;
import net.minecraft.server.world.ServerWorld;
import net.minecraft.client.render.model.json.ModelTransformationMode;
import net.minecraft.util.math.AffineTransformation;
import org.joml.Quaternionf;
import org.joml.Vector3f;
import java.nio.file.Files;
import java.nio.file.Path;
import java.io.IOException;
import java.util.*;

/** Typed, bounded visuals for seven registered models. No command/NBT execution. */
public final class ActorVisuals {
    public record GroceryRelease(net.minecraft.util.math.Vec3d center,net.minecraft.util.math.Vec3d opening,Quaternionf rotation) {}
    public GroceryRelease releaseGroceryBag(ServerPlayerEntity player) {
        Binding b=bindings.get(player.getUuid());
        if(b==null||!b.ref.equals("classmate:elder")||b.groceryBagReleased)throw new IllegalStateException("one registered elder bag release required");
        var tx=b.transforms.get("forearm_r");
        var center=new Vector3f(-.046875f,-.6275f,.015625f);
        var opening=new Vector3f(-.046875f,-.3875f,.015625f);
        tx.getMatrix().transformPosition(center);tx.getMatrix().transformPosition(opening);
        var yaw=new Quaternionf().rotateY((float)Math.toRadians(-player.getYaw()));
        yaw.transform(center);yaw.transform(opening);
        var item=new ItemStack(Items.STICK);item.set(DataComponentTypes.CUSTOM_MODEL_DATA,new CustomModelDataComponent(72445));
        b.parts.get("forearm_r").setItemStack(item);b.groceryBagReleased=true;
        return new GroceryRelease(player.getPos().add(center.x,center.y,center.z),player.getPos().add(opening.x,opening.y,opening.z),yaw.mul(new Quaternionf(tx.getLeftRotation())));
    }
    public static final Set<String> ROLES=Set.of("a","zhou","teacher","chen","elder","filmer","safety");
    private final Path registryPath;
    private Map<String,Object> roles;
    private final Map<UUID,Binding> bindings=new HashMap<>();
    public ActorVisuals(Path workspace){registryPath=workspace.resolve("assets/actors/classmate-20261004/visual-binding-v10.json");}
    public void validate(String ref) throws IOException {
        if(ref==null)return;
        if(!ref.startsWith("classmate:") || !ROLES.contains(ref.substring(10)))throw new IllegalArgumentException("unregistered actor model");
        if(roles==null){
            Map<String,Object> doc=object(MiniJson.parse(Files.readString(registryPath)));
            if(((Number)doc.get("schema_version")).intValue()!=1)throw new IllegalArgumentException("visual registry version mismatch");
            roles=object(doc.get("roles"));
        }
        Map<String,Object> role=object(roles.get(ref.substring(10)));List<?> parts=(List<?>)role.get("parts");
        if(parts.size()!=(ref.equals("classmate:filmer")?12:10))throw new IllegalArgumentException("registered model part count mismatch");
        for(Object p:parts){int id=((Number)object(p).get("custom_model_data")).intValue();if(id<72000||id>72609)throw new IllegalArgumentException("unregistered item model");}
        for(Object raw:object(role.get("poses")).values())for(Object rawPart:object(raw).values()){
            Map<String,Object> part=object(rawPart);
            vector(part,"translation",3,4);vector(part,"scale",3,3);vector(part,"left_rotation",4,1);vector(part,"right_rotation",4,1);
        }
    }
    public void bind(ServerWorld world,ServerPlayerEntity player,String ref,String takeId) throws IOException {
        remove(player);
        if(ref==null){player.setInvisible(false);return;}
        validate(ref);
        Map<String,Object> role=object(roles.get(ref.substring(10)));
        Binding b=new Binding(player,ref,object(role.get("poses")));
        try{
            for(Object raw:(List<?>)role.get("parts")){
                Map<String,Object> part=object(raw);
                var display=new DisplayEntity.ItemDisplayEntity(EntityType.ITEM_DISPLAY,world);
                ItemStack item=new ItemStack(Items.STICK);
                item.set(DataComponentTypes.CUSTOM_MODEL_DATA,new CustomModelDataComponent(((Number)part.get("custom_model_data")).intValue()));
                display.setItemStack(item);display.setTransformationMode(ModelTransformationMode.NONE);
                display.setDisplayWidth(2);display.setDisplayHeight(3);display.setViewRange(1.5f);
                display.setShadowRadius(part.get("part").equals("body")?0.25f:0.0f);
                display.setTeleportDuration(1);display.setInterpolationDuration(2);
                display.addCommandTag("mcfilm_actor_visual");display.addCommandTag("mcfilm_"+takeId);
                display.setPosition(player.getPos());display.setYaw(player.getYaw());
                String name=(String)part.get("part");
                AffineTransformation initial=transform(object(object(b.poses.get("stand")).get(name)));
                display.setTransformation(initial);
                if(!world.spawnEntity(display))throw new IllegalStateException("actor visual spawn refused");
                b.parts.put(name,display);
                b.transforms.put(name,initial);
            }
            bindings.put(player.getUuid(),b);player.setInvisible(true);
        }catch(Throwable error){for(var e:b.parts.values())e.discard();throw error;}
    }
    public void update(ServerPlayerEntity player,String action,int tick,int elapsed,int duration){
        Binding b=bindings.get(player.getUuid());if(b==null)return;
        boolean puttingAway=action.equals("phone_putaway")||action.equals("phone_putaway_sit");
        float putProgress=puttingAway?PhonePutAwayMotion.progress(elapsed,duration):0;
        b.putAwayProof=puttingAway?Map.of("progress",(double)putProgress,"lowering",(double)PhonePutAwayMotion.lowering(putProgress),"phone_visible",PhonePutAwayMotion.visible(putProgress),"seated",action.endsWith("_sit")):null;
        boolean phone=(puttingAway&&PhonePutAwayMotion.visible(putProgress))||action.equals("pickup_coat")||action.equals("hold_coat")||action.equals("phone") || action.equals("phone_sit") || action.equals("phone_call") || action.equals("phone_call_sit") || action.equals("phone_stop");
        int variant=(action.equals("phone_call") || action.equals("phone_call_sit"))?20:(phone?10:0);
        if(b.phoneVariant==null || b.phoneVariant!=variant){
            String role=b.ref.substring(10);
            int base=switch(role){case "a"->72003;case "zhou"->72103;case "chen"->72303;case "filmer"->72503;case "safety"->72603;default->-1;};
            if(base>=0){
                ItemStack item=new ItemStack(Items.STICK);
                item.set(DataComponentTypes.CUSTOM_MODEL_DATA,new CustomModelDataComponent(base+variant));
                b.parts.get("forearm_l").setItemStack(item);
            }
            b.phoneVisible=phone;b.phoneVariant=variant;
        }
        String pose=switch(action){case "pickup_coat","hold_coat"->"phone";case "phone_putaway_sit","pack_bag_sit"->"sit";case "phone","phone_sit","phone_call","phone_call_sit","sit","explain","reach","down"->action;case "fall_down","rise_supported"->"ground_sit";case "support_actor"->"support_low";case "pickup_groceries"->"pickup_crouch";case "hold_item"->"explain";case "swing_arm"->"reach";default->"stand";};
        b.supportProof=null;
        float progress=Math.min(1f,Math.max(0f,elapsed/(float)Math.max(1,duration-1)));
        if(elapsed==0&&Set.of("idle","walk_to","look_at","reach","phone","phone_sit","phone_call","phone_call_sit").contains(action)){
            b.contactReleaseFrom=new HashMap<>(b.transforms);b.contactReleaseTick=tick;
        }
        if(!action.equals("support_actor")&&!action.equals("push_actor"))b.supportProof=null;
        b.phoneStopProof=null;
        Map<String,AffineTransformation> stopTransforms=action.equals("phone_stop")?phoneStop(b,progress):null;
        if(action.equals("phone_place_sit")){placePhone(b,progress);return;}
        b.riseProgress=action.equals("rise_supported")?progress*progress*(3-2*progress):(pose.equals("ground_sit")?0:1);
        if(action.equals("fall_down"))b.riseProgress=1-FallMotion.progress(elapsed);
        if(action.equals("support_actor")||action.equals("push_actor")){
            for(var e:b.parts.values()){e.setPosition(player.getPos());e.setYaw(player.getYaw());e.setPitch(0);}
            return; // Apply the final contact pose once, after the target updates.
        }
        boolean walking=action.equals("walk_to")&&player.getVelocity().horizontalLengthSquared()>0.00001;
        Map<String,AffineTransformation> actionTransforms=new HashMap<>();
        boolean packingAction=action.equals("pack_bag_sit")||action.equals("pack_bag_stand");
        boolean coatAction=action.equals("pickup_coat")||action.equals("hold_coat");
        if(packingAction){
            if(b.packing==null)throw new IllegalStateException("packing props not prepared");
            float phase=action.equals("pack_bag_stand")?StandingPackingMotion.progress(elapsed,duration):BagPackingMotion.progress(elapsed,duration);
            var transforms=b.packing.update(player,phase,v3(object(object(b.poses.get(action.equals("pack_bag_stand")?"stand":"sit")).get("arm_l")),"translation"));
            if(phase>0&&phase<1)actionTransforms.putAll(transforms);
        }
        if(coatAction){
            if(b.coat==null)throw new IllegalStateException("coat prop not prepared");
            float phase=action.equals("hold_coat")?1:CoatPickupMotion.progress(elapsed,duration);
            actionTransforms.putAll(b.coat.update(player,phase,v3(object(object(b.poses.get("stand")).get("arm_r")),"translation")));
        }
        if(action.equals("pickup_groceries"))actionTransforms.putAll(groceryPickupTransforms(b,elapsed,duration));
        Map<String,Object> chosen=object(b.poses.get(pose));
        for(var entry:b.parts.entrySet()){
            String name=entry.getKey();var e=entry.getValue();
            if(e.isRemoved())throw new IllegalStateException("owned model part disappeared");
            e.setPosition(player.getPos());e.setYaw(player.getYaw());e.setPitch(0);
            e.setInterpolationDuration(actionTransforms.containsKey(name)?1:2);
            Map<String,Object> data=object(chosen.get(name));
            AffineTransformation tx=transform(data);
            if(stopTransforms!=null)tx=stopTransforms.get(name);
            if(puttingAway){
                String from=action.endsWith("_sit")?"phone_sit":"phone";
                String to=action.endsWith("_sit")?"sit":"stand";
                tx=blend(object(object(b.poses.get(from)).get(name)),object(object(b.poses.get(to)).get(name)),PhonePutAwayMotion.lowering(putProgress));
            }
            if(action.equals("rise_supported"))tx=blend(data,object(object(b.poses.get("stand")).get(name)),b.riseProgress);
            if(action.equals("fall_down"))tx=blend(object(object(b.poses.get("stand")).get(name)),data,FallMotion.progress(elapsed));
            if(walking){
                Map<String,Object> walk=object(object(b.poses.get("walk")).get(name));
                float wave=(float)Math.sin(tick*0.55);
                Vector3f start=v3(data,"translation"),end=v3(walk,"translation");
                Vector3f position=start.add(end.sub(new Vector3f(start)).mul(wave));
                Quaternionf rotation=q4(data,"left_rotation").slerp(q4(walk,"left_rotation"),Math.abs(wave));
                if(wave<0)rotation.conjugate();
                tx=new AffineTransformation(position,rotation,v3(data,"scale"),q4(data,"right_rotation"));
            }
            // Minecraft forcibly transmits start_interpolation even when its
            // value is unchanged. Resetting it on every idle tick prevents the
            // client (and ReplayMod) from completing a static pose transition.
            if(actionTransforms.containsKey(name))tx=actionTransforms.get(name);
            // Blend ordinary pose entries and contact withdrawals over 13 ticks,
            // keeping the elbow joined
            // to the original .375-block upper arm throughout the withdrawal.
            if(b.contactReleaseFrom!=null&&tick-b.contactReleaseTick<=13&&(name.startsWith("arm_")||name.startsWith("forearm_"))){
                float u=Math.min(1,(tick-b.contactReleaseTick)/13f);u=u*u*(3-2*u);
                tx=mix(b.contactReleaseFrom.get(name),tx,u);
                if(name.startsWith("forearm_")){
                    var upper=b.transforms.get("arm_"+name.substring(8));
                    var elbow=new Vector3f(0,-.375f,0);upper.getMatrix().transformPosition(elbow);
                    tx=new AffineTransformation(elbow,tx.getLeftRotation(),tx.getScale(),tx.getRightRotation());
                }
            }
            AffineTransformation previous=b.transforms.get(name);
            if(previous==null || !previous.getMatrix().equals(tx.getMatrix())){
                e.setTransformation(tx);e.setStartInterpolation(0);
                b.transforms.put(name,tx);
            }
        }
        b.pose=puttingAway?"phone-put-away":action.equals("phone_stop")?"phone-stop":(action.equals("rise_supported")?"supported-rise":(walking?"walk-cycle":pose));
        if(packingAction)b.pose=action.equals("pack_bag_stand")?"pack-bag-standing":"pack-bag-seated";
        if(coatAction)b.pose=action;
    }
    public void updateMouth(ServerPlayerEntity player,int frame){
        if(frame<0||frame>2)throw new IllegalArgumentException("mouth frame outside0..2");
        Binding b=bindings.get(player.getUuid());if(b==null){if(frame!=0)throw new IllegalStateException("mouth requires model");return;}
        if(b.mouthFrame==frame)return;
        ItemStack item=new ItemStack(Items.STICK);item.set(DataComponentTypes.CUSTOM_MODEL_DATA,new CustomModelDataComponent(MouthModels.modelData(b.ref.substring(10),frame)));
        b.parts.get("head").setItemStack(item);b.mouthFrame=frame;
    }
    public Map<String,Object> proof(ServerPlayerEntity player){
        Binding b=bindings.get(player.getUuid());if(b==null)return Map.of("backend","vanilla-player");
        List<Map<String,Object>> parts=new ArrayList<>();for(var row:b.parts.entrySet()){
            var e=row.getValue();var tx=b.transforms.get(row.getKey());var t=tx.getTranslation();var q=tx.getLeftRotation();
            parts.add(Map.of("part",row.getKey(),"uuid",e.getUuidAsString(),"x",e.getX(),"y",e.getY(),"z",e.getZ(),"local_translation",List.of((double)t.x,(double)t.y,(double)t.z),"local_rotation",List.of((double)q.x,(double)q.y,(double)q.z,(double)q.w)));
        }
        Map<String,Object> proof=new LinkedHashMap<>(Map.of("backend","registered-item-display","model_ref",b.ref,"pose",b.pose,"parts",parts,"phone_visible",Boolean.TRUE.equals(b.phoneVisible)));
        proof.put("rise_progress",(double)b.riseProgress);
        proof.put("carried_grocery_bag_released",b.groceryBagReleased);
        proof.put("mouth_frame",b.mouthFrame);
        if(b.supportProof!=null)proof.put(b.pose.equals("push-contact")?"push_contact":"support_contact",b.supportProof);
        if(b.phoneStopProof!=null)proof.put("phone_stop",b.phoneStopProof);
        if(b.putAwayProof!=null)proof.put("phone_putaway",b.putAwayProof);
        if(b.groceryFrame!=null){var f=b.groceryFrame;proof.put("grocery_approach",Map.of("phase",f.phase(),"item",f.item(),"gripped",f.gripped(),"stored",f.stored(),"upright",(double)f.upright(),"reached_root",List.of((double)f.root().x,(double)f.root().y,(double)f.root().z)));}
        if(b.packing!=null)proof.put("bag_packing",b.packing.proof());
        if(b.coat!=null)proof.put("coat_pickup",b.coat.proof());
        if(b.tablePhone!=null){Map<String,Object> tableProof=new LinkedHashMap<>();tableProof.put("uuid",b.tablePhone.getUuidAsString());tableProof.put("phone_world_center",List.of(b.currentPhonePos.x,b.currentPhonePos.y,b.currentPhonePos.z));tableProof.put("placed",b.phonePlaced);tableProof.put("progress",(double)b.placeProgress);tableProof.put("table_block",List.of(b.tableBlock.getX(),b.tableBlock.getY(),b.tableBlock.getZ()));tableProof.put("placement_target",List.of(b.phoneTarget.x,b.phoneTarget.y,b.phoneTarget.z));tableProof.put("target_bottom_y",b.phoneTarget.y-.025625);tableProof.put("release_solver_error",(double)b.placeHandError);proof.put("table_phone",tableProof);}
        return proof;
    }
    public void beginPhonePlacement(ServerWorld world,ServerPlayerEntity player,ActorPlan.Point target,String takeId){
        Binding b=bindings.get(player.getUuid());
        if(b==null||!b.ref.equals("classmate:chen")||b.tablePhone!=null)throw new IllegalStateException("one seated worker phone placement per actor binding");
        var block=net.minecraft.util.math.BlockPos.ofFloored(target.x(),target.y()-.04,target.z());
        var state=world.getBlockState(block);
        if(!state.isOf(net.minecraft.block.Blocks.SPRUCE_SLAB)||state.get(net.minecraft.state.property.Properties.SLAB_TYPE)!=net.minecraft.block.enums.SlabType.TOP)throw new IllegalStateException("phone table must be registered vanilla spruce top slab");
        if(Math.abs(target.y()-.025625-(block.getY()+1))>.001||target.x()-.1<block.getX()||target.x()+.1>block.getX()+1||target.z()-.1625<block.getZ()||target.z()+.1625>block.getZ()+1)throw new IllegalStateException("phone footprint must rest entirely on declared table surface");
        Vector3f local=new Vector3f((float)(target.x()-player.getX()),(float)(target.y()-player.getY()),(float)(target.z()-player.getZ()));new Quaternionf().rotateY((float)Math.toRadians(player.getYaw())).transform(local);
        Vector3f shoulder=v3(object(object(b.poses.get("phone_call_sit")).get("arm_l")),"translation");
        if(shoulder.distance(local)>.749f)throw new IllegalStateException("phone table exceeds original seated arm reach");
        b.phoneTarget=new net.minecraft.util.math.Vec3d(target.x(),target.y(),target.z());b.tableBlock=block;b.localPhoneTarget=local;
        var e=new DisplayEntity.ItemDisplayEntity(EntityType.ITEM_DISPLAY,world);ItemStack item=new ItemStack(Items.STICK);item.set(DataComponentTypes.CUSTOM_MODEL_DATA,new CustomModelDataComponent(72700));e.setItemStack(item);e.setTransformationMode(ModelTransformationMode.NONE);e.setDisplayWidth(2);e.setDisplayHeight(2);e.setViewRange(2);e.setInterpolationDuration(1);e.setTeleportDuration(1);e.addCommandTag("mcfilm_phone_prop");e.addCommandTag("mcfilm_"+takeId);e.setPosition(player.getPos());b.tablePhone=e;placePhone(b,0);
        if(!world.spawnEntity(e))throw new IllegalStateException("owned table phone spawn failed");
    }
    private static void placePhone(Binding b,float progress){
        if(b.tablePhone==null||b.tablePhone.isRemoved())throw new IllegalStateException("owned tabletop phone absent");
        Map<String,Object> call=object(b.poses.get("phone_call_sit")),sit=object(b.poses.get("sit"));
        AffineTransformation original=transform(object(call.get("forearm_l")));
        Vector3f startCenter=new Vector3f(0,-.5875f,-.093125f);original.getMatrix().transformPosition(startCenter);
        float reach=Math.min(1,progress/.6f),smooth=reach*reach*(3-2*reach),withdraw=Math.max(0,(progress-.7f)/.3f);
        Vector3f center=new Vector3f(startCenter).lerp(b.localPhoneTarget,smooth);
        Vector3f worldCenter=new Vector3f(center);new Quaternionf().rotateY((float)Math.toRadians(-b.player.getYaw())).transform(worldCenter);b.currentPhonePos=b.player.getPos().add(worldCenter.x,worldCenter.y,worldCenter.z);
        Quaternionf phoneRotation=new Quaternionf(original.getLeftRotation()).slerp(new Quaternionf().rotateX((float)Math.PI/2),smooth);
        b.tablePhone.setPosition(b.player.getPos());b.tablePhone.setYaw(b.player.getYaw());b.tablePhone.setTransformation(new AffineTransformation(center,phoneRotation,new Vector3f(1),new Quaternionf()));b.tablePhone.setStartInterpolation(0);
        Vector3f shoulder=v3(object(call.get("arm_l")),"translation"),dir=new Vector3f(b.localPhoneTarget).sub(shoulder).normalize();float distance=shoulder.distance(b.localPhoneTarget);
        Vector3f bend=new Vector3f(0,-1,0).sub(new Vector3f(dir).mul(dir.dot(new Vector3f(0,-1,0))));if(bend.lengthSquared()<.001f)throw new IllegalStateException("degenerate seated phone reach");bend.normalize().mul((float)Math.sqrt(.375*.375-distance*distance/4));Vector3f elbow=new Vector3f(shoulder).lerp(b.localPhoneTarget,.5f).add(bend);
        Map<String,AffineTransformation> release=new HashMap<>();release.put("arm_l",new AffineTransformation(shoulder,new Quaternionf().rotationTo(new Vector3f(0,-1,0),new Vector3f(elbow).sub(shoulder).normalize()),new Vector3f(1),new Quaternionf()));release.put("forearm_l",new AffineTransformation(elbow,new Quaternionf().rotationTo(new Vector3f(0,-1,0),new Vector3f(b.localPhoneTarget).sub(elbow).normalize()),new Vector3f(1),new Quaternionf()));
        for(var entry:b.parts.entrySet()){
            String part=entry.getKey();var e=entry.getValue();e.setPosition(b.player.getPos());e.setYaw(b.player.getYaw());e.setPitch(0);
            AffineTransformation rest=transform(object(sit.get(part))),tx=rest;
            if(release.containsKey(part))tx=progress<.6f?mix(transform(object(call.get(part))),release.get(part),smooth):mix(release.get(part),rest,withdraw);
            apply(b,part,tx);
        }
        Vector3f hand=new Vector3f(0,-.375f,0);release.get("forearm_l").getMatrix().transformPosition(hand);b.placeHandError=hand.distance(b.localPhoneTarget);if(b.placeHandError>.001f)throw new IllegalStateException("phone release hand contact failed");b.phonePlaced=progress>=.6f;b.placeProgress=progress;b.pose="phone-place-sit";
    }
    private static Map<String,AffineTransformation> phoneStop(Binding b,float progress){
        if(!b.ref.equals("classmate:filmer"))throw new IllegalStateException("phone stop currently supports the registered filmer only");
        Map<String,Object> phone=object(b.poses.get("phone")),stand=object(b.poses.get("stand"));
        Map<String,AffineTransformation> tap=new HashMap<>(),result=new HashMap<>();
        for(String part:b.parts.keySet())tap.put(part,transform(object(phone.get(part))));
        Vector3f leftShoulder=v3(object(phone.get("arm_l")),"translation");
        Vector3f leftDirection=new Vector3f(.75f,-.64f,.20f).normalize();
        Vector3f leftElbow=new Vector3f(leftShoulder).add(new Vector3f(leftDirection).mul(.375f));
        tap.put("arm_l",new AffineTransformation(leftShoulder,new Quaternionf().rotationTo(new Vector3f(0,-1,0),leftDirection),new Vector3f(1),new Quaternionf()));
        tap.put("forearm_l",new AffineTransformation(leftElbow,q4(object(phone.get("forearm_l")),"left_rotation"),new Vector3f(1),new Quaternionf()));
        // Source phone screen north face: model coordinates[8,4.7,4.79], centered at[8,8,8]/16.
        Vector3f screen=new Vector3f(0,-.20625f,-.200625f);tap.get("forearm_l").getMatrix().transformPosition(screen);
        Vector3f rightShoulder=v3(object(phone.get("arm_r")),"translation");
        float distance=rightShoulder.distance(screen);
        if(distance>.749f||distance<.025f)throw new IllegalStateException("phone screen beyond original arm reach");
        Vector3f direction=new Vector3f(screen).sub(rightShoulder).normalize();
        Vector3f bend=new Vector3f(0,-1,0).sub(new Vector3f(direction).mul(direction.dot(new Vector3f(0,-1,0))));
        if(bend.lengthSquared()<.001f)throw new IllegalStateException("degenerate phone tap geometry");
        bend.normalize().mul((float)Math.sqrt(.375*.375-distance*distance/4));
        Vector3f rightElbow=new Vector3f(rightShoulder).lerp(screen,.5f).add(bend);
        if(Math.abs(rightShoulder.distance(rightElbow)-.375f)>.001f||Math.abs(rightElbow.distance(screen)-.375f)>.001f)throw new IllegalStateException("phone tap arm length mismatch");
        Quaternionf upper=new Quaternionf().rotationTo(new Vector3f(0,-1,0),new Vector3f(rightElbow).sub(rightShoulder).normalize());
        Quaternionf lower=new Quaternionf().rotationTo(new Vector3f(0,-1,0),new Vector3f(screen).sub(rightElbow).normalize());
        tap.put("arm_r",new AffineTransformation(rightShoulder,upper,new Vector3f(1),new Quaternionf()));
        tap.put("forearm_r",new AffineTransformation(rightElbow,lower,new Vector3f(1),new Quaternionf()));
        float move=Math.min(1,progress/.2f),lowering=Math.max(0,(progress-.4f)/.6f);
        for(String part:b.parts.keySet()){
            AffineTransformation from=transform(object(phone.get(part))),to=tap.get(part);
            result.put(part,progress<.2f?mix(from,to,move):mix(to,transform(object(stand.get(part))),lowering));
        }
        Vector3f hand=new Vector3f(0,-.375f,0);result.get("forearm_r").getMatrix().transformPosition(hand);
        Vector3f target=new Vector3f(0,-.20625f,-.200625f);result.get("forearm_l").getMatrix().transformPosition(target);
        boolean touching=progress>=.2f&&progress<=.4f;
        if(touching&&hand.distance(target)>.001f)throw new IllegalStateException("phone tap contact failed");
        b.phoneStopProof=Map.of("phase",progress<.2f?"reach":(touching?"tap":"lower"),"progress",(double)progress,"lower_progress",(double)lowering,"tap_contact",touching,"hand_local",List.of((double)hand.x,(double)hand.y,(double)hand.z),"screen_local",List.of((double)target.x,(double)target.y,(double)target.z),"error",(double)hand.distance(target),"upper_length",(double)rightShoulder.distance(rightElbow),"forearm_length",(double)rightElbow.distance(screen));
        return result;
    }
    private static AffineTransformation mix(AffineTransformation a,AffineTransformation b,float t){return new AffineTransformation(new Vector3f(a.getTranslation()).lerp(b.getTranslation(),t),new Quaternionf(a.getLeftRotation()).slerp(b.getLeftRotation(),t),new Vector3f(a.getScale()).lerp(b.getScale(),t),new Quaternionf(a.getRightRotation()).slerp(b.getRightRotation(),t));}
    public void support(ServerPlayerEntity helper,ServerPlayerEntity elder,String actorRef){
        contact(helper,elder,actorRef,false);
    }
    public void push(ServerPlayerEntity helper,ServerPlayerEntity elder,String actorRef){
        contact(helper,elder,actorRef,true);
    }
    private void contact(ServerPlayerEntity helper,ServerPlayerEntity elder,String actorRef,boolean push){
        Binding h=bindings.get(helper.getUuid()),e=bindings.get(elder.getUuid());
        if(h==null||e==null||!e.ref.equals("classmate:elder")||helper.getPos().distanceTo(elder.getPos())>1.5||Math.abs(helper.getY()-elder.getY())>.1)throw new IllegalStateException("support requires nearby same-floor registered actors");
        if(push&&(!h.ref.equals("classmate:chen")||e.riseProgress!=1||!e.pose.equals("stand")))throw new IllegalStateException("push contact requires registered worker and standing elder");
        for(String part:h.parts.keySet()){h.parts.get(part).setYaw(helper.getYaw());if(!part.startsWith("arm_")&&!part.startsWith("forearm_"))apply(h,part,blend(object(object(h.poses.get("support_low")).get(part)),object(object(h.poses.get("stand")).get(part)),e.riseProgress));}
        // Compute arm bases without transmitting an intermediate low pose.
        Map<String,AffineTransformation> baseArms=new HashMap<>();
        for(String part:List.of("arm_l","arm_r","forearm_l","forearm_r"))baseArms.put(part,blend(object(object(h.poses.get("support_low")).get(part)),object(object(h.poses.get("stand")).get(part)),e.riseProgress));
        Vector3f relative=new Vector3f((float)(helper.getX()-elder.getX()),0,(float)(helper.getZ()-elder.getZ()));
        new Quaternionf().rotateY((float)Math.toRadians(elder.getYaw())).transform(relative);
        String targetPart=relative.x<0?"arm_l":"arm_r";
        Vector3f contact=new Vector3f(targetPart.equals("arm_l")?-.13f:.13f,-.16f,0);
        e.transforms.get(targetPart).getMatrix().transformPosition(contact);
        new Quaternionf().rotateY((float)Math.toRadians(-elder.getYaw())).transform(contact);
        var worldTarget=elder.getPos().add(contact.x,contact.y,contact.z);
        Vector3f local=new Vector3f((float)(worldTarget.x-helper.getX()),(float)(worldTarget.y-helper.getY()),(float)(worldTarget.z-helper.getZ()));
        new Quaternionf().rotateY((float)Math.toRadians(helper.getYaw())).transform(local);
        String arm="arm_l";Vector3f shoulder=baseArms.get(arm).getTranslation();
        Vector3f other=baseArms.get("arm_r").getTranslation();
        if(other.distance(local)<shoulder.distance(local)){arm="arm_r";shoulder=other;}
        float distance=shoulder.distance(local);
        if(distance>.749f||distance<.025f)throw new IllegalStateException("support hand target is beyond two original .375-block arm segments: "+distance);
        Vector3f direction=new Vector3f(local).sub(shoulder).normalize();
        Vector3f bend=new Vector3f(0,-1,0).sub(new Vector3f(direction).mul(direction.dot(new Vector3f(0,-1,0))));
        if(bend.lengthSquared()<.001f)bend.set(0,0,1).sub(new Vector3f(direction).mul(direction.z));
        bend.normalize().mul((float)Math.sqrt(.375*.375-distance*distance/4));
        Vector3f elbow=new Vector3f(shoulder).lerp(local,.5f).add(bend);
        Quaternionf upper=new Quaternionf().rotationTo(new Vector3f(0,-1,0),new Vector3f(elbow).sub(shoulder).normalize());
        Quaternionf lower=new Quaternionf().rotationTo(new Vector3f(0,-1,0),new Vector3f(local).sub(elbow).normalize());
        String unused=arm.equals("arm_l")?"arm_r":"arm_l";apply(h,unused,baseArms.get(unused));
        String unusedForearm=unused.equals("arm_l")?"forearm_l":"forearm_r";apply(h,unusedForearm,baseArms.get(unusedForearm));
        apply(h,arm,new AffineTransformation(shoulder,upper,new Vector3f(1),new Quaternionf()));
        String forearm=arm.equals("arm_l")?"forearm_l":"forearm_r";
        apply(h,forearm,new AffineTransformation(elbow,lower,new Vector3f(1),new Quaternionf()));
        Vector3f hand=new Vector3f(0,-.375f,0);h.transforms.get(forearm).getMatrix().transformPosition(hand);
        new Quaternionf().rotateY((float)Math.toRadians(-helper.getYaw())).transform(hand);
        var actual=helper.getPos().add(hand.x,hand.y,hand.z);double error=actual.distanceTo(worldTarget);
        if(error>.001)throw new IllegalStateException("support contact anchor failed");
        h.supportProof=Map.of("actor_ref",actorRef,"elder_part",targetPart,"helper_part",forearm,"hand",point(actual),"target",point(worldTarget),"error",error,"upper_length",(double)shoulder.distance(elbow),"forearm_length",(double)elbow.distance(local));h.pose=push?"push-contact":"support-contact";
    }
    public void prepareGroceryPickup(ServerPlayerEntity player,ActorPlan.Point center,int duration){
        Binding b=bindings.get(player.getUuid());
        if(b==null||!b.ref.equals("classmate:filmer"))throw new IllegalStateException("registered filmer required");
        b.groceryRig=new GroceryApproachRig(duration==GroceryApproachRig.COMPACT_DURATION);b.groceryCenter=center;b.groceryFrame=null;b.groceryRightHand=true;
    }
    private static Map<String,AffineTransformation> groceryPickupTransforms(Binding b,int elapsed,int duration){
        if(!GroceryApproachRig.supportedDuration(duration)||b.groceryRig==null||b.groceryCenter==null)
            throw new IllegalStateException("prepared approach pickup requires a supported route clock");
        Vector3f reached=new Vector3f((float)(b.player.getX()-b.groceryCenter.x()),(float)(b.player.getY()-b.groceryCenter.y()),(float)(b.player.getZ()-b.groceryCenter.z()));
        b.groceryFrame=b.groceryRig.sample(elapsed,reached);
        Map<String,AffineTransformation> result=new HashMap<>();
        for(var p:b.groceryFrame.parts().entrySet())result.put(p.getKey(),new AffineTransformation(p.getValue().translation(),p.getValue().rotation(),new Vector3f(1),new Quaternionf()));
        return result;
    }
    private static AffineTransformation local(Vector3f translation,float angle){return new AffineTransformation(translation,new Quaternionf().rotateX(angle),new Vector3f(1),new Quaternionf());}
    private static Map<String,Object> point(net.minecraft.util.math.Vec3d p){return Map.of("x",p.x,"y",p.y,"z",p.z);}
    private static AffineTransformation blend(Map<String,Object> from,Map<String,Object> to,float t){return new AffineTransformation(v3(from,"translation").lerp(v3(to,"translation"),t),q4(from,"left_rotation").slerp(q4(to,"left_rotation"),t),v3(from,"scale").lerp(v3(to,"scale"),t),q4(from,"right_rotation").slerp(q4(to,"right_rotation"),t));}
    private static void apply(Binding b,String part,AffineTransformation tx){var old=b.transforms.get(part);if(old==null||!old.getMatrix().equals(tx.getMatrix())){var entity=b.parts.get(part);entity.setTransformation(tx);entity.setStartInterpolation(0);b.transforms.put(part,tx);}}
    public net.minecraft.util.math.Vec3d pickupHandPosition(ServerPlayerEntity player){
        Binding b=bindings.get(player.getUuid());
        if(b==null)throw new IllegalStateException("registered hand required for pickup");
        Vector3f tip=new Vector3f(0,-.375f,0);
        b.transforms.get(b.groceryRightHand?"forearm_r":"forearm_l").getMatrix().transformPosition(tip);
        new Quaternionf().rotateY((float)Math.toRadians(-player.getYaw())).transform(tip);
        return player.getPos().add(tip.x,tip.y,tip.z);
    }
    public void prepareBagPacking(ServerWorld world,ServerPlayerEntity player,String takeId,boolean standing){Binding b=bindings.get(player.getUuid());if(b==null||!(standing?b.ref.equals("classmate:chen"):Set.of("classmate:a","classmate:zhou").contains(b.ref))||b.packing!=null)throw new IllegalStateException("one matching registered packing binding required");b.packing=BagPackingVisual.prepare(world,player,takeId,standing);}
    public void remove(UUID id){Binding b=bindings.remove(id);if(b!=null){for(var e:b.parts.values())e.discard();if(b.tablePhone!=null)b.tablePhone.discard();if(b.packing!=null)b.packing.remove();if(b.coat!=null)b.coat.remove();}}
    public void prepareCoatPickup(ServerWorld world,ServerPlayerEntity player,ActorPlan.Point target,String take){Binding b=bindings.get(player.getUuid());if(b==null||!b.ref.equals("classmate:a")||b.coat!=null)throw new IllegalStateException("one registered A coat pickup required");b.coat=CoatPickupVisual.prepare(world,player,target,take);}
    public void remove(ServerPlayerEntity player){remove(player.getUuid());player.setInvisible(false);}
    private static AffineTransformation transform(Map<String,Object> data){return new AffineTransformation(v3(data,"translation"),q4(data,"left_rotation"),v3(data,"scale"),q4(data,"right_rotation"));}
    private static Vector3f v3(Map<String,Object> d,String key){List<?> a=(List<?>)d.get(key);return new Vector3f(f(a,0),f(a,1),f(a,2));}
    private static Quaternionf q4(Map<String,Object> d,String key){List<?> a=(List<?>)d.get(key);return new Quaternionf(f(a,0),f(a,1),f(a,2),f(a,3));}
    private static float f(List<?> a,int i){return ((Number)a.get(i)).floatValue();}
    private static void vector(Map<String,Object> d,String key,int size,float limit){List<?> a=(List<?>)d.get(key);if(a.size()!=size)throw new IllegalArgumentException("invalid model transform");for(Object v:a){double n=((Number)v).doubleValue();if(!Double.isFinite(n)||Math.abs(n)>limit)throw new IllegalArgumentException("unbounded model transform");}}
    @SuppressWarnings("unchecked")private static Map<String,Object> object(Object v){if(!(v instanceof Map<?,?>))throw new IllegalArgumentException("invalid visual registry object");return (Map<String,Object>)v;}
    private static class Binding{final ServerPlayerEntity player;final String ref;final Map<String,Object> poses;final Map<String,DisplayEntity.ItemDisplayEntity> parts=new LinkedHashMap<>();final Map<String,AffineTransformation> transforms=new HashMap<>();boolean groceryRightHand,groceryBagReleased;Map<String,AffineTransformation> contactReleaseFrom;int contactReleaseTick=-100;GroceryApproachRig groceryRig;GroceryApproachRig.Frame groceryFrame;ActorPlan.Point groceryCenter;int mouthFrame=0;Boolean phoneVisible;Integer phoneVariant;float riseProgress;Map<String,Object> supportProof;Map<String,Object> phoneStopProof;Map<String,Object> putAwayProof;BagPackingVisual packing;CoatPickupVisual coat;DisplayEntity.ItemDisplayEntity tablePhone;net.minecraft.util.math.Vec3d phoneTarget,currentPhonePos;net.minecraft.util.math.BlockPos tableBlock;Vector3f localPhoneTarget;boolean phonePlaced;float placeProgress,placeHandError;String pose="stand";Binding(ServerPlayerEntity p,String r,Map<String,Object> poses){player=p;ref=r;this.poses=poses;}}
}
