package dev.mcfilm.cinematicbridge.replay;

import com.replaymod.pathing.properties.CameraProperties;
import com.replaymod.pathing.properties.TimestampProperty;
import com.replaymod.recording.ReplayModRecording;
import com.replaymod.render.RenderSettings;
import com.replaymod.render.rendering.VideoRenderer;
import com.replaymod.replay.ReplayHandler;
import com.replaymod.replay.ReplayModReplay;
import com.replaymod.replaystudio.pathing.interpolation.CatmullRomSplineInterpolator;
import com.replaymod.replaystudio.pathing.interpolation.Interpolator;
import com.replaymod.replaystudio.pathing.interpolation.LinearInterpolator;
import com.replaymod.replaystudio.pathing.path.Keyframe;
import com.replaymod.replaystudio.pathing.path.Timeline;
import com.replaymod.replaystudio.replay.ReplayFile;
import com.replaymod.lib.org.apache.commons.lang3.tuple.Triple;
import dev.mcfilm.cinematicbridge.CinematicBridgeLog;
import dev.mcfilm.cinematicbridge.core.CameraTrackConverter;
import dev.mcfilm.cinematicbridge.json.MiniJson;
import dev.mcfilm.cinematicbridge.server.ClientThreadExecutor;
import net.minecraft.client.MinecraftClient;
import net.minecraft.client.network.ClientPlayNetworkHandler;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * The pinned ReplayMod binding (workflow v3 §7-P1). Compiled against the
 * REAL 1.21-2.6.27 API (local-maven mirror, sha1-pinned); at runtime it is
 * constructed only when that exact version is loaded — any other version
 * leaves the port fail-closed ({@link ReplayDisabledPort}).
 *
 * Semantics mapped onto ReplayMod's actual behavior:
 * - start_recording: {@link ReplayModRecording#initiateRecording} on the
 *   live client connection. ReplayMod has no mid-session "stop": the master
 *   is finalized when the world unloads, so stop_recording deterministically
 *   leaves the world on the client thread.
 * - await_master_saved: poll the captured listener's exact recording; validate
 *   metadata, packet framing, timestamps and CRC before publishing a unique master.
 * - open_master: {@code ReplayFilesService.open} + {@code startReplay} on
 *   the client thread; the handler is kept for camera and render.
 * - replace_camera_track: replaystudio Timeline built from the compiler's
 *   raw keyframes (CameraProperties + TimestampProperty). Timestamps are
 *   supplied in ticks by the controller and converted to the path's
 *   millisecond clock (×50); cropped video time starts at zero.
 * - start_render: construction and renderVideo are queued to the client thread;
 *   progress/cancel come from the renderer, never from optimism.
 *
 * FFmpeg is ReplayMod's own dependency (no system ffmpeg bundled): rendering
 * fails with NoFFmpegException surfaces as a failed job — never as success.
 */
public final class ReplayModBinding implements ReplayPort {

    public static final Set<String> EXPECTED_VERSIONS = Set.of("2.6.27", "1.21-2.6.27");

    private final ClientThreadExecutor client;
    private final Path replaysDir;
    private volatile Timeline pendingTimeline;
    private volatile RenderJob renderJob;
    private volatile String recordingId;
    private volatile Path recordingPath;
    private volatile Path recordingRawPath;
    private volatile Path recordingFinalPath;
    private volatile long recordingDate;
    private volatile Object recordingListener;
    private volatile boolean stopRequested;
    private volatile List<Map<String,Object>> cameraFrames;
    private volatile String cameraInterpolation;
    private volatile String masterError;
    private volatile ReplayFile pendingFile;
    private volatile ReplayHandler previousHandler;
    private volatile long masterGeneration;
    private volatile String liveMasterHash;

    // Master lifecycle, observed not awaited (workflow v3: queue, then poll —
    // startReplay needs the client thread to pump its own setup queue).
    private volatile String pendingMasterId;
    private volatile String liveMasterId;
    private volatile ReplayHandler liveHandler;

    private static final class RenderJob {
        final String masterId;
        final Path output;
        final Path temporary;
        final VideoRenderer renderer;
        volatile String state = "rendering";
        volatile String error = null;
        int expectedFrames;
        volatile Map<String,Object> fovEvidence = Map.of();
        String jobId;

        RenderJob(String masterId, Path output, Path temporary, VideoRenderer renderer) {
            this.masterId = masterId;
            this.output = output;
            this.temporary = temporary;
            this.renderer = renderer;
        }
    }

    public ReplayModBinding(ClientThreadExecutor client, Path replaysDir) {
        this.client = client;
        this.replaysDir = replaysDir.toAbsolutePath().normalize();
        Thread watcher = new Thread(this::watchMaster, "cinematic-bridge-master-watch");
        watcher.setDaemon(true);
        watcher.start();
    }

    /** Observes replay-session startup off the client thread. */
    private void watchMaster() {
        try {
            while (true) {
                ReplayHandler current = ReplayModReplay.instance == null ? null : ReplayModReplay.instance.getReplayHandler();
                if (liveHandler != null && liveHandler != current) {
                    liveHandler = null;
                    liveMasterId = null;
                    pendingMasterId = null;
                }
                String pending = pendingMasterId;
                if (pending != null && !pending.equals(liveMasterId)) {
                    ReplayHandler handler = ReplayModReplay.instance == null
                        ? null : ReplayModReplay.instance.getReplayHandler();
                    if (handler != null && handler != previousHandler && handler.getReplayFile() == pendingFile) {
                        liveHandler = handler;
                        liveMasterId = pending;
                        CinematicBridgeLog.info("master loaded: " + pending);
                    }
                }
                Thread.sleep(500);
            }
        } catch (InterruptedException done) {
            Thread.currentThread().interrupt();
        }
    }

    @Override
    public String backendName() {
        return "replaymod";
    }

    @Override
    public boolean enabled() {
        return true;
    }

    @Override
    public String disabledReason() {
        return "";
    }

    @Override
    public boolean matchesHash(String id, String hash) {
        try { return ReplayArtifacts.hash(ReplayArtifacts.masterPath(replaysDir, id)).equals(hash); }
        catch (IOException invalid) { return false; }
    }

    @Override
    public long recordingTimestamp(String timelineId) {
        Object listener=recordingListener;
        if (!timelineId.equals(recordingId) || listener==null) return -1;
        return ((com.replaymod.recording.packet.PacketListener)listener).getCurrentDuration();
    }

    // -- recording ---------------------------------------------------------------

    @Override
    public synchronized Map<String, Object> startRecording(String timelineId) {
        Path canonical = ReplayArtifacts.masterPath(replaysDir, timelineId);
        if (Files.exists(canonical) || recordingId != null)
            return Map.of("status", "rejected", "error_class", "operation_rejected", "message", "master exists or recording already owned");
        ClientThreadExecutor.Dispatch dispatch = client.dispatch(10_000, () -> {
            MinecraftClient mc = MinecraftClient.getInstance();
            ClientPlayNetworkHandler handler = mc.getNetworkHandler();
            if (mc.world == null || handler == null) {
                return MiniJson.write(Map.of(
                    "ok", false, "reason", "not in a world; recording starts from the live connection"));
            }
            if (ReplayModRecording.instance == null) {
                return MiniJson.write(Map.of("ok", false, "reason", "replaymod recording module not initialized"));
            }
            ReplayModRecording.instance.initiateRecording(handler.getConnection());
            Object listener = ReplayModRecording.instance.getConnectionEventHandler().getPacketListener();
            if (listener == null) return MiniJson.write(Map.of("ok", false, "reason", "recording listener absent"));
            try {
                var field = listener.getClass().getDeclaredField("outputPath");
                field.setAccessible(true);
                recordingPath = ((Path) field.get(listener)).toAbsolutePath().normalize();
                recordingRawPath = com.replaymod.core.ReplayMod.instance.folders.getRawReplayFolder()
                    .resolve(recordingPath.getFileName()).toAbsolutePath().normalize();
                recordingFinalPath = com.replaymod.core.ReplayMod.instance.folders.getReplayFolder()
                    .resolve(recordingPath.getFileName()).toAbsolutePath().normalize();
                if (Files.exists(recordingRawPath) || Files.exists(recordingFinalPath))
                    return MiniJson.write(Map.of("ok", false, "reason", "native replay destination already exists"));
                var metadata = listener.getClass().getDeclaredField("metaData");
                metadata.setAccessible(true);
                recordingDate = ((com.replaymod.replaystudio.replay.ReplayMetaData) metadata.get(listener)).getDate();
                recordingListener = listener;
                recordingId = timelineId;
                stopRequested = false;
            } catch (ReflectiveOperationException | IOException error) {
                return MiniJson.write(Map.of("ok", false, "reason", "pinned recorder identity unavailable: " + error));
            }
            return MiniJson.write(Map.of(
                "ok", true,
                "replays_dir", replaysDir.toString(),
                "stop_semantics", "the master is finalized when the world unloads (ReplayMod behavior)"));
        });
        return fromDispatch(dispatch, "replay.start_recording");
    }

    @Override
    public Map<String, Object> stopRecording(String timelineId) {
        if (!timelineId.equals(recordingId)) return Map.of("status", "rejected", "error_class", "operation_rejected", "message", "recording ownership mismatch");
        // P0-live finding: calling disconnect() SYNCHRONOUSLY on the client
        // thread deadlocks ReplayMod's save (channelInactive queues its save
        // setup back onto the very thread we are blocking). Queue the
        // disconnect instead: this call returns immediately, the world
        // unloads on the next client-thread pump, and the master save gets
        // the free thread. await_master_saved owns the wait from here.
        ClientThreadExecutor.Dispatch dispatch = client.dispatch(10_000, () -> {
            MinecraftClient mc = MinecraftClient.getInstance();
            if (mc.world == null) {
                return MiniJson.write(Map.of("ok", false, "reason", "not in a world"));
            }
            stopRequested = true;
            mc.send(() -> {
                // Minecraft's normal exit closes the connection first. Without
                // this, disconnect() waits forever for a still-running server.
                if (mc.world != null) mc.world.disconnect();
                mc.disconnect();
            });
            return MiniJson.write(Map.of("ok", true, "world_left", "queued"));
        });
        return fromDispatch(dispatch, "replay.stop_recording");
    }

    @Override
    public synchronized Map<String, Object> awaitMasterSaved(String timelineId) {
        Path target = ReplayArtifacts.masterPath(replaysDir, timelineId);
        try {
            if (Files.isRegularFile(target)) {
                Map<String,Object> proof = new LinkedHashMap<>(ReplayArtifacts.validate(target));
                proof.put("master_id", timelineId);
                return Map.of("status", "applied", "result", proof);
            }
            if (!timelineId.equals(recordingId) || !stopRequested || recordingPath == null)
                return Map.of("status", "rejected", "error_class", "operation_rejected", "message", "no stopped recording owned by this master");
            Files.createDirectories(replaysDir);
            // The captured listener identifies the exact recording, including native auto-recording.
            // Never open the intermediate recordingPath: native save/rename
            // still owns it and Windows forbids renaming an open ZipFile.
            Path source = Files.isRegularFile(recordingFinalPath) ? recordingFinalPath : recordingRawPath;
            if (Files.isRegularFile(source)) {
                ReplayArtifacts.validateOwned(source, recordingDate);
                Path temporary = Files.createTempFile(replaysDir, timelineId + "-copy-", ".mcpr");
                try (var input = Files.newInputStream(source); var out = Files.newOutputStream(temporary)) {
                    input.transferTo(out);
                }
                ReplayArtifacts.validateOwned(temporary, recordingDate);
                Files.move(temporary, target); // no REPLACE_EXISTING
            } else {
                if (Files.exists(recordingPath))
                    return Map.of("status", "pending", "result", Map.of("state", "native_finalizing"));
                Path recovered = finalizeRawRecording();
                if (recovered == null) return Map.of("status", "pending", "result", Map.of("state", "saving"));
                Files.move(recovered, target); // no REPLACE_EXISTING
            }
            Map<String,Object> proof = new LinkedHashMap<>(ReplayArtifacts.validate(target));
            proof.put("master_id", timelineId);
            recordingId = null;
            return Map.of("status", "applied", "result", proof);
        } catch (IOException error) {
            return Map.of("status", "failed", "error_class", "operation_failed", "message", error.toString(),
                "result", Map.of("recording_file", String.valueOf(recordingPath)));
        }
    }

    /** Pinned-version fallback: writer must be terminated; only the captured recording is eligible. */
    @SuppressWarnings("unchecked")
    private Path finalizeRawRecording() throws IOException {
        // Packet writes and native zip finalization use different workers.
        // saveService termination alone does not prove the finalizer stopped;
        // closing/reading changed files while channelInactive is saving races
        // its zip rename and CRC deletion. Wait for that actual worker to exit.
        for(var entry:Thread.getAllStackTraces().entrySet())
            if(entry.getKey().isAlive())for(var frame:entry.getValue())
                if(frame.getClassName().equals("com.replaymod.recording.packet.PacketListener")
                    && frame.getMethodName().startsWith("lambda$channelInactive"))return null;
        try {
            var field = recordingListener.getClass().getDeclaredField("saveService");
            field.setAccessible(true);
            if (!((java.util.concurrent.ExecutorService) field.get(recordingListener)).isTerminated()) return null;
            // A failed native finalizer may leave buffered packets unflushed.
            // The writer has terminated, so closing its output can no longer race packet writes.
            var outputField = recordingListener.getClass().getDeclaredField("packetOutputStream");
            outputField.setAccessible(true);
            ((java.io.Closeable) outputField.get(recordingListener)).close();
        } catch (ReflectiveOperationException error) { throw new IOException("writer completion unavailable", error); }
        Path changed = recordingPath.resolveSibling(recordingPath.getFileName() + ".tmp").resolve("changed");
        if (!Files.isRegularFile(changed.resolve("recording.tmcpr"))) return null;
        ReplayArtifacts.Packets packets;
        try (var in = Files.newInputStream(changed.resolve("recording.tmcpr"))) { packets = ReplayArtifacts.packets(in); }
        Path temporary = Files.createTempFile(replaysDir, recordingId + "-recovered-", ".mcpr");
        try (var zip = new java.util.zip.ZipOutputStream(Files.newOutputStream(temporary))) {
            try (var paths = Files.walk(changed)) {
                for (Path file : paths.filter(Files::isRegularFile).toList()) {
                    String entry = changed.relativize(file).toString().replace('\\', '/');
                    zip.putNextEntry(new java.util.zip.ZipEntry(entry));
                    if (entry.equals("metaData.json")) {
                        Map<String,Object> meta = (Map<String,Object>) MiniJson.parse(Files.readString(file));
                        meta.put("duration", packets.durationMillis());
                        zip.write(MiniJson.write(meta).getBytes(StandardCharsets.UTF_8));
                    } else Files.copy(file, zip);
                    zip.closeEntry();
                }
            }
        }
        ReplayArtifacts.validate(temporary);
        CinematicBridgeLog.warn("validated recovery from owned stopped recording: " + recordingPath);
        return temporary;
    }

    // -- master lifecycle ----------------------------------------------------------

    @Override
    public synchronized Map<String, Object> openMaster(String timelineId) {
        Path master = ReplayArtifacts.masterPath(replaysDir, timelineId);
        if (!Files.isRegularFile(master)) {
            return Map.of("status", "rejected", "error_class", "asset_missing",
                "message", "no master file: " + master,
                "result", Map.of("master_id", timelineId));
        }
        // startReplay needs the client thread to pump its own setup queue —
        // blocking this dispatch on it starves exactly that queue (the same
        // pattern as stop). Queue and let the watcher observe the handler.
        if (renderJob != null && (renderJob.state.equals("rendering") || renderJob.state.equals("cancelling")))
            return Map.of("status", "rejected", "error_class", "operation_rejected", "message", "renderer busy");
        try { liveMasterHash = (String) ReplayArtifacts.validate(master).get("master_hash"); }
        catch (IOException invalid) { return Map.of("status", "failed", "error_class", "operation_failed", "message", invalid.toString()); }
        if (timelineId.equals(liveMasterId) && liveHandler != null)
            return Map.of("status", "applied", "result", masterStatus().get("result"));
        long generation = ++masterGeneration;
        pendingMasterId = timelineId;
        previousHandler = liveHandler;
        liveMasterId = null;
        liveHandler = null;
        masterError = null;
        pendingFile = null;
        pendingTimeline = null;
        cameraFrames = null;
        ClientThreadExecutor.Dispatch dispatch = client.dispatch(5_000, () -> {
            MinecraftClient mc = MinecraftClient.getInstance();
            if (!mc.isFinishedLoading() || mc.getOverlay() != null)
                return MiniJson.write(Map.of("ok", false, "reason", "client resources are still loading"));
            mc.send(() -> {
                try {
                    if (generation != masterGeneration) return;
                    if (previousHandler != null) previousHandler.endReplay();
                    ReplayFile file = com.replaymod.core.ReplayMod.instance.files.open(master);
                    pendingFile = file;
                    ReplayModReplay.instance.startReplay(file);
                } catch (Throwable error) {
                    masterError = error.toString();
                    CinematicBridgeLog.warn("open_master failed for " + timelineId + ": " + error);
                }
            });
            return MiniJson.write(Map.of("ok", true, "master_id", timelineId,
                "master_file", master.toString(), "state", "loading"));
        });
        return fromDispatch(dispatch, "replay.open_master");
    }

    @Override
    public Map<String,Object> masterStatus() {
        String state = masterError != null ? "failed" : liveHandler != null ? "ready" : pendingMasterId != null ? "loading" : "idle";
        Map<String,Object> result = new LinkedHashMap<>();
        result.put("state", state);
        MinecraftClient mc = MinecraftClient.getInstance();
        result.put("resources_ready", mc.isFinishedLoading() && mc.getOverlay() == null);
        result.put("master_id", liveMasterId != null ? liveMasterId : String.valueOf(pendingMasterId));
        if (liveHandler != null) result.put("master_hash", liveMasterHash);
        if (masterError != null) result.put("error", masterError);
        return Map.of("status", "applied", "result", result);
    }

    @Override
    public synchronized Map<String, Object> replaceCameraTrack(String timelineId, List<Map<String, Object>> keyframes,
                                                  String interpolation) {
        if (!timelineId.equals(liveMasterId) || liveHandler == null) {
            return Map.of("status", "rejected", "error_class", "editor_not_ready",
                "message", "open the master " + timelineId
                    + " and wait for it to load before applying a camera track",
                "result", Map.of("master_id", String.valueOf(liveMasterId)));
        }
        if (renderJob != null && (renderJob.state.equals("rendering") || renderJob.state.equals("cancelling")))
            return Map.of("status", "rejected", "error_class", "operation_rejected", "message", "renderer busy");
        Timeline timeline;
        try {
            timeline = ReplayCameraTimeline.buildTimeline(keyframes, interpolation);
        } catch (IllegalArgumentException error) {
            return Map.of("status", "rejected", "error_class", "validation_failed",
                "message", String.valueOf(error.getMessage()));
        }
        pendingTimeline = timeline;
        cameraFrames = keyframes.stream().map(Map::copyOf).toList();
        cameraInterpolation = interpolation;
        return Map.of("status", "applied", "result", Map.of(
            "master_id", timelineId,
            "keyframes", keyframes.size(),
            "interpolation", interpolation == null ? "smooth" : interpolation));
    }

    /**
     * One path, one keyframe carrying timestamp + camera position + rotation
     * (ReplayMod's own single-path layout). Path time runs on the video
     * millisecond clock; TimestampProperty carries the replay time in
     * milliseconds (ticks × 50 — the binding's single unit assumption).
     */
    // -- rendering -----------------------------------------------------------------

    @Override
    public synchronized Map<String, Object> startRender(String timelineId, int startTick, int endTick,
                                           int width, int height, int fps, String outputPath) {
        if (!timelineId.equals(liveMasterId) || liveHandler == null) {
            return Map.of("status", "rejected", "error_class", "editor_not_ready",
                "message", "render needs the master " + timelineId + " to be loaded",
                "result", Map.of("master_id", String.valueOf(liveMasterId)));
        }
        if (pendingTimeline == null) {
            return Map.of("status", "rejected", "error_class", "validation_failed",
                "message", "apply a camera track before rendering (deterministic camera only)");
        }
        if (outputPath == null || outputPath.isBlank()) {
            return Map.of("status", "rejected", "error_class", "validation_failed",
                "message", "output_path is required");
        }
        if (renderJob != null && (renderJob.state.equals("rendering") || renderJob.state.equals("cancelling")))
            return Map.of("status", "rejected", "error_class", "operation_rejected", "message", "renderer busy");
        Path output = Path.of(outputPath).toAbsolutePath().normalize();
        Path allowed = replaysDir.toAbsolutePath().normalize().getParent().resolve("bridge-renders");
        if (!output.startsWith(allowed) || !output.toString().endsWith(".mp4"))
            return Map.of("status", "rejected", "error_class", "validation_failed", "message", "render output must be inside instance bridge-renders and end in .mp4");
        if (Files.exists(output)) {
            return Map.of("status", "rejected", "error_class", "operation_rejected",
                "message", "output already exists (never overwrite a previous export): " + output);
        }
        if (output.getParent() != null) {
            try {
                Files.createDirectories(output.getParent());
                if (!output.getParent().toRealPath().startsWith(allowed.toRealPath()))
                    throw new IOException("output directory escapes bridge-renders through a link");
            } catch (IOException error) {
                return Map.of("status", "rejected", "error_class", "validation_failed",
                    "message", "output directory not creatable: " + error);
            }
        }
        long durationTicks = (long) endTick - startTick;
        if (durationTicks <= 0) {
            return Map.of("status", "rejected", "error_class", "validation_failed",
                "message", "range must satisfy end_tick > start_tick");
        }
        if (width < 16 || width > 7680 || height < 16 || height > 4320 || width % 2 != 0 || height % 2 != 0 || fps < 1 || fps > 240 || startTick < 0)
            return Map.of("status", "rejected", "error_class", "validation_failed", "message", "invalid render dimensions/fps/range");
        if (durationTicks * fps % 20 != 0)
            return Map.of("status", "rejected", "error_class", "validation_failed", "message", "render range does not produce an integral frame count");
        final Timeline renderTimeline;
        try {
            var proof = ReplayArtifacts.validate(ReplayArtifacts.masterPath(replaysDir, timelineId));
            if (((Number) proof.get("last_packet_ms")).longValue() < endTick * 50L) throw new IllegalArgumentException("range exceeds recorded packets");
            renderTimeline = ReplayCameraTimeline.buildRangeTimeline(cameraFrames, cameraInterpolation, startTick, endTick);
        } catch (IOException | IllegalArgumentException invalid) {
            return Map.of("status", "rejected", "error_class", "validation_failed", "message", invalid.toString());
        }
        final Path temporary = output.resolveSibling(output.getFileName() + ".partial.mp4");
        try {
            Files.createFile(output.resolveSibling(output.getFileName() + ".reserved"));
            if (Files.exists(temporary)) throw new IOException("partial render already exists");
        } catch (IOException collision) {
            return Map.of("status", "rejected", "error_class", "operation_rejected", "message", "output reservation failed: " + collision);
        }
        // MP4_CUSTOM leaves the strings to the GUI; null NPEs inside
        // FFmpegWriter. exportCommand is the ffmpeg executable, and
        // exportArguments is EVERYTHING after it — ReplayMod's own preset
        // (from the pinned jar) splits as: raw BGRA stdin pipeline, then
        // encoder, then output. %FILTERS% stays empty here.
        String ffmpegArgs =
            "-y -f rawvideo -pix_fmt bgra -s %WIDTH%x%HEIGHT% -r %FPS% -i - %FILTERS% "
            + "-an -c:v libx264 -b:v %BITRATE% -pix_fmt yuv420p \"%FILENAME%\"";
        RenderSettings settings = new RenderSettings(
            RenderSettings.RenderMethod.DEFAULT,
            RenderSettings.EncodingPreset.MP4_CUSTOM,
            width, height, fps, 10_000_000,
            temporary.toFile(),
            false, false, false, false, false,
            null, 360, 360, false, false, false,
            RenderSettings.AntiAliasing.NONE,
            "ffmpeg", ffmpegArgs, false);
        // VideoRenderer's constructor initializes RenderSystem state and is
        // legal only on the client thread. Both construction and renderVideo
        // are dispatched there; HTTP status reads remain independent.
        java.util.concurrent.atomic.AtomicReference<VideoRenderer> rendererRef =
            new java.util.concurrent.atomic.AtomicReference<>();
        java.util.concurrent.atomic.AtomicReference<String> failure =
            new java.util.concurrent.atomic.AtomicReference<>();
        ClientThreadExecutor.Dispatch construct = client.dispatch(15_000, () -> {
            try {
                MinecraftClient mc = MinecraftClient.getInstance();
                if (!mc.isFinishedLoading() || mc.getOverlay() != null)
                    throw new IOException("client resources are still loading");
                rendererRef.set(new VideoRenderer(settings, liveHandler, renderTimeline));
                return "ok";
            } catch (IOException error) {
                failure.set("renderer construction failed: " + error);
                return "failed";
            } catch (Throwable error) {
                failure.set("renderer construction threw: " + error);
                return "failed";
            }
        });
        if (construct.outcome() == ClientThreadExecutor.Outcome.UNPROVEN) {
            return Map.of("status", "unknown", "error_class", "operation_timeout_unknown",
                "message", "renderer construction not acknowledged on the client thread",
                "result", Map.of());
        }
        if (failure.get() != null) {
            return Map.of("status", "rejected", "error_class", "export_failed",
                "message", failure.get());
        }
        VideoRenderer renderer = rendererRef.get();
        RenderJob job = new RenderJob(timelineId, output, temporary, renderer);
        job.expectedFrames = Math.toIntExact(durationTicks * fps / 20);
        job.jobId = java.util.UUID.randomUUID().toString();
        renderJob = job;
        // renderVideo drives the replay tick loop and game rendering, so it
        // must own the client thread (ReplayMod's GUI blocks it the same way
        // behind a progress overlay). Queue it; renderStatus stays readable
        // from the HTTP thread via the volatile job state.
        MinecraftClient.getInstance().send(() -> runRender(job));
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("job_id", job.jobId);
        result.put("output", output.toString());
        result.put("expected_frames", durationTicks * fps / 20);
        result.put("state", "rendering");
        return Map.of("status", "applied", "result", result);
    }

    private void runRender(RenderJob job) {
        dev.mcfilm.cinematicbridge.core.FovState.begin();
        try {
            boolean completed = job.renderer.renderVideo();
            job.fovEvidence = dev.mcfilm.cinematicbridge.core.FovState.evidence();
            synchronized (job) {
            if (job.state.equals("cancelling")) {
                job.state = "cancelled";
                return; // cancelRender already owns the terminal state
            }
            if (completed && !job.renderer.hasFailed() && Files.exists(job.temporary) && job.renderer.getFramesDone() == job.expectedFrames) {
                Files.move(job.temporary, job.output);
                job.state = "rendered";
            } else {
                job.state = "failed";
                job.error = job.renderer.hasFailed()
                    ? "renderer reported failure (missing ffmpeg is the usual cause: NoFFmpegException)"
                    : "renderVideo returned false or the output file is absent";
            }
            }
        } catch (Throwable error) {
            job.state = "failed";
            job.error = String.valueOf(error);
        } finally {
            job.fovEvidence = dev.mcfilm.cinematicbridge.core.FovState.evidence();
            dev.mcfilm.cinematicbridge.core.FovState.end();
        }
    }

    @Override
    public Map<String, Object> renderStatus() {
        RenderJob job = renderJob;
        if (job == null) {
            return Map.of("status", "applied", "result", Map.of("state", "idle"));
        }
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("state", job.state);
        result.put("job_id", job.jobId);
        result.put("output", job.output.toString());
        result.put("temporary_output", job.temporary.toString());
        result.put("frames_done", job.renderer.getFramesDone());
        result.put("total_frames", job.renderer.getTotalFrames());
        result.put("has_failed", job.renderer.hasFailed());
        result.put("output_exists", Files.exists(job.output));
        result.put("fov", job.fovEvidence);
        if (job.error != null) {
            result.put("error", job.error);
        }
        return Map.of("status", "applied", "result", result);
    }

    @Override
    public Map<String, Object> cancelRender() {
        RenderJob job = renderJob;
        if (job == null) {
            return Map.of("status", "rejected", "error_class", "operation_rejected",
                "message", "no render job to cancel");
        }
        synchronized (job) {
        if (!job.state.equals("rendering")) {
            return Map.of("status", "rejected", "error_class", "operation_rejected",
                "message", "render job already " + job.state);
        }
        job.state = "cancelling";
        }
        job.renderer.cancel();
        return Map.of("status", "applied", "result", Map.of("state", "cancelling", "job_id", job.jobId));
    }

    // -- helpers -----------------------------------------------------------------

    private static Map<String, Object> fromDispatch(ClientThreadExecutor.Dispatch dispatch, String method) {
        if (dispatch.outcome() == ClientThreadExecutor.Outcome.FAILED) {
            return Map.of("status", "rejected", "error_class", "operation_rejected",
                "message", method + ": " + dispatch.detail());
        }
        if (dispatch.outcome() == ClientThreadExecutor.Outcome.UNPROVEN) {
            return Map.of("status", "unknown", "error_class", "operation_timeout_unknown",
                "message", method + " not acknowledged on the client thread within budget",
                "result", Map.of());
        }
        try {
            Object parsed = MiniJson.parse(dispatch.output());
            @SuppressWarnings("unchecked")
            Map<String, Object> payload = (Map<String, Object>) parsed;
            Map<String, Object> result = new LinkedHashMap<>(payload);
            result.remove("ok");
            if (Boolean.TRUE.equals(payload.get("ok"))) {
                return Map.of("status", "applied", "result", result);
            }
            result.putIfAbsent("reason", "binding reported failure without a reason");
            return Map.of("status", "rejected", "error_class", "operation_rejected",
                "message", method + ": " + result.remove("reason"), "result", result);
        } catch (RuntimeException error) {
            return Map.of("status", "unknown", "error_class", "operation_timeout_unknown",
                "message", method + " reply unreadable: " + error);
        }
    }

}
