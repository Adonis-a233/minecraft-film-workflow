package dev.mcfilm.cinematicbridge.actor;

import carpet.fakes.ServerPlayerInterface;
import carpet.patches.EntityPlayerMPFake;
import dev.mcfilm.cinematicbridge.CinematicBridgeLog;
import dev.mcfilm.cinematicbridge.json.MiniJson;
import dev.mcfilm.cinematicbridge.server.PersistentJournal;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.network.ServerPlayerEntity;
import net.minecraft.server.world.ServerWorld;
import net.minecraft.util.math.BlockPos;
import net.minecraft.util.math.Vec3d;
import net.minecraft.world.GameMode;
import net.minecraft.world.World;
import net.minecraft.text.Text;

import java.io.BufferedWriter;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.function.Supplier;

/** Server-tick actor runner using Carpet's action pack, never per-tick teleport. */
public final class ActorService {
    private final Path workspace;
    private ActorVisuals visuals;
    private final PersistentJournal journal;
    private final Supplier<MinecraftServer> serverProvider;
    private final Map<String, Take> takes = new HashMap<>();
    private final Map<String, UUID> owned = new HashMap<>();
    private Take active;
    private volatile java.util.function.LongSupplier replayClock;
    private final Map<String,Long> playbackOnsets = new HashMap<>();

    public synchronized void bindReplayClock(java.util.function.LongSupplier clock) {
        replayClock=clock; playbackOnsets.clear();
    }

    private static Object field(Object object,String name) throws ReflectiveOperationException {
        var field=object.getClass().getDeclaredField(name);field.setAccessible(true);return field.get(object);
    }

    private List<Map<String,Object>> playbackRows() throws ReflectiveOperationException {
        List<Map<String,Object>> rows=new ArrayList<>();
        Class<?> playing=Class.forName("com.mt1006.mocap.mocap.playing.Playing");
        for (Object scene:(List<?>)playing.getField("playedScenes").get(null)) playbackRows(scene,rows);
        return rows;
    }

    private void playbackRows(Object scene,List<Map<String,Object>> rows) throws ReflectiveOperationException {
        Object ctx=field(scene,"ctx");
        if (ctx!=null && field(ctx,"entity") instanceof net.minecraft.entity.player.PlayerEntity player) {
            Map<String,Object> row=new LinkedHashMap<>();
            row.put("player_name",player.getGameProfile().getName());row.put("uuid",player.getUuidAsString());
            row.put("x",player.getX());row.put("y",player.getY());row.put("z",player.getZ());
            row.put("yaw",(double)player.getYaw());row.put("pitch",(double)player.getPitch());
            row.put("scene_tick",field(scene,"tickCounter"));row.put("recording_ticks",field(field(scene,"recording"),"tickCount"));
            row.put("held_item",net.minecraft.registry.Registries.ITEM.getId(player.getMainHandStack().getItem()).toString());
            var skin=player.getGameProfile().getProperties().get("mocap:skin_from_file");
            if (!skin.isEmpty())row.put("skin_file",skin.iterator().next().value());
            Long onset=playbackOnsets.get(player.getUuidAsString());if(onset!=null)row.put("onset_ms",onset);
            rows.add(row);
        }
        for(Object child:(List<?>)field(scene,"subscenes"))playbackRows(child,rows);
    }

    /** Fictional Film* names use deterministic offline profiles and local PNGs. */
    public Map<String,Object> prepareOfflinePlayers(List<?> names) {
        if(names.isEmpty() || names.size()>8 || names.stream().anyMatch(n -> !(n instanceof String s) || !s.matches("Film[A-Za-z0-9_]{1,12}")))
            return rejected("offline actor names must use Film plus 1..12 safe characters");
        MinecraftServer server=serverProvider.get();if(server==null)return rejected("world is not loaded");
        java.util.concurrent.CompletableFuture<Map<String,Object>> answer=new java.util.concurrent.CompletableFuture<>();
        server.execute(() -> {
            try {
                Class<?> profiles=Class.forName("com.mt1006.mocap.utils.ProfileUtils");
                @SuppressWarnings("unchecked") Map<String,com.mojang.authlib.GameProfile> cache=
                    (Map<String,com.mojang.authlib.GameProfile>)profiles.getField("gameProfileCache").get(null);
                Map<String,Object> proof=new LinkedHashMap<>();
                for(Object raw:names) {
                    String name=(String)raw;
                    if(server.getPlayerManager().getPlayer(name)!=null)throw new IllegalArgumentException("offline playback name is already online");
                    UUID id=UUID.nameUUIDFromBytes(("OfflinePlayer:"+name).getBytes(StandardCharsets.UTF_8));
                    var previous=cache.get(name);
                    if(previous!=null && !previous.getId().equals(id))throw new IllegalArgumentException("playback profile name is already bound");
                    if(previous==null)cache.put(name,new com.mojang.authlib.GameProfile(id,name));
                    proof.put(name,id.toString());
                }
                answer.complete(result("applied",Map.of("offline_profiles",proof)));
            }catch(Throwable error){answer.complete(rejected(error.toString()));}
        });
        try{return answer.get(5,java.util.concurrent.TimeUnit.SECONDS);}
        catch(Exception error){return Map.of("status","unknown","message","offline profile preparation unproven");}
    }

    public ActorService(Path workspace, PersistentJournal journal, Supplier<MinecraftServer> serverProvider) {
        if (workspace == null || !workspace.isAbsolute() || !Files.isDirectory(workspace))
            throw new IllegalArgumentException("MINECRAFT_FILM_PROJECT_ROOT must name an existing absolute project directory");
        this.workspace = workspace.normalize();
        this.journal = journal;
        this.serverProvider = serverProvider;
    }

