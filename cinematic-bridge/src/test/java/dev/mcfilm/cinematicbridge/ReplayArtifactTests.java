package dev.mcfilm.cinematicbridge;
import dev.mcfilm.cinematicbridge.replay.ReplayArtifacts;
import dev.mcfilm.cinematicbridge.server.PersistentJournal;
import java.io.*;
import java.nio.file.*;
import java.util.Map;
import java.util.zip.*;

public final class ReplayArtifactTests {
    public static void main(String[] args) throws Exception {
        Path root = Files.createTempDirectory("replay-artifacts");
        byte[] valid;
        try (var buffer = new ByteArrayOutputStream(); var out = new DataOutputStream(buffer)) {
            out.writeInt(0); out.writeInt(1); out.writeByte(1);
            out.writeInt(11000); out.writeInt(2); out.writeShort(2);
            valid = buffer.toByteArray();
        }
        Path good = root.resolve("good.mcpr");
        zip(good, valid, 11000);
        if (!ReplayArtifacts.validate(good).get("packet_count").equals(2)) throw new AssertionError("packet count");
        ReplayArtifacts.validateOwned(good, 123L);
        try { ReplayArtifacts.validateOwned(good, 456L); throw new AssertionError("accepted another recording"); }
        catch (IOException expected) {}
        Path bad = root.resolve("truncated.mcpr");
        zip(bad, java.util.Arrays.copyOf(valid, valid.length-1), 11000);
        try { ReplayArtifacts.validate(bad); throw new AssertionError("accepted truncation"); }
        catch (IOException expected) {}
        Path wrongTime = root.resolve("wrong-time.mcpr"); zip(wrongTime, valid, 150000);
        try { ReplayArtifacts.validate(wrongTime); throw new AssertionError("accepted false duration"); }
        catch (IOException expected) {}
        try { ReplayArtifacts.masterPath(root, "../other"); throw new AssertionError("path escape"); }
        catch (IllegalArgumentException expected) {}
        Path ledger = root.resolve("ledger"); var journal = PersistentJournal.open(ledger);
        journal.begin("test/key", "replay.start_render", "hash"); journal.markRunning("test/key");
        journal.markSucceeded("test/key", Map.of("job_id", "job"));
        Files.writeString(ledger.resolve(PersistentJournal.FILE_NAME), "{\"torn", StandardOpenOption.APPEND);
        var once = PersistentJournal.open(ledger);
        var twice = PersistentJournal.open(ledger);
        if (twice.get("test/key").orElseThrow().state() != PersistentJournal.State.SUCCEEDED)
            throw new AssertionError("second restart lost recovered journal");
        if (args.length > 0) {
            try { ReplayArtifacts.validate(Path.of(args[0])); throw new AssertionError("historical truncated master accepted"); }
            catch (IOException expected) { System.out.println("historical master rejected: " + expected); }
        }
        System.out.println("Replay artifacts: 8 checks passed");
    }
    static void zip(Path target, byte[] packets, int duration) throws IOException {
        try (var out = new ZipOutputStream(Files.newOutputStream(target))) {
            out.putNextEntry(new ZipEntry("metaData.json"));
            out.write(("{\"fileFormat\":\"MCPR\",\"date\":123,\"duration\":" + duration + "}").getBytes()); out.closeEntry();
            out.putNextEntry(new ZipEntry("recording.tmcpr")); out.write(packets); out.closeEntry();
        }
    }
}
