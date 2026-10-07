package dev.mcfilm.cinematicbridge.actor;

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
import net.minecraft.util.math.Vec3d;
import org.joml.Quaternionf;
import org.joml.Vector3f;
import java.util.Map;

/** One owned prop copied from original A clothing meshes, anchored at its collar. */
final class CoatPickupVisual {
    private final DisplayEntity.ItemDisplayEntity entity;
    private final BagPackingMotion.Point source;
    private float progress,error;
    private AffineTransformation lastTransform;
    private CoatPickupVisual(DisplayEntity.ItemDisplayEntity entity,BagPackingMotion.Point source){this.entity=entity;this.source=source;}
    static CoatPickupVisual prepare(ServerWorld world,ServerPlayerEntity player,ActorPlan.Point target,String take){
        Vector3f local=new Vector3f((float)(target.x()-player.getX()),(float)(target.y()-player.getY()),(float)(target.z()-player.getZ()));new Quaternionf().rotateY((float)Math.toRadians(player.getYaw())).transform(local);
        var e=new DisplayEntity.ItemDisplayEntity(EntityType.ITEM_DISPLAY,world);var item=new ItemStack(Items.STICK);item.set(DataComponentTypes.CUSTOM_MODEL_DATA,new CustomModelDataComponent(73000));e.setItemStack(item);e.setTransformationMode(ModelTransformationMode.NONE);e.setDisplayWidth(1);e.setDisplayHeight(1);e.setViewRange(1.5f);e.setTeleportDuration(1);e.setInterpolationDuration(1);e.setPosition(target.x(),target.y(),target.z());e.setYaw(player.getYaw());e.setTransformation(new AffineTransformation(new Vector3f(),new Quaternionf().rotateX((float)-Math.PI/2),new Vector3f(.8f),new Quaternionf()));e.addCommandTag("mcfilm_actor_visual");e.addCommandTag("mcfilm_"+take);
        if(!world.spawnEntity(e))throw new IllegalStateException("coat prop spawn refused");return new CoatPickupVisual(e,new BagPackingMotion.Point(local.x,local.y,local.z));
    }
    Map<String,AffineTransformation> update(ServerPlayerEntity player,float p,Vector3f shoulder){
        if(entity.isRemoved())throw new IllegalStateException("owned coat disappeared");
        var h=CoatPickupMotion.hand(p,source);var j=BagPackingMotion.elbow(new BagPackingMotion.Point(shoulder.x,shoulder.y,shoulder.z),h);Vector3f hand=new Vector3f(h.x(),h.y(),h.z()),elbow=new Vector3f(j.x(),j.y(),j.z());
        var upper=new AffineTransformation(shoulder,new Quaternionf().rotationTo(new Vector3f(0,-1,0),new Vector3f(elbow).sub(shoulder).normalize()),new Vector3f(1),new Quaternionf());var lower=new AffineTransformation(elbow,new Quaternionf().rotationTo(new Vector3f(0,-1,0),new Vector3f(hand).sub(elbow).normalize()),new Vector3f(1),new Quaternionf());
        var c=CoatPickupMotion.coat(p,source);Vector3f center=new Vector3f(c.x(),c.y(),c.z());new Quaternionf().rotateY((float)Math.toRadians(-player.getYaw())).transform(center);entity.setPosition(player.getPos().add(center.x,center.y,center.z));
        var tx=new AffineTransformation(new Vector3f(),new Quaternionf().rotateX((float)(-Math.PI/2*(1-CoatPickupMotion.upright(p)))),new Vector3f(.8f),new Quaternionf());
        if(lastTransform==null||!lastTransform.getMatrix().equals(tx.getMatrix())){entity.setTransformation(tx);entity.setStartInterpolation(0);lastTransform=tx;}
        Vector3f actual=new Vector3f(0,-.375f,0);lower.getMatrix().transformPosition(actual);error=CoatPickupMotion.gripped(p)?actual.distance(new Vector3f(c.x(),c.y(),c.z())):0;if(error>.001f)throw new IllegalStateException("hand missed coat collar");progress=p;
        return Map.of("arm_r",upper,"forearm_r",lower);
    }
    Map<String,Object> proof(){Vec3d p=entity.getPos();return Map.of("uuid",entity.getUuidAsString(),"model","kanjian2:prop/a_coat","custom_model_data",73000,"progress",(double)progress,"gripped",CoatPickupMotion.gripped(progress),"hand_collar_error",(double)error,"collar_world",Map.of("x",p.x,"y",p.y,"z",p.z));}
    void remove(){entity.discard();}
}