    public synchronized Map<String, Object> start(Map<String, Object> params, String key,
                                                   String operationId, String requestRunId) {
        MinecraftServer server = serverProvider.get();
        if (journal == null) return rejected("actor operations require the persistent journal");
        ActorPlan plan;
        try { plan = ActorPlan.parse(params); }
        catch (IllegalArgumentException invalid) { return rejected(invalid.getMessage()); }
        if (!plan.runId().equals(requestRunId)) return rejected("plan run_id must match the request run_id");
        if (server == null) return rejected("an integrated world must be loaded before an actor take");
        if (!plan.world().equals(server.getSaveProperties().getLevelName())) return rejected("world name mismatch");
        String hash = PersistentJournal.paramsHash(params);
        PersistentJournal.Record prior = journal.get(key).orElse(null);
        if (prior != null) {
            if (!prior.method.equals("actor.start_take") || !prior.paramsHash.equals(hash))
                return conflict("idempotency key is already bound to different actor parameters");
            if (prior.proof() != null) return new LinkedHashMap<>(prior.proof());
            return pending(plan.takeId(), prior.state().json(), operationId);
        }
        if (takes.containsKey(plan.takeId())) return conflict("take_id already exists in this server session");
        if (active != null || takes.values().stream().anyMatch(t -> t.state.equals("queued") || t.state.equals("running")))
            return rejected("another actor take is active");
        Path trace = workspace.resolve("work").resolve("S01-actor-20261002").resolve(plan.takeId() + ".jsonl").normalize();
        if (!trace.startsWith(workspace.resolve("work").resolve("S01-actor-20261002")) || Files.exists(trace))
            return rejected("trace path exists or escapes the actor evidence directory");
        PersistentJournal.Record record = journal.begin(key, "actor.start_take", hash);
        if (record == null) return conflict("idempotency key was accepted concurrently; query its status");
        journal.markQueued(key);
        Take take = new Take(plan, key, trace);
        takes.put(plan.takeId(), take);
        // The operation enters the tick-owned queue only after the durable ACCEPTED event.
        server.execute(() -> {
            synchronized (ActorService.this) {
                if (take.state.equals("queued")) {
                    take.ready = true;
                    if (active == null) active = take;
                }
            }
        });
        return pending(plan.takeId(), "queued", operationId);
    }

    public synchronized Map<String, Object> status(String takeId) {
        Take take = takes.get(takeId);
        if (take == null) return result("unknown", Map.of("take_id", takeId,
            "take_state", "unknown", "message", "take not present in this server process; it was not replayed"));
        return result("applied", take.snapshot());
    }

    /** Resolves only an actor created by this service, never an arbitrary player. */
    public synchronized String recordingPlayer(String actorId) {
        MinecraftServer server = serverProvider.get();
        UUID uuid = owned.get(actorId);
        ServerPlayerEntity player = server == null || uuid == null ? null : server.getPlayerManager().getPlayer(uuid);
        if (!(player instanceof EntityPlayerMPFake)) throw new IllegalArgumentException("recording actor is not owned and online");
        return player.getGameProfile().getName();
    }

    /** Authoritative, text-only player poses, captured on the server thread. */
    public Map<String,Object> inspect() {
        MinecraftServer server = serverProvider.get();
        if (server == null) return rejected("world is not loaded");
        java.util.concurrent.CompletableFuture<Map<String,Object>> answer = new java.util.concurrent.CompletableFuture<>();
        server.execute(() -> {
            List<Map<String,Object>> players = new ArrayList<>();
            for (net.minecraft.entity.Entity entity : server.getOverworld().iterateEntities()) {
                if (!(entity instanceof net.minecraft.entity.player.PlayerEntity player)) continue;
                Map<String,Object> row = new LinkedHashMap<>();
                row.put("player_name", player.getGameProfile().getName()); row.put("uuid", player.getUuid().toString());
                row.put("x", player.getX()); row.put("y", player.getY()); row.put("z", player.getZ());
                row.put("yaw", (double)player.getYaw()); row.put("pitch", (double)player.getPitch());
                row.put("held_item", net.minecraft.registry.Registries.ITEM.getId(player.getMainHandStack().getItem()).toString());
                var skin = player.getGameProfile().getProperties().get("mocap:skin_from_file");
                if (!skin.isEmpty()) row.put("skin_file", skin.iterator().next().value());
                players.add(row);
            }
            try {
                answer.complete(result("applied",Map.of("server_tick",server.getOverworld().getTime(),"players",players,"playback",playbackRows())));
            }catch(ReflectiveOperationException error){answer.complete(rejected("pinned Mocap playback inspection failed: "+error));}
        });
        try { return answer.get(5, java.util.concurrent.TimeUnit.SECONDS); }
        catch (Exception error) { return Map.of("status", "unknown", "message", "server player snapshot timed out"); }
    }

    public synchronized Map<String, Object> cancel(String takeId, String key) {
        if (journal == null) return rejected("actor cancellation requires the persistent journal");
        Take take = takes.get(takeId);
        if (take == null) return rejected("take_id is not owned by this actor service");
        if (take.state.equals("succeeded") || take.state.equals("failed") || take.state.equals("cancelled"))
            return result("applied", take.snapshot());
        String hash = PersistentJournal.paramsHash(Map.of("take_id", takeId));
        PersistentJournal.Record old = journal.get(key).orElse(null);
        if (old != null) {
            if (!old.method.equals("actor.cancel_take") || !old.paramsHash.equals(hash)) return conflict("cancel idempotency conflict");
            if (old.proof() != null) return new LinkedHashMap<>(old.proof());
            take.cancelRequested = true;
            return pending(takeId, old.state().json(), key);
        }
        if (journal.begin(key, "actor.cancel_take", hash) == null) return conflict("cancel key already exists");
        journal.markQueued(key);
        take.cancelKey = key;
        take.cancelRequested = true;
        return pending(takeId, "queued", key);
    }

