package dev.mcfilm.cinematicbridge.replay;

import dev.mcfilm.cinematicbridge.json.MiniJson;
import java.io.*;
import java.nio.file.*;
import java.security.MessageDigest;
import java.util.*;
import java.util.zip.*;

/** Validates pinned MCPR packet framing without loading Minecraft. Never repairs a truncated stream. */
public final class ReplayArtifacts {
    private ReplayArtifacts() {}
    public record Packets(int count, int durationMillis) {}

    public static Packets packets(InputStream source) throws IOException {
        var in = new DataInputStream(new BufferedInputStream(source));
        int count = 0, last = 0;
        byte[] buffer = new byte[65536];
        while (true) {
            int first = in.read();
            if (first == -1) break;
            int time = (first << 24) | (in.readUnsignedByte() << 16)
                | (in.readUnsignedByte() << 8) | in.readUnsignedByte();
            int length = in.readInt();
            if (time < last || length <= 0 || length > 16 * 1024 * 1024)
                throw new IOException("invalid packet header at packet " + count);
            int remaining = length;
            while (remaining > 0) {
                int read = in.read(buffer, 0, Math.min(buffer.length, remaining));
                if (read < 0) throw new EOFException("truncated packet " + count);
                remaining -= read;
            }
            last = time;
            count++;
        }
        if (count == 0 || last <= 0) throw new IOException("empty recording");
        return new Packets(count, last);
    }

    @SuppressWarnings("unchecked")
    public static Map<String, Object> validate(Path file) throws IOException {
        try (ZipFile zip = new ZipFile(file.toFile())) {
            var metaEntry = zip.getEntry("metaData.json");
            var packetEntry = zip.getEntry("recording.tmcpr");
            if (metaEntry == null || packetEntry == null) throw new IOException("required MCPR entries missing");
            Map<String,Object> meta;
            try (var in = zip.getInputStream(metaEntry)) {
                meta = (Map<String,Object>) MiniJson.parse(new String(in.readAllBytes(), java.nio.charset.StandardCharsets.UTF_8));
            }
            if (!"MCPR".equals(meta.get("fileFormat"))) throw new IOException("not MCPR metadata");
            Packets parsed;
            try (var in = zip.getInputStream(packetEntry)) { parsed = packets(in); }
            int duration = ((Number) meta.get("duration")).intValue();
            if (duration < parsed.durationMillis() || duration - parsed.durationMillis() > 2000)
                throw new IOException("metadata duration disagrees with recorded packet timestamps");
            // Read every entry, independently verifying CRC instead of just the central directory.
            for (var entry : Collections.list(zip.entries())) {
                if (entry.isDirectory()) continue;
                var crc = new CRC32();
                try (var in = zip.getInputStream(entry)) {
                    byte[] buffer = new byte[65536];
                    int read;
                    while ((read = in.read(buffer)) >= 0) crc.update(buffer, 0, read);
                }
                if (crc.getValue() != entry.getCrc()) throw new IOException("CRC mismatch: " + entry.getName());
            }
            return Map.of("master_file", file.toAbsolutePath().toString(), "master_hash", hash(file),
                "duration_ms", duration, "last_packet_ms", parsed.durationMillis(),
                "packet_count", parsed.count(), "size_bytes", Files.size(file),
                "recording_date_ms", ((Number) meta.getOrDefault("date", 0L)).longValue());
        } catch (RuntimeException bad) { throw new IOException("invalid replay metadata", bad); }
    }

    public static Map<String, Object> validateOwned(Path file, long recordingDate) throws IOException {
        var proof = validate(file);
        if (recordingDate <= 0 || !proof.get("recording_date_ms").equals(recordingDate))
            throw new IOException("native replay does not belong to captured recording");
        return proof;
    }

    public static String hash(Path file) throws IOException {
        try {
            var digest = MessageDigest.getInstance("SHA-256");
            try (var in = Files.newInputStream(file)) {
                byte[] buffer = new byte[65536]; int read;
                while ((read = in.read(buffer)) >= 0) digest.update(buffer, 0, read);
            }
            return "sha256:" + HexFormat.of().formatHex(digest.digest());
        } catch (java.security.NoSuchAlgorithmException impossible) { throw new AssertionError(impossible); }
    }

    public static Path masterPath(Path root, String id) {
        if (id == null || !id.matches("[A-Za-z0-9_.-]{1,96}") || id.equals(".") || id.equals(".."))
            throw new IllegalArgumentException("invalid master id");
        return root.toAbsolutePath().normalize().resolve(id + ".mcpr");
    }
}
