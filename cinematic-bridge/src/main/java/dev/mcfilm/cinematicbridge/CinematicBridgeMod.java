package dev.mcfilm.cinematicbridge;

import dev.mcfilm.cinematicbridge.core.TickScheduler;
import dev.mcfilm.cinematicbridge.core.VersionGate;
import dev.mcfilm.cinematicbridge.flash.FlashbackDisabledPort;
import dev.mcfilm.cinematicbridge.flash.FlashbackPort;
import dev.mcfilm.cinematicbridge.mocap.MocapStateMachine;
import dev.mcfilm.cinematicbridge.server.AsyncOperationService;
import dev.mcfilm.cinematicbridge.server.BridgeDispatcher;
import dev.mcfilm.cinematicbridge.server.BridgeHttpServer;
import dev.mcfilm.cinematicbridge.server.ClientThreadExecutor;
import dev.mcfilm.cinematicbridge.server.OperationJournal;
import dev.mcfilm.cinematicbridge.server.PersistentJournal;
import dev.mcfilm.cinematicbridge.state.GameStateV2;
import dev.mcfilm.cinematicbridge.world.WorldAccess;
import dev.mcfilm.cinematicbridge.world.WorldOperations;
import net.fabricmc.api.ClientModInitializer;
import net.fabricmc.fabric.api.client.event.lifecycle.v1.ClientTickEvents;
import net.fabricmc.fabric.api.event.lifecycle.v1.ServerTickEvents;
import net.fabricmc.fabric.api.client.message.v1.ClientReceiveMessageEvents;
import net.fabricmc.loader.api.FabricLoader;
import net.minecraft.block.Block;
import net.minecraft.client.MinecraftClient;
import net.minecraft.client.network.ClientPlayerEntity;
import net.minecraft.entity.Entity;
import net.minecraft.entity.EntityType;
import net.minecraft.registry.Registries;
import net.minecraft.registry.Registry;
import net.minecraft.server.world.ServerWorld;
import net.minecraft.util.Identifier;
import net.minecraft.util.math.BlockPos;
import net.minecraft.util.math.Box;
import net.minecraft.util.math.Vec3d;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * Client entrypoint (Minecraft-facing; needs a Fabric build environment).
 *
 * Wires the pure core to the game under contracts 2 and 3 (plan v2 §Phases
 * B–D; workflow v3 §4):
 * - reads the session token from config/cinematicbridge.token (never logged);
 * - reports a TRUTHFUL GameStateV2 (session phase, integrated-save name,
 *   player identity, pause) — a dimension id is never passed off as a world
 *   name (failure F8);
 * - typed world writes and authoritative proof reads run on the INTEGRATED
 *   SERVER thread via ServerWorldAccess; the client thread only serves
 *   client-owned work (mocap feedback, timeline ticks);
 * - contract-3 writes ride the persistent journal + async job pipeline; a
 *   restart recovers the ledger and leaves interrupted work visibly UNKNOWN;
 * - Mocap feedback is observed from client game messages and classified;
 *   unknown feedback fails closed (F6);
 * - the tick scheduler advances ONLY while in world, unpaused, and with no
 *   blocking screen; a pause freezes the relative take clock (F9);
 * - the Flashback port stays fail-closed (license review pending).
 */
public final class CinematicBridgeMod implements ClientModInitializer {

    static final int DEFAULT_PORT = 25575;
    /** Same-task proof reads need the dispatch to come back; chat feedback needs polling. */
    static final int DISPATCH_TIMEOUT_MS = 5_000;
    static final int MOCAP_POLLS = 20;
    static final long MOCAP_POLL_SLEEP_MS = 100;

    private static BridgeDispatcher dispatcher;
    private static MocapStateMachine mocapMachine;
    private static final AtomicInteger TAKE_TICK = new AtomicInteger(0);
    private static dev.mcfilm.cinematicbridge.actor.ActorService actorService;