    public Map<String, Object> releaseOwned(String actorId) {
        MinecraftServer server = serverProvider.get();
        if (server == null) return rejected("an integrated world must be loaded to release actors");
        java.util.concurrent.CompletableFuture<Map<String,Object>> result = new java.util.concurrent.CompletableFuture<>();
        server.execute(() -> {
            synchronized (ActorService.this) {
                try { result.complete(releaseOwnedOnServer(actorId)); }
                catch (Throwable error) { result.completeExceptionally(error); }
            }
        });
        try { return result.get(5, java.util.concurrent.TimeUnit.SECONDS); }
        catch (Exception error) { return Map.of("status", "unknown", "error_class", "operation_timeout_unknown", "message", "actor release unproven; inspect actor identity"); }
    }

    private Map<String, Object> releaseOwnedOnServer(String actorId) {
        MinecraftServer server = serverProvider.get();
        if (server == null) return rejected("an integrated world must be loaded to release actors");
        UUID uuid = owned.get(actorId);
        if (uuid == null) return rejected("actor_id is not owned by this service session");
        ServerPlayerEntity player = server.getPlayerManager().getPlayer(uuid);
        if (player == null) {
            if(visuals!=null)visuals.remove(uuid);
            FallenPoses.remove(uuid);
            owned.remove(actorId);
            return result("applied", Map.of("actor_id", actorId, "released", true, "already_absent", true));
        }
        ((ServerPlayerInterface)player).getActionPack().stopAll();
        if(visuals!=null)visuals.remove(player);
        FallenPoses.remove(uuid);
        ((EntityPlayerMPFake)player).kill(Text.literal("owned rehearsal actor released"));
        owned.remove(actorId);
        return result("applied", Map.of("actor_id", actorId, "uuid", uuid.toString(), "released", true));
    }

    /** Called on END_SERVER_TICK. No HTTP waits or filesystem creation occur here. */
    public synchronized void tick(MinecraftServer server) {
        if(replayClock!=null) {
            try {
                for(var row:playbackRows())playbackOnsets.computeIfAbsent((String)row.get("uuid"),uuid->replayClock.getAsLong());
            }catch(ReflectiveOperationException error){CinematicBridgeLog.warn("playback clock capture failed: "+error);}
        }
        if (active == null) {
            for (Take candidate : takes.values()) {
                if (candidate.ready && candidate.state.equals("queued")) { active = candidate; break; }
            }
        }
        if (active == null) return;
        try {
            if (active.cancelRequested && active.state.equals("queued") && !active.spawnRequested) {
                cancelActive(active); return;
            }
            if (active.state.equals("queued")) begin(active, server);
            if (!active.state.equals("running")) return;
            if (active.ownerServer != server || !active.plan.world().equals(server.getSaveProperties().getLevelName())
                || server.getOverworld() == null) { fail(active, "world changed during actor take"); return; }
            if (active.cancelRequested) { cancelActive(active); return; }
            if (active.tick >= active.plan.durationTicks()) { finish(active); return; }
            for (ActorRun actor : active.actors) {
                if (!runActorStep(active, actor, server.getOverworld())) return;
            }
            for(ActorRun actor:active.actors)if(actor.step.action().equals("support_actor")||actor.step.action().equals("push_actor")){
                ActorRun target=active.actors.stream().filter(a->a.plan.actorId().equals(actor.step.actorRef())).findFirst().orElseThrow();
                ((ServerPlayerInterface)actor.player).getActionPack().stopMovement().lookAt(target.player.getPos().add(0,.8,0));
                if(actor.step.action().equals("push_actor"))visuals.push(actor.player,target.player,actor.step.actorRef());
                else visuals.support(actor.player,target.player,actor.step.actorRef());
            }
            if(active.groceries!=null)active.groceries.tick(active.tick);
            for(ActorRun actor:active.actors)appendTrace(active,actor,server.getOverworld());
            active.tick++;
        } catch (Throwable error) {
            CinematicBridgeLog.warn("actor take failed: " + error);
            fail(active, "actor execution failed: " + error.getClass().getSimpleName() + ": " + error.getMessage());
        }
    }

