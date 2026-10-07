package dev.mcfilm.cinematicbridge.actor;

import net.minecraft.block.Blocks;
import net.minecraft.entity.EntityType;
import net.minecraft.entity.decoration.DisplayEntity;
import net.minecraft.server.world.ServerWorld;
import net.minecraft.util.math.BlockPos;
import net.minecraft.util.math.AffineTransformation;
import org.joml.Quaternionf;
import org.joml.Vector3f;
import java.util.Map;

/** One owned vanilla wooden board: fixed dimensions, bounded column and floor. */
final class BoardProp {
    final DisplayEntity.BlockDisplayEntity display;
    final ActorPlan.Point origin;
    final double floor;
    int releasedAt = -1;
    BoardProp(ServerWorld world, ActorPlan.Point origin, double floor, String takeId) {
        this.origin=origin;this.floor=floor;
        // Check the entire1x2 footprint, including the board's wobble clearance.
        for(int x=(int)Math.floor(origin.x()-.5);x<=(int)Math.floor(origin.x()+.5);x++)
            for(int z=(int)Math.floor(origin.z()-1);z<=(int)Math.floor(origin.z()+1);z++) {
                BlockPos support=BlockPos.ofFloored(x,floor-1,z);
                if(!world.shouldTickEntity(support) || world.getBlockState(support).getCollisionShape(world,support).isEmpty())
                    throw new IllegalStateException("board footprint needs a loaded supporting floor");
                for(int y=(int)Math.floor(floor);y<=(int)Math.ceil(origin.y()+.3);y++)
                    if(!world.getBlockState(new BlockPos(x,y,z)).isAir())
                        throw new IllegalStateException("board footprint column is obstructed");
            }
        display=new DisplayEntity.BlockDisplayEntity(EntityType.BLOCK_DISPLAY,world);
        display.setBlockState(Blocks.OAK_PLANKS.getDefaultState());
        display.setDisplayWidth(3);display.setDisplayHeight(3);display.setViewRange(2);
        display.setTeleportDuration(1);display.setInterpolationDuration(1);
        display.addCommandTag("mcfilm_board_prop");display.addCommandTag("mcfilm_"+takeId);
        display.setPosition(origin.x(),origin.y(),origin.z());transform(0);
        if(!world.spawnEntity(display))throw new IllegalStateException("board spawn failed");
    }
    void release(int tick) {
        if(releasedAt>=0)throw new IllegalStateException("board was already released");
        releasedAt=tick;transform(0);
    }
    void tick(int tick) {
        if(display.isRemoved())throw new IllegalStateException("owned board vanished");
        if(releasedAt<0)transform((float)(.06*Math.sin(tick*.4)));
        else {
            int elapsed=tick-releasedAt;
            // Fixed20TPS choreography; stop at the declared floor with no damage.
            double y=Math.max(floor,origin.y()-.02*elapsed*(elapsed+1));
            display.setPosition(origin.x(),y,origin.z());
        }
    }
    private void transform(float angle) {
        display.setTransformation(new AffineTransformation(new Vector3f(-.5f,0,-1),
            new Quaternionf().rotateX(angle),new Vector3f(1,.15f,2),new Quaternionf()));
        display.setStartInterpolation(0);
    }
    Map<String,Object> proof() {
        return Map.of("uuid",display.getUuidAsString(),"x",display.getX(),"y",display.getY(),"z",display.getZ(),
            "released_at_tick",releasedAt,"floor",floor,"dimensions",java.util.List.of(1,.15,2),"material","minecraft:oak_planks");
    }
    void discard(){display.discard();}
}