    @Override
    public void onInitializeClient() {
        Path configDir = FabricLoader.getInstance().getConfigDir();
        String token = readToken(configDir.resolve("cinematicbridge.token"));
        if (token == null || token.isBlank()) {
            CinematicBridgeLog.warn("no config/cinematicbridge.token; bridge stays offline");
            return;
        }

        // minecraft is pinned by fabric.mod.json depends (minecraft ~1.21.1);
        // flashback stays at the pinned value the gate expects to hear back.
        VersionGate.RuntimeVersions versions = VersionGate.RuntimeVersions.of(
            "1.21.1",
            FabricLoader.getInstance().getModContainer("fabricloader")
                .map(c -> c.getMetadata().getVersion().getFriendlyString()).orElse("unknown"),
            detectModVersion("flashback"),
            detectModVersion("mocap"));
        if (!VersionGate.automationAllowed(versions)) {
            CinematicBridgeLog.warn("version gate closed: " + VersionGate.mismatches(versions));
        }

        FlashbackPort flashbackPort = new FlashbackDisabledPort();
        ClientThreadExecutor executor = new ClientThreadExecutor(task -> {
            MinecraftClient client=MinecraftClient.getInstance();
            if (client.isOnThread()) task.run(); else client.execute(task);
        });
        mocapMachine = new MocapStateMachine(command ->
            executor.dispatch(DISPATCH_TIMEOUT_MS, () -> {
                runCommandNow(command);
                return "sent";
            }));

        // World writes and authoritative reads run on the INTEGRATED SERVER
        // thread (workflow v3 §4.2): the client world is a render mirror and
        // must never be the proof surface. The runner refuses when no
        // integrated server is up — ClientThreadExecutor turns that refusal
        // into a proven failure, never into "unknown".
        ClientThreadExecutor serverExecutor = new ClientThreadExecutor(task -> {
            net.minecraft.server.MinecraftServer server = MinecraftClient.getInstance().getServer();
            if (server == null) {
                throw new IllegalStateException(
                    "no integrated server: world writes require an in-game single-player session");
            }
            server.execute(task);
        });

        OperationJournal journal = new OperationJournal();
        WorldOperations worldOps = new WorldOperations(
            new ServerWorldAccess(), serverExecutor, journal, DISPATCH_TIMEOUT_MS);

        // Persistent ledger (workflow v3 §4.4): accepted → succeeded/failed/
        // unknown survive process restarts. Unavailable disk → contract-3
        // stays offline (fail closed) while contract-2 keeps the game usable.
        PersistentJournal persistentJournal = null;
        try {
            persistentJournal = PersistentJournal.open(
                configDir.resolve("cinematicbridge-journal"));
        } catch (Exception error) {
            CinematicBridgeLog.warn("persistent journal unavailable, contract 3 disabled: " + error);
        }
        AsyncOperationService asyncOps = persistentJournal == null
            ? null
            : new AsyncOperationService(persistentJournal, worldOps, serverExecutor,
                DISPATCH_TIMEOUT_MS);

        // Replay-master port (workflow v3 §7-P1): the ReplayMod binding only
        // comes up with the EXACTLY pinned version loaded. The binding class
        // must never be touched while replaymod is absent — every reference
        // stays inside the guard so a plain install keeps working fail-closed.
        dev.mcfilm.cinematicbridge.replay.ReplayPort replayPort =
            new dev.mcfilm.cinematicbridge.replay.ReplayDisabledPort();
        String replayModVersion = detectModVersion("replaymod");
        if (!"missing".equals(replayModVersion)) {
            try {
                if (dev.mcfilm.cinematicbridge.replay.ReplayModBinding.EXPECTED_VERSIONS
                    .contains(replayModVersion)) {
                    replayPort = new dev.mcfilm.cinematicbridge.replay.ReplayModBinding(
                        executor, FabricLoader.getInstance().getGameDir().resolve("replays"));
                    CinematicBridgeLog.info("replaymod binding active at pinned " + replayModVersion);
                } else {
                    CinematicBridgeLog.warn("replaymod " + replayModVersion
                        + " is not the pinned 1.21-2.6.27; replay port stays fail-closed");
                }
            } catch (Throwable error) {
                CinematicBridgeLog.warn("replaymod binding failed to construct: " + error);
            }
        }

        dispatcher = new BridgeDispatcher(
            command -> {
                // legacy timeline-event commands: bounded dispatch, no fake ack
                executor.dispatch(DISPATCH_TIMEOUT_MS, () -> {
                    runCommandNow(command);
                    return "sent";
                });
                return "";
            },
            flashbackPort,
            () -> snapshotState().toMap(),
            versions,
            journal, worldOps, mocapMachine, mocapMachine::phase,
            MOCAP_POLLS, MOCAP_POLL_SLEEP_MS,
            persistentJournal, asyncOps, replayPort);

        String projectRoot = System.getenv("MINECRAFT_FILM_PROJECT_ROOT");
        if (persistentJournal != null && projectRoot != null && !projectRoot.isBlank()) {
            try {
                actorService = new dev.mcfilm.cinematicbridge.actor.ActorService(
                    Path.of(projectRoot), persistentJournal, () -> MinecraftClient.getInstance().getServer());
                dispatcher.setActorService(actorService);
                ServerTickEvents.END_SERVER_TICK.register(server -> actorService.tick(server));
                CinematicBridgeLog.info("typed Carpet actor driver available");
            } catch (RuntimeException invalidRoot) {
                CinematicBridgeLog.warn("typed actor driver disabled: " + invalidRoot.getMessage());
            }
        } else {
            CinematicBridgeLog.warn("typed actor driver disabled: project root or persistent journal unavailable");
        }

        try {
            BridgeHttpServer server = new BridgeHttpServer(DEFAULT_PORT, token, dispatcher);
            server.start();
            CinematicBridgeLog.info("bridge listening on 127.0.0.1:" + server.port()
                + "/rpc (contract 3, async world writes: " + (asyncOps != null) + ")");
        } catch (Exception error) {
            CinematicBridgeLog.warn("bridge HTTP server failed to start: " + error);
        }

        // Mocap feedback arrives as game messages; classification is the ONLY
        // source of state transitions — dispatch alone never proves anything.
        ClientReceiveMessageEvents.GAME.register((message, overlay) -> {
            if (mocapMachine != null) {
                mocapMachine.observeGameMessage(message.getString(), recordingFeedback(message));
                if (dispatcher!=null) dispatcher.observeTimelineFeedback(message.getString());
            }
        });

        // F9: a take advances only in world, unpaused, without a blocking screen.
        ClientTickEvents.END_CLIENT_TICK.register(client -> {
            if (dispatcher == null) {
                return;
            }
            TickScheduler active = dispatcher.activeScheduler();
            boolean running = active != null && (active.state() == TickScheduler.State.RUNNING
                || active.state() == TickScheduler.State.READY);
            if (running && client.world != null && !client.isPaused() && client.currentScreen == null) {
                active.tick(TAKE_TICK.getAndIncrement());
            } else if (!running) {
                TAKE_TICK.set(0);
            }
        });
    }