    private void begin(Take take, MinecraftServer server) throws IOException {
        ServerWorld world = server.getOverworld();
        if (take.spawnRequested) {
            if (take.ownerServer != server) throw new IllegalStateException("server session changed while spawning");
            for (ActorPlan.Actor actor : take.plan.actors()) {
                if (take.actors.stream().anyMatch(a -> a.plan.actorId().equals(actor.actorId()))) continue;
                ServerPlayerEntity player = server.getPlayerManager().getPlayer(actor.playerName());
                if (player == null) continue;
                if (!(player instanceof EntityPlayerMPFake) || !(player instanceof ServerPlayerInterface))
                    throw new IllegalStateException("spawned actor identity is not a Carpet fake player");
                ((ServerPlayerInterface)player).getActionPack().stopAll();
                visuals.bind(world,player,actor.skinRef(),take.plan.takeId());
                if(actor.steps().stream().anyMatch(s->s.action().equals("pack_bag_sit")))visuals.prepareBagPacking(world,player,take.plan.takeId(),false);
                if(actor.steps().stream().anyMatch(s->s.action().equals("pack_bag_stand")))visuals.prepareBagPacking(world,player,take.plan.takeId(),true);
                for(var step:actor.steps())if(step.action().equals("pickup_coat"))visuals.prepareCoatPickup(world,player,step.target(),take.plan.takeId());
                take.actors.add(new ActorRun(actor, player.getUuid(), player));
                owned.put(actor.actorId(), player.getUuid());
            }
            if (take.actors.size() != take.plan.actors().size()) {
                if (++take.spawnWaitTicks > 200) throw new IllegalStateException("fake player spawn timed out");
                return;
            }
            take.state = "running";
            journal.markRunning(take.key);
            take.startedWorldTick = world.getTime();
            return;
        }
        if (!take.plan.dimension().equals(world.getRegistryKey().getValue().toString())) throw new IllegalStateException("dimension mismatch");
        for (ActorPlan.Actor actor : take.plan.actors()) {
            if(visuals==null)visuals=new ActorVisuals(workspace);
            visuals.validate(actor.skinRef());
            ServerPlayerEntity existing = server.getPlayerManager().getPlayer(actor.playerName());
            if (existing != null && (!(existing instanceof EntityPlayerMPFake)
                || !existing.getUuid().equals(owned.get(actor.actorId()))))
                throw new IllegalArgumentException("player name already online and not owned: " + actor.playerName());
            checkStand(world, actor.start());
            for (ActorPlan.Step step : actor.steps()) if ((step.action().equals("walk_to") || step.action().equals("recoil_to"))) checkStand(world, step.target());
            for(ActorPlan.Step step:actor.steps())if(step.action().equals("pickup_groceries")){
                ActorPlan.Point prior=null;
                for(int t=0;t<GroceryApproachRig.DURATION;t++){
                    var r=GroceryApproachRig.plannedRoot(t);
                    var p=new ActorPlan.Point(step.target().x()+r.x,step.target().y(),step.target().z()+r.z);
                    if(!take.plan.region().contains(p))throw new IllegalArgumentException("pickup route outside declared region");
                    checkStand(world,p);
                    checkPickupSpace(world,p);
                    if(prior!=null&&!clearLine(world,prior,p))throw new IllegalArgumentException("pickup route obstructed");
                    prior=p;
                }
            }
            for (ActorPlan.Step step : actor.steps()) if (step.action().equals("sneak"))
                throw new IllegalArgumentException("sneak is reserved but not enabled");
        }
        Files.createDirectories(take.trace.getParent());
        take.writer = Files.newBufferedWriter(take.trace, StandardCharsets.UTF_8,
            StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE);
        take.ownerServer = server;
        take.spawnRequested = true;
        for (ActorPlan.Actor actor : take.plan.actors()) {
            ServerPlayerEntity existing = server.getPlayerManager().getPlayer(actor.playerName());
            if (existing != null) {
                ((ServerPlayerInterface) existing).getActionPack().stopAll();
                if (existing.getPos().distanceTo(vec(actor.start())) > 0.001)
                    existing.teleport(world, actor.start().x(), actor.start().y(), actor.start().z(), actor.yaw(), actor.pitch());
                FallenPoses.remove(existing.getUuid()); existing.clearSleepingPosition(); existing.setPose(net.minecraft.entity.EntityPose.STANDING);
                existing.setYaw((float)actor.yaw()); existing.setPitch((float)actor.pitch());
                continue;
            }
            boolean spawned = EntityPlayerMPFake.createFake(actor.playerName(), server,
                vec(actor.start()), actor.yaw(), actor.pitch(), World.OVERWORLD, GameMode.CREATIVE, false);
            if (!spawned) throw new IllegalStateException("Carpet refused fake player spawn: " + actor.playerName());
        }
    }

