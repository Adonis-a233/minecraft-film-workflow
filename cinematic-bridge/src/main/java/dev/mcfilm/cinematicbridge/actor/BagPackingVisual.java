package dev.mcfilm.cinematicbridge.actor;

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

/** Two owned vanilla props; fixed geometry; both reclaimed with the actor. */
final class BagPackingVisual {
    private DisplayEntity.ItemDisplayEntity bag,book;
    private float progress,handError,bagHandError;
    private boolean stored,standing;
    private AffineTransformation lastBookTransform;
    private final PackingArmPose armPose=new PackingArmPose();
    private BagPackingMotion.Point hand(float p){return standing?StandingPackingMotion.hand(p):BagPackingMotion.hand(p);}
    private BagPackingMotion.Point bag(float p){return standing?StandingPackingMotion.bag(p):BagPackingMotion.bag(p);}
    private BagPackingMotion.Point book(float p){return standing?StandingPackingMotion.book(p):BagPackingMotion.book(p);}
    static BagPackingVisual prepare(ServerWorld world,ServerPlayerEntity player,String take,boolean standing){
        var p=new BagPackingVisual();p.standing=standing;
        try {p.bag=spawn(world,player,Items.BUNDLE,p.bag(0),.4f,false,take);p.book=spawn(world,player,Items.BOOK,p.book(0),.4f,true,take);return p;}
        catch(Throwable error){p.remove();throw error;}
    }
    private static Vec3d worldPoint(ServerPlayerEntity player,BagPackingMotion.Point point){Vector3f v=new Vector3f(point.x(),point.y(),point.z());new Quaternionf().rotateY((float)Math.toRadians(-player.getYaw())).transform(v);return player.getPos().add(v.x,v.y,v.z);}
    private static DisplayEntity.ItemDisplayEntity spawn(ServerWorld world,ServerPlayerEntity player,net.minecraft.item.Item item,BagPackingMotion.Point point,float scale,boolean flat,String take){
        var e=new DisplayEntity.ItemDisplayEntity(EntityType.ITEM_DISPLAY,world);e.setItemStack(new ItemStack(item));e.setTransformationMode(ModelTransformationMode.NONE);e.setPosition(worldPoint(player,point));e.setYaw(player.getYaw());e.setViewRange(1.5f);e.setDisplayWidth(1);e.setDisplayHeight(1);e.setTeleportDuration(1);e.setInterpolationDuration(1);e.addCommandTag("mcfilm_actor_visual");e.addCommandTag("mcfilm_"+take);e.setTransformation(new AffineTransformation(new Vector3f(),flat?new Quaternionf().rotateX((float)Math.PI/2):new Quaternionf(),new Vector3f(scale),new Quaternionf()));if(!world.spawnEntity(e))throw new IllegalStateException("owned packing prop spawn refused");return e;
    }
    Map<String,AffineTransformation> update(ServerPlayerEntity player,float p,Vector3f shoulder){
        if(bag.isRemoved()||book.isRemoved())throw new IllegalStateException("owned packing prop disappeared");
        var target=hand(p);Vector3f hand=new Vector3f(target.x(),target.y(),target.z()),direction=new Vector3f(hand).sub(shoulder);float distance=direction.length();
        if(distance>.75001f||distance<.01f)throw new IllegalStateException("packing hand outside two .375-block arm segments");
        var pose=armPose.sample(shoulder,hand,standing);Vector3f elbow=pose.elbow();
        var bagCenter=bag(p);bag.setPosition(worldPoint(player,bagCenter));
        var center=book(p);book.setPosition(worldPoint(player,center));float turn=Math.min(1,Math.max(0,(p-.60f)/.12f));
        var bookTransform=new AffineTransformation(new Vector3f(),new Quaternionf().rotateX((float)Math.PI/2*(1-turn)),new Vector3f(.4f),new Quaternionf());
        if(lastBookTransform==null||!lastBookTransform.getMatrix().equals(bookTransform.getMatrix())){book.setTransformation(bookTransform);book.setStartInterpolation(0);lastBookTransform=bookTransform;}
        boolean hide=BagPackingMotion.stored(p);if(hide!=stored)book.setItemStack(hide?ItemStack.EMPTY:new ItemStack(Items.BOOK));stored=hide;progress=p;
        Vector3f actual=new Vector3f(0,-.375f,0);var lower=new AffineTransformation(elbow,pose.lower(),new Vector3f(1),new Quaternionf());lower.getMatrix().transformPosition(actual);handError=p>=.18f&&!stored?actual.distance(new Vector3f(center.x(),center.y(),center.z())):0;
        if(handError>.001f)throw new IllegalStateException("packing hand missed book center: "+handError);
        bagHandError=p>=.72f&&p<.92f?actual.distance(new Vector3f(bagCenter.x(),bagCenter.y(),bagCenter.z())):0;
        if(bagHandError>.001f)throw new IllegalStateException("packing hand missed bag center: "+bagHandError);
        return Map.of("arm_l",new AffineTransformation(shoulder,pose.upper(),new Vector3f(1),new Quaternionf()),"forearm_l",lower);
    }
    Map<String,Object> proof(){var out=new java.util.LinkedHashMap<String,Object>();out.put("bag_uuid",bag.getUuidAsString());out.put("book_uuid",book.getUuidAsString());out.put("bag_item","minecraft:bundle");out.put("book_item","minecraft:book");out.put("standing",standing);out.put("progress",(double)progress);out.put("stored",stored);out.put("book_visible",!stored);out.put("book_world_center",point(book.getPos()));out.put("bag_world_center",point(bag.getPos()));out.put("hand_book_error",(double)handError);out.put("hand_bag_error",(double)bagHandError);out.put("bag_on_floor",progress>=1);return out;}
    private static Map<String,Object> point(Vec3d p){return Map.of("x",p.x,"y",p.y,"z",p.z);}
    void remove(){if(bag!=null)bag.discard();if(book!=null)book.discard();}
}