    // -- truthful game state (F8) ---------------------------------------------

    static GameStateV2 snapshotState() {
        MinecraftClient client = MinecraftClient.getInstance();
        if (client.world == null) {
            return client.getServer() != null
                ? new GameStateV2(GameStateV2.Phase.LOADING_WORLD, saveName(), null, null, true, null, true, null)
                : GameStateV2.mainMenu();
        }
        boolean inEditor = client.currentScreen != null
            && client.currentScreen.getClass().getName().toLowerCase(java.util.Locale.ROOT).contains("flashback");
        return new GameStateV2(
            inEditor ? GameStateV2.Phase.REPLAY_EDITOR : GameStateV2.Phase.IN_WORLD,
            saveName(),
            client.world.getRegistryKey().getValue().toString(),
            client.player != null ? client.player.getGameProfile().getName() : null,
            client.isPaused(),
            client.world.getTime(),
            client.currentScreen != null,
            client.currentScreen == null ? null
                : client.currentScreen.getClass().getName());
    }

    /** Integrated-save name; null on dedicated/remote sessions. */
    private static String saveName() {
        MinecraftClient client = MinecraftClient.getInstance();
        try {
            if (client.getServer() != null) {
                return client.getServer().getSaveProperties().getLevelName();
            }
        } catch (Exception error) {
            CinematicBridgeLog.warn("save name unavailable: " + error);
        }
        return null;
    }

    /** Route by translation namespace; unrelated chat cannot change recorder state. */
    private static boolean recordingFeedback(net.minecraft.text.Text text) {
        if (text.getContent() instanceof net.minecraft.text.TranslatableTextContent content) {
            if (content.getKey().startsWith("mocap.recording.")) return true;
            for (Object arg:content.getArgs())
                if (arg instanceof net.minecraft.text.Text child && recordingFeedback(child)) return true;
        }
        for (var child:text.getSiblings()) if (recordingFeedback(child)) return true;
        return false;
    }