    private boolean runActorStep(Take take, ActorRun run, ServerWorld world) {
        ServerPlayerEntity player = world.getServer().getPlayerManager().getPlayer(run.uuid);
        if (player == null || player != run.player) throw new IllegalStateException("owned actor vanished or identity changed: " + run.plan.actorId());
        if (!take.plan.region().contains(new ActorPlan.Point(player.getX(), player.getY(), player.getZ())))
            throw new IllegalStateException("actor escaped the declared region");
        int tick = take.tick;
        ActorPlan.Step step = run.plan.steps().stream().filter(s -> tick >= s.startTick()
            && tick < s.startTick() + s.durationTicks()).findFirst().orElseThrow();
        if (step != run.step) {
            leaveStep(run);
            run.step = step;
            run.stepStarted = tick;
            ServerPlayerInterface controls = (ServerPlayerInterface) player;
            switch (step.action()) {
                case "idle", "phone", "phone_sit", "phone_call", "phone_call_sit", "sit", "explain", "reach", "down", "support_actor", "push_actor", "phone_stop", "phone_putaway", "phone_putaway_sit", "pack_bag_sit", "pack_bag_stand", "pickup_coat", "hold_coat" -> controls.getActionPack().stopMovement();
                case "walk_to", "recoil_to" -> {
                    if (!clearLine(world, new ActorPlan.Point(player.getX(), player.getY(), player.getZ()), step.target()))
                        throw new IllegalStateException("walk_to path is obstructed");
                    if (step.action().equals("walk_to")) controls.getActionPack().look(walkYaw(player,step.target()),0.0f).setForward(1.0f);
                    else controls.getActionPack().stopMovement();
                    run.walkStart = new ActorPlan.Point(player.getX(), player.getY(), player.getZ());
                    run.lastProgress = run.walkStart.distanceXZ(step.target());
                    run.walkStartTick = tick;
                    run.lastProgressTick = tick;
                    run.arrivedAt = -1;
                    run.driftChecked = false;
                }
                case "look_at" -> controls.getActionPack().stopMovement().lookAt(vec(step.target()));
                case "phone_place_sit" -> {controls.getActionPack().stopMovement();visuals.beginPhonePlacement(world,player,step.target(),take.plan.takeId());}
                case "swing_arm" -> { controls.getActionPack().stopMovement(); player.swingHand(net.minecraft.util.Hand.MAIN_HAND,true); }
                case "fall_down" -> {
                    controls.getActionPack().stopMovement(); player.setVelocity(Vec3d.ZERO);
                    player.clearSleepingPosition(); FallenPoses.add(player.getUuid()); player.setPose(net.minecraft.entity.EntityPose.SLEEPING);
                }
                case "stand_up", "rise_supported" -> {
                    FallenPoses.remove(player.getUuid()); player.clearSleepingPosition(); player.setPose(net.minecraft.entity.EntityPose.STANDING); controls.getActionPack().stopMovement();
                }
                case "prepare_board" -> {
                    controls.getActionPack().stopMovement();
                    run.board=new BoardProp(world,step.target(),run.plan.start().y(),take.plan.takeId());
                    run.propUuid=run.board.display.getUuidAsString();
                }
                case "drop_board" -> {
                    controls.getActionPack().stopMovement();
                    if(run.board==null)throw new IllegalStateException("owned board is not prepared");
                    run.board.release(tick);
                }
                case "scatter_groceries" -> {
                    controls.getActionPack().stopMovement();player.setVelocity(Vec3d.ZERO);
                    if(take.groceries!=null||new ActorPlan.Point(player.getX(),player.getY(),player.getZ()).distanceXZ(step.target())>.35||Math.abs(player.getY()-step.target().y())>.1)
                        throw new IllegalStateException("grocery scatter actor is outside the registered floor position");
                    player.clearSleepingPosition();FallenPoses.add(player.getUuid());player.setPose(net.minecraft.entity.EntityPose.SLEEPING);
                    var release=visuals.releaseGroceryBag(player);
                    take.groceries=new GroceryProps(world,step.target(),tick,take.plan.takeId(),release);
                }
                case "pickup_groceries" -> {
                    controls.getActionPack().stopMovement();
                    // The registered rig has a fixed forward axis. A final small
                    // facing correction is explicit; staging still must walk in.
                    if(Math.abs(player.getYaw())<=3)controls.getActionPack().look(0,0);
                    if(step.durationTicks()!=GroceryApproachRig.DURATION||Math.abs(player.getYaw())>.01||take.groceries==null||Math.abs(player.getX()-take.groceries.center.x())>.025||Math.abs(player.getZ()-(take.groceries.center.z()-.4))>.025)
                        throw new IllegalStateException("contact pickup requires3040ticks, yaw0, center.x/center.z-.4 anchor");
                    if(take.groceries==null||new ActorPlan.Point(player.getX(),player.getY(),player.getZ()).distanceXZ(take.groceries.center)>2||Math.abs(player.getY()-take.groceries.center.y())>.1)
                        throw new IllegalStateException("owned groceries absent or beyond pickup reach");
                    visuals.prepareGroceryPickup(player,take.groceries.center);
                    take.groceries.startPickup(run.plan.actorId(),tick,checkedPickupHand(take,player));
                }
                case "drop_material" -> {
                    controls.getActionPack().stopMovement();
                    BlockPos drop=BlockPos.ofFloored(step.target().x(),step.target().y(),step.target().z());
                    if(!world.getBlockState(drop).isAir()) throw new IllegalStateException("material origin must be empty");
                    for(int yy=drop.getY();yy>=Math.floor(run.plan.start().y());yy--)
                        if(!world.getBlockState(new BlockPos(drop.getX(),yy,drop.getZ())).isAir()) throw new IllegalStateException("material fall column is obstructed");
                    var prop=net.minecraft.entity.FallingBlockEntity.spawnFromBlock(world,drop,net.minecraft.block.Blocks.GRAY_CONCRETE_POWDER.getDefaultState());
                    prop.dropItem=false; prop.setHurtEntities(0.0f,0); prop.addCommandTag("mcfilm-"+take.plan.takeId());
                    run.propUuid=prop.getUuid().toString();
                }
                case "hold_item" -> {
                    controls.getActionPack().stopMovement();
                    player.setStackInHand(net.minecraft.util.Hand.MAIN_HAND,
                        new net.minecraft.item.ItemStack(net.minecraft.item.Items.BOOK));
                }
                default -> throw new IllegalArgumentException("G1 action disabled: " + step.action());
            }
        }
        if ((step.action().equals("walk_to") || step.action().equals("recoil_to")) && run.arrivedAt < 0) {
            double remaining = new ActorPlan.Point(player.getX(), player.getY(), player.getZ()).distanceXZ(step.target());
            boolean pickupStaging=step.action().equals("walk_to")&&run.plan.steps().stream().anyMatch(s->s.action().equals("pickup_groceries")&&s.startTick()>step.startTick()&&Math.abs(s.target().x()-step.target().x())<.001&&Math.abs(s.target().z()-.4-step.target().z())<.001);
            if (remaining <= (pickupStaging?.005:.10)) {
                ((ServerPlayerInterface) player).getActionPack().stopMovement();
                player.setVelocity(0.0, player.getVelocity().y, 0.0);
                run.arrivedAt = tick;
                run.stoppedAt = new ActorPlan.Point(player.getX(), player.getY(), player.getZ());
            } else {
                if (run.lastProgress - remaining >= 0.001) run.lastProgressTick = tick;
                if (tick - run.lastProgressTick >= 20)
                    throw new IllegalStateException("fake player made no walking progress for 20 ticks");
                if (remaining < run.lastProgress) run.lastProgress = remaining;
                if(pickupStaging&&remaining<=.12){
                    ((ServerPlayerInterface)player).getActionPack().stopMovement();
                    double scale=Math.min(.02,remaining*.6)/remaining;
                    player.setVelocity((step.target().x()-player.getX())*scale,player.getVelocity().y,(step.target().z()-player.getZ())*scale);player.velocityModified=true;
                }else if (step.action().equals("walk_to")) ((ServerPlayerInterface) player).getActionPack().look(walkYaw(player,step.target()),0.0f)
                    .setForward((float)Math.min(1.0, Math.max(0.08, remaining * 1.5)));
                else {
                    double dx=step.target().x()-player.getX(), dz=step.target().z()-player.getZ();
                    double speed=Math.min(0.22, remaining*0.7);
                    player.setVelocity(dx/remaining*speed,player.getVelocity().y,dz/remaining*speed);
                    player.velocityModified=true;
                }
                if (tick - run.walkStartTick >= step.timeoutTicks()) throw new IllegalStateException("walk_to timed out before target");
            }
        }
        if (run.arrivedAt >= 0 && tick - run.arrivedAt >= 20 && !run.driftChecked) {
            double drift = run.stoppedAt.distanceXZ(new ActorPlan.Point(player.getX(), player.getY(), player.getZ()));
            run.stopDrift = drift;
            run.driftChecked = true;
            if (drift > 0.05) throw new IllegalStateException("actor drift after stop exceeded 0.05 blocks: " + drift);
        }
        if(step.action().equals("pickup_groceries")){
            int elapsed=tick-run.stepStarted;
            var center=take.groceries.center;
            var planned=GroceryApproachRig.plannedRoot(elapsed);
            double error=Math.hypot(player.getX()-center.x()-planned.x,player.getZ()-center.z()-planned.z);
            if(error>.08||Math.abs(player.getY()-center.y())>.025||Math.abs(player.getYaw())>.01)
                throw new IllegalStateException("pickup route/floor/facing deviation: "+error);
            var next=GroceryApproachRig.plannedRoot(Math.min(elapsed+1,GroceryApproachRig.DURATION-1));
            var target=new ActorPlan.Point(center.x()+next.x,center.y(),center.z()+next.z);
            checkStand(world,target);
            checkPickupSpace(world,target);
            if(!take.plan.region().contains(target)||!clearLine(world,new ActorPlan.Point(player.getX(),player.getY(),player.getZ()),target))
                throw new IllegalStateException("pickup route became obstructed");
            ((ServerPlayerInterface)player).getActionPack().stopMovement();
            double dx=target.x()-player.getX(),dz=target.z()-player.getZ();
            if(Math.hypot(dx,dz)>.05)throw new IllegalStateException("pickup velocity correction exceeds bounded step");
            player.setVelocity(dx,player.getVelocity().y,dz);player.velocityModified=true;
        }
        if(run.board!=null)run.board.tick(take.tick);
        visuals.update(player,step.action(),take.tick,take.tick-run.stepStarted,step.durationTicks());
        visuals.updateMouth(player,run.plan.mouthFrames().isEmpty()?0:run.plan.mouthFrames().get(take.tick));
        if(take.groceries!=null&&run.plan.actorId().equals(take.groceries.collector))
            take.groceries.updateHand(run.plan.actorId(),checkedPickupHand(take,player));
        return true;
    }

