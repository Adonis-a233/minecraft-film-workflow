package dev.mcfilm.cinematicbridge.mixin;
import dev.mcfilm.cinematicbridge.actor.FallenPoses;
import net.minecraft.entity.player.PlayerEntity;
import net.minecraft.entity.EntityPose;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;
/** Preserve the tracked fallen pose; use no bed and do not alter coordinates. */
@Mixin(PlayerEntity.class)
public abstract class ActorFallenPoseMixin {
 @Inject(method="updatePose",at=@At("HEAD"),cancellable=true)
 private void mcfilm$keepFallen(CallbackInfo ci){
  PlayerEntity actor=(PlayerEntity)(Object)this;
  if(!actor.getWorld().isClient && FallenPoses.contains(actor.getUuid())){
   actor.setPose(EntityPose.SLEEPING); ci.cancel();
  }
 }
}