    /** Must run on the client thread. Command feedback arrives via chat events. */
    private static void runCommandNow(String command) {
        MinecraftClient client = MinecraftClient.getInstance();
        ClientPlayerEntity player = client.player;
        if (player == null || player.networkHandler == null) {
            CinematicBridgeLog.warn("command dropped (no player): " + command);
            return;
        }
        if (command.startsWith("mocap playing stopScene .")) {
            String ownedName=command.substring("mocap playing stopScene .".length());
            var server=client.getServer();
            if (server==null) throw new IllegalStateException("owned scene stop requires integrated server");
            server.execute(() -> {
                String feedback;
                try {
                    Class<?> playing=Class.forName("com.mt1006.mocap.mocap.playing.Playing");
                    java.util.List<?> scenes=(java.util.List<?>)playing.getField("playedScenes").get(null);
                    java.util.List<Object> matches=new java.util.ArrayList<>();
                    for(Object scene:scenes) {
                        String name=(String)scene.getClass().getMethod("getName").invoke(scene);
                        if (ownedName.equals(name) || ("."+ownedName).equals(name)) matches.add(scene);
                    }
                    if (matches.size()>1) throw new IllegalStateException("ambiguous owned scene playback");
                    if (matches.isEmpty()) feedback="Owned scene already completed";
                    else {
                        Object scene=matches.getFirst();
                        int id=((Number)scene.getClass().getMethod("getID").invoke(scene)).intValue();
                        CinematicBridgeLog.info("stopping owned scene "+ownedName+" playback id="+id);
                        client.execute(() -> runCommandNow("mocap playing stop "+id));
                        return; // Only the mod's command feedback proves successful stopping.
                    }
                } catch (Throwable error) { feedback="Error: owned scene stop failed: "+error; }
                String result=feedback;
                client.execute(() -> dispatcher.observeTimelineFeedback(result));
            });
            return;
        }
        try {
            player.networkHandler.sendChatCommand(command);
        } catch (Exception error) {
            CinematicBridgeLog.warn("command failed: " + command + " → " + error);
        }
    }

    // -- authoritative world access on the integrated server thread --------------
    //
    // Reads and command execution happen on the SERVER world (workflow v3
    // §4.2). The client world is a render mirror: a proof read taken there
    // cannot show that the server executed anything (failure F5's root).

    static final class ServerWorldAccess implements WorldAccess {

        @Override
        public boolean blockExists(String blockId) {
            return registryHas(Registries.BLOCK, blockId);
        }

        @Override
        public boolean entityTypeExists(String entityTypeId) {
            return registryHas(Registries.ENTITY_TYPE, entityTypeId);
        }

        private static boolean registryHas(Registry<?> registry, String id) {
            try {
                return registry.containsId(Identifier.of(id));
            } catch (Exception error) {
                return false;
            }
        }

        private static ServerWorld world() {
            MinecraftClient client = MinecraftClient.getInstance();
            if (client.getServer() == null || client.world == null) {
                return null;
            }
            return client.getServer().getWorld(client.world.getRegistryKey());
        }

        @Override
        public boolean entityPositionReady(int x, int y, int z) {
            ServerWorld world = world();
            return world != null && world.shouldTickEntity(new BlockPos(x, y, z));
        }

        @Override
        public String canonicalBlockState(String state) {
            try {
                ServerWorld level=world();
                if (level==null) return null;
                var parsed=net.minecraft.command.argument.BlockArgumentParser.block(
                    level.getRegistryManager().getWrapperOrThrow(net.minecraft.registry.RegistryKeys.BLOCK),state,false);
                return net.minecraft.command.argument.BlockArgumentParser.stringifyBlockState(parsed.blockState());
            } catch (Exception invalid) { return null; }
        }

        @Override
        public String blockStateAt(int x,int y,int z) {
            ServerWorld level=world();
            return level==null ? "" : net.minecraft.command.argument.BlockArgumentParser.stringifyBlockState(
                level.getBlockState(new BlockPos(x,y,z)));
        }

        @Override
        public void setBlockKeepExact(int x,int y,int z,String state) {
            ServerWorld level=world();
            if (level==null) throw new IllegalStateException("world is not loaded");
            BlockPos point=new BlockPos(x,y,z);
            if (!level.getBlockState(point).isAir()) throw new IllegalStateException("keep target is occupied");
            if (!level.shouldTickEntity(point)) throw new IllegalStateException("keep target is not loaded");
            try {
                var parsed=net.minecraft.command.argument.BlockArgumentParser.block(
                    level.getRegistryManager().getWrapperOrThrow(net.minecraft.registry.RegistryKeys.BLOCK),state,false);
                level.setBlockState(point,parsed.blockState(),Block.NOTIFY_LISTENERS | Block.FORCE_STATE);
            } catch (com.mojang.brigadier.exceptions.CommandSyntaxException invalid) {
                throw new IllegalArgumentException("invalid schematic block state",invalid);
            }
        }

        @Override
        public String blockAt(int x, int y, int z) {
            ServerWorld world = world();
            if (world == null) {
                return "";
            }
            Block block = world.getBlockState(new BlockPos(x, y, z)).getBlock();
            return Registries.BLOCK.getId(block).toString();
        }