    private void leaveStep(ActorRun run) {
        if(run.step!=null&&run.step.action().equals("pickup_groceries")){
            ((ServerPlayerInterface)run.player).getActionPack().stopMovement();
            run.player.setVelocity(0,run.player.getVelocity().y,0);
        }
        if (run.step != null && (run.step.action().equals("walk_to") || run.step.action().equals("recoil_to"))) {
            if (run.arrivedAt < 0) throw new IllegalStateException("walk_to step ended before arrival");
            double error = run.stoppedAt.distanceXZ(run.step.target());
            if (error > 0.15) throw new IllegalStateException("walk endpoint error exceeded 0.15 blocks: " + error);
            if (!run.driftChecked) throw new IllegalStateException("walk stop stability window did not finish");
            run.walkError = error;
        }
    }

    private net.minecraft.util.math.Vec3d checkedPickupHand(Take take,ServerPlayerEntity player){
        var hand=visuals.pickupHandPosition(player);
        var point=new ActorPlan.Point(hand.x,hand.y,hand.z);
        if(!Double.isFinite(hand.x)||!Double.isFinite(hand.y)||!Double.isFinite(hand.z)||!take.plan.region().contains(point)||hand.squaredDistanceTo(player.getPos())>4)
            throw new IllegalStateException("pickup hand outside bounded actor region");
        return hand;
    }
    private void appendTrace(Take take, ActorRun run, ServerWorld world) throws IOException {
        ServerPlayerEntity player = world.getServer().getPlayerManager().getPlayer(run.uuid);
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("run_id", take.plan.runId()); row.put("take_id", take.plan.takeId());
        row.put("actor_id", run.plan.actorId()); row.put("uuid", run.uuid.toString());
        row.put("server_tick", world.getTime()); row.put("planned_tick", take.tick);
        row.put("wall_clock_ms", System.currentTimeMillis());
        // ReplayMod pauses its packet clock during initialization; epoch time
        // minus metadata.date does not locate an actor cue in the replay.
        // Persist the same native clock already used for Mocap playback onsets.
        var clock = replayClock;
        row.put("replay_timestamp_ms", clock == null ? -1L : clock.getAsLong());
        row.put("x", player.getX()); row.put("y", player.getY()); row.put("z", player.getZ());
        row.put("velocity", Map.of("x", player.getVelocity().x, "y", player.getVelocity().y, "z", player.getVelocity().z));
        row.put("yaw", (double)player.getYaw()); row.put("pitch", (double)player.getPitch());
        row.put("pose", player.getPose().name());
        row.put("visual",visuals.proof(player));
        row.put("prop_uuid", run.propUuid);
        if(run.board!=null)row.put("board",run.board.proof());
        if(take.groceries!=null)row.put("groceries",take.groceries.proof());
        row.put("action", run.step == null ? "idle" : run.step.action());
        row.put("walk_error", run.walkError); row.put("stop_drift", run.stopDrift);
        take.writer.write(MiniJson.write(row)); take.writer.newLine(); take.writer.flush();
    }

