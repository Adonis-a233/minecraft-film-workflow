package dev.mcfilm.cinematicbridge.mixin;

import dev.mcfilm.cinematicbridge.core.FovState;
import net.minecraft.client.render.GameRenderer;
import net.minecraft.client.render.Camera;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;

@Mixin(GameRenderer.class)
public abstract class GameRendererMixin {
    @Inject(method="getFov",at=@At("RETURN"),cancellable=true)
    private void mcfilmOptics(Camera camera,float tickDelta,boolean changingFov,CallbackInfoReturnable<Double> callback) {
        Double value=FovState.rendered();
        if (value!=null) callback.setReturnValue(value);
    }
}