        @Override
        public long countBlocks(String blockId, int[] start, int[] end) {
            ServerWorld world = world();
            if (world == null) {
                return 0;
            }
            Identifier target = Identifier.of(blockId);
            long count = 0;
            int minX = Math.min(start[0], end[0]), maxX = Math.max(start[0], end[0]);
            int minY = Math.min(start[1], end[1]), maxY = Math.max(start[1], end[1]);
            int minZ = Math.min(start[2], end[2]), maxZ = Math.max(start[2], end[2]);
            for (BlockPos pos : BlockPos.iterate(minX, minY, minZ, maxX, maxY, maxZ)) {
                if (Registries.BLOCK.getId(world.getBlockState(pos).getBlock()).equals(target)) {
                    count++;
                }
            }
            return count;
        }

        @Override
        public long countAir(int[] start, int[] end) {
            ServerWorld world = world();
            if (world == null) {
                return 0;
            }
            long count = 0;
            int minX = Math.min(start[0], end[0]), maxX = Math.max(start[0], end[0]);
            int minY = Math.min(start[1], end[1]), maxY = Math.max(start[1], end[1]);
            int minZ = Math.min(start[2], end[2]), maxZ = Math.max(start[2], end[2]);
            for (BlockPos pos : BlockPos.iterate(minX, minY, minZ, maxX, maxY, maxZ)) {
                if (world.getBlockState(pos).isAir()) {
                    count++;
                }
            }
            return count;
        }

        @Override
        public long timeOfDay() {
            ServerWorld world = world();
            return world == null ? -1 : world.getTimeOfDay() % 24_000L;
        }

        @Override
        public boolean raining() {
            // The LEVEL PROPERTY is the authoritative instant flag; World
            // .isRaining() reads the eased rain GRADIENT, which lags the flag
            // through the fade and made a successful `weather clear` look
            // like a failure in the P0 live round.
            ServerWorld world = world();
            return world != null && world.getLevelProperties().isRaining();
        }

        @Override
        public boolean thundering() {
            ServerWorld world = world();
            return world != null && world.getLevelProperties().isThundering();
        }

        @Override
        public double rainGradient() { ServerWorld level=world(); return level==null ? -1 : level.getRainGradient(1.0f); }
        @Override
        public double thunderGradient() { ServerWorld level=world(); return level==null ? -1 : level.getThunderGradient(1.0f); }

        @Override
        public long countEntities(String entityTypeId, int x, int y, int z, int radius) {
            return entityIds(entityTypeId, x, y, z, radius).size();
        }

        @Override
        public java.util.List<String> entityIds(String entityTypeId, int x, int y, int z, int radius) {
            ServerWorld world = world();
            if (world == null) {
                return java.util.List.of();
            }
            Identifier target = Identifier.of(entityTypeId);
            Box box = new Box(new Vec3d(x - radius, y - radius, z - radius),
                new Vec3d(x + radius, y + radius, z + radius));
            return world.getEntitiesByClass(Entity.class, box,
                    entity -> EntityType.getId(entity.getType()).equals(target))
                .stream().map(Entity::getUuidAsString).toList();
        }

        @Override
        public String firstEntityWithTag(String tag) {
            ServerWorld world = world();
            if (world == null) {
                return null;
            }
            for (Entity entity : world.iterateEntities()) {
                if (entity.getCommandTags().contains(tag)) {
                    return entity.getUuidAsString();
                }
            }
            return null;
        }

        @Override
        public void runCommand(String command) {
            // Same thread (server task): the command applies before the proof read.
            net.minecraft.server.MinecraftServer server = MinecraftClient.getInstance().getServer();
            if (server == null) {
                CinematicBridgeLog.warn("command dropped (no integrated server): " + command);
                return;
            }
            try {
                server.getCommandManager().executeWithPrefix(
                    server.getCommandSource().withLevel(2).withSilent(), command);
            } catch (Exception error) {
                CinematicBridgeLog.warn("command failed: " + command + " → " + error);
            }
        }
    }

    private static String detectModVersion(String modId) {
        return FabricLoader.getInstance().getModContainer(modId)
            .map(container -> container.getMetadata().getVersion().getFriendlyString())
            .orElse("missing");
    }

    private static String readToken(Path path) {
        try {
            if (!Files.isRegularFile(path)) {
                return null;
            }
            return Files.readString(path).trim();
        } catch (Exception error) {
            return null;
        }
    }
}