    private void finish(Take take) throws IOException {
        if(take.groceries!=null&&!take.groceries.complete())throw new IllegalStateException("owned groceries were not completely collected");
        for (ActorRun actor : take.actors) leaveStep(actor);
        closeTrace(take);
        Map<String, Object> actorResults = new LinkedHashMap<>();
        for (ActorRun actor : take.actors) actorResults.put(actor.plan.actorId(), Map.of(
            "player_name", actor.plan.playerName(), "uuid", actor.uuid.toString(),
            "walk_error", actor.walkError, "stop_drift", actor.stopDrift));
        Map<String, Object> proof = Map.of("status", "succeeded", "journal_state", "succeeded",
            "result", Map.of("take_id", take.plan.takeId(), "take_state", "succeeded",
                "duration_ticks", take.tick, "actors", actorResults,
                "trace", take.trace.toString(), "trace_sha256", hash(take.trace)));
        take.state = "succeeded"; take.finishedAt = System.currentTimeMillis();
        journal.markSucceeded(take.key, proof); active = null;
    }

    private void fail(Take take, String message) {
        if(take.groceries!=null)take.groceries.discard();
        for (ActorRun actor : take.actors) {
            // A failed take must not leave visuals saved into the next reload.
            // Only actors constructed and owned by this take are released.
            try { ((ServerPlayerInterface) actor.player).getActionPack().stopAll(); }
            catch (Throwable ignored) { }
            try { if(actor.board!=null)actor.board.discard(); }
            catch (Throwable ignored) { }
            try { visuals.remove(actor.player); FallenPoses.remove(actor.uuid);
                ((EntityPlayerMPFake)actor.player).kill(Text.literal("owned rehearsal actor failed"));
                owned.remove(actor.plan.actorId()); }
            catch (Throwable cleanupError) { CinematicBridgeLog.warn("failed actor cleanup: "+cleanupError); }
        }
        closeTrace(take);
        take.state = "failed"; take.message = message; take.finishedAt = System.currentTimeMillis();
        if (journal != null && journal.get(take.key).isPresent()) {
            var state = journal.get(take.key).orElseThrow().state();
            if (state == PersistentJournal.State.RUNNING || state == PersistentJournal.State.QUEUED)
                journal.markFailed(take.key, "operation_failed", message, Map.of("take_id", take.plan.takeId(), "take_state", "failed"));
        }
        active = null;
    }

    private void cancelActive(Take take) {
        if(take.groceries!=null)take.groceries.discard();
        for (ActorRun actor : take.actors) {
            if(actor.board!=null)actor.board.discard();
            ((ServerPlayerInterface) actor.player).getActionPack().stopAll();
            visuals.remove(actor.player);
            FallenPoses.remove(actor.uuid);
            ((EntityPlayerMPFake)actor.player).kill(Text.literal("owned rehearsal actor cancelled"));
            owned.remove(actor.plan.actorId());
        }
        closeTrace(take); take.state = "cancelled"; take.finishedAt = System.currentTimeMillis();
        if (take.cancelKey != null) {
            journal.markRunning(take.cancelKey);
            journal.markSucceeded(take.cancelKey, Map.of("status", "applied", "result", take.snapshot()));
        }
        if (journal.get(take.key).orElseThrow().state() == PersistentJournal.State.RUNNING)
            journal.markFailed(take.key, "operation_failed", "actor take cancelled", Map.of("take_id", take.plan.takeId(), "take_state", "cancelled"));
        active = null;
    }

    private static boolean clearLine(ServerWorld world, ActorPlan.Point start, ActorPlan.Point end) {
        double distance = start.distanceXZ(end);
        int samples = Math.max(1, (int) Math.ceil(distance * 4));
        double height = start.y();
        for (int i = 0; i <= samples; i++) {
            double t = i / (double) samples;
            double x = start.x() + (end.x() - start.x()) * t;
            double z = start.z() + (end.z() - start.z()) * t;
            // Stairs are discrete collision surfaces, not the sloping interpolation
            // between endpoint Y values. Keep clearance/loading checks on every
            // sampled standing position, and reject gaps and full-block steps.
            var supported = new java.util.ArrayList<Double>();
            int floor = (int)Math.floor(height);
            for (int y = floor - 2; y <= floor; y++) {
                BlockPos support = BlockPos.ofFloored(x, y, z);
                if (!world.shouldTickEntity(support)) continue;
                var shape = world.getBlockState(support).getCollisionShape(world, support);
                if (shape.isEmpty()) continue;
                double surface = y + shape.getMax(net.minecraft.util.math.Direction.Axis.Y);
                if (safeStand(world, new ActorPlan.Point(x, surface, z))) supported.add(surface);
            }
            height = WalkSurface.nextHeight(height, supported);
            if (!Double.isFinite(height)) return false;
        }
        return Math.abs(height - end.y()) <= 0.0001;
    }

    private static void checkStand(ServerWorld world, ActorPlan.Point point) {
        if (!safeStand(world, point)) throw new IllegalArgumentException("actor start/target is not a safe, loaded standing position: " + point);
    }

    private static void checkPickupSpace(ServerWorld world,ActorPlan.Point point){
        // Include the fake player's entire 0.6 x 1.8 collision box. A clear
        // center cell alone misses adjacent boards, kerbs and other blocks.
        var box=new net.minecraft.util.math.Box(point.x()-.3,point.y()+.0001,point.z()-.3,point.x()+.3,point.y()+1.8,point.z()+.3);
        if(!world.isSpaceEmpty(null,box))throw new IllegalArgumentException("pickup player collision box is obstructed: "+point);
    }

    private static boolean safeStand(ServerWorld world, ActorPlan.Point point) {
        BlockPos feet = BlockPos.ofFloored(point.x(), point.y(), point.z());
        if (!world.shouldTickEntity(feet)) return false;
        var below = world.getBlockState(feet.down()).getCollisionShape(world, feet.down());
        var atFeet = world.getBlockState(feet).getCollisionShape(world, feet);
        var atHead = world.getBlockState(feet.up()).getCollisionShape(world, feet.up());
        double fraction = point.y() - Math.floor(point.y());
        boolean feetClear = atFeet.isEmpty() || atFeet.getMax(net.minecraft.util.math.Direction.Axis.Y) <= fraction + 0.0001;
        return !below.isEmpty() && feetClear && atHead.isEmpty();
    }

    private static Vec3d vec(ActorPlan.Point p) { return new Vec3d(p.x(), p.y(), p.z()); }
    private static float walkYaw(ServerPlayerEntity player, ActorPlan.Point target) {
        return (float)Math.toDegrees(Math.atan2(-(target.x()-player.getX()),target.z()-player.getZ()));
    }
    private static String hash(Path path) throws IOException {
        try {
            byte[] digest = java.security.MessageDigest.getInstance("SHA-256").digest(Files.readAllBytes(path));
            StringBuilder out = new StringBuilder("sha256:");
            for (byte b : digest) out.append(String.format("%02x", b));
            return out.toString();
        } catch (java.security.NoSuchAlgorithmException impossible) { throw new IllegalStateException(impossible); }
    }
    private static void closeTrace(Take take) {
        if (take.writer != null) try { take.writer.close(); } catch (IOException ignored) { }
        take.writer = null;
    }
    private static Map<String, Object> rejected(String message) { return Map.of("status", "rejected", "error_class", "validation_failed", "message", message); }
    private static Map<String, Object> conflict(String message) { return Map.of("status", "rejected", "error_class", "operation_conflict", "message", message); }
    private static Map<String, Object> pending(String takeId, String state, String operationId) { return Map.of("status", "pending", "journal_state", state, "result", Map.of("take_id", takeId, "take_state", state, "operation_id", operationId)); }
    private static Map<String, Object> result(String status, Map<String, Object> result) { return Map.of("status", status, "result", result); }

    private static final class Take {
        GroceryProps groceries;
        final ActorPlan plan; final String key; final Path trace; final List<ActorRun> actors = new ArrayList<>();
        String state = "queued", message, cancelKey; int tick; long startedWorldTick, finishedAt;
        boolean ready, cancelRequested, spawnRequested; int spawnWaitTicks; MinecraftServer ownerServer; BufferedWriter writer;
        Take(ActorPlan plan, String key, Path trace) { this.plan = plan; this.key = key; this.trace = trace; }
        Map<String, Object> snapshot() {
            Map<String, Object> actorsOut = new LinkedHashMap<>();
            for (ActorRun actor : actors) actorsOut.put(actor.plan.actorId(), Map.of("player_name", actor.plan.playerName(),
                "uuid", actor.uuid.toString(), "walk_error", actor.walkError, "stop_drift", actor.stopDrift));
            Map<String, Object> out = new LinkedHashMap<>();
            out.put("take_id", plan.takeId()); out.put("take_state", state); out.put("planned_tick", tick);
            out.put("duration_ticks", plan.durationTicks()); out.put("actors", actorsOut);
            if (message != null) out.put("message", message);
            if (Files.isRegularFile(trace)) out.put("trace", trace.toString());
            return out;
        }
    }
    private static final class ActorRun {
        final ActorPlan.Actor plan; final UUID uuid; final ServerPlayerEntity player;
        BoardProp board;
        String propUuid; ActorPlan.Step step; int stepStarted, walkStartTick, lastProgressTick, arrivedAt = -1;
        ActorPlan.Point walkStart, stoppedAt; double lastProgress, walkError = -1, stopDrift = -1; boolean driftChecked;
        ActorRun(ActorPlan.Actor plan, UUID uuid, ServerPlayerEntity player) { this.plan = plan; this.uuid = uuid; this.player = player; }
    }
}
