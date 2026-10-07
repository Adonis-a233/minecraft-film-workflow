package dev.mcfilm.cinematicbridge;
import dev.mcfilm.cinematicbridge.server.*;
import dev.mcfilm.cinematicbridge.replay.*;
import dev.mcfilm.cinematicbridge.flash.FlashbackDisabledPort;
import dev.mcfilm.cinematicbridge.core.VersionGate;
import java.nio.file.*;
import java.util.*;

public final class ReplayMutationTests {
    static int calls;
    static class Port implements ReplayPort {
        public String backendName(){return "replaymod";}
        public boolean enabled(){return true;}
        public String disabledReason(){return "";}
        public Map<String,Object> startRecording(String id){calls++;return Map.of("status","applied","result",Map.of("master_id",id));}
        public Map<String,Object> stopRecording(String id){return startRecording(id);}
        public Map<String,Object> awaitMasterSaved(String id){return Map.of("status","pending","result",Map.of());}
        public Map<String,Object> openMaster(String id){return startRecording(id);}
        public Map<String,Object> replaceCameraTrack(String id,List<Map<String,Object>> keys,String interpolation){return startRecording(id);}
        public Map<String,Object> startRender(String id,int s,int e,int w,int h,int f,String p){return startRecording(id);}
        public Map<String,Object> renderStatus(){return Map.of("status","applied","result",Map.of("state","rendered"));}
        public Map<String,Object> cancelRender(){return startRecording("cancel");}
    }
    static BridgeDispatcher dispatcher(PersistentJournal journal) {
        return new BridgeDispatcher(command->"",new FlashbackDisabledPort(),()->Map.of(),
            VersionGate.RuntimeVersions.of("1.21.1","0.19.3","0.39.8","1.3.10"),
            new OperationJournal(),null,null,null,1,0,journal,null,new Port());
    }
    public static void main(String[] args) throws Exception {
        Path path=Files.createTempDirectory("replay-mutations");
        var journal=PersistentJournal.open(path);var d=dispatcher(journal);
        var params=Map.<String,Object>of("timeline_id","test");
        var first=d.handle("replay.start_recording",params,3,"run/start");
        var replay=d.handle("replay.start_recording",params,3,"run/start");
        if (calls!=1 || !first.equals(replay)) throw new AssertionError("duplicate execution");
        var conflict=d.handle("replay.stop_recording",params,3,"run/start");
        if (!"operation_conflict".equals(conflict.get("error_class"))) throw new AssertionError("method conflict");
        var reopened=dispatcher(PersistentJournal.open(path));
        if (!first.equals(reopened.handle("replay.start_recording",params,3,"run/start")) || calls!=1)
            throw new AssertionError("restart reexecuted");
        var status=reopened.handle("bridge.get_operation_status",Map.of("idempotency_key","run/start"),3,"read");
        if (!"succeeded".equals(status.get("status"))) throw new AssertionError("missing replay status");
        var missing=d.handle("replay.open_master",params,3,"run/open-missing");
        if (!"validation_failed".equals(missing.get("error_class")) || calls!=1)
            throw new AssertionError("missing hash mutated replay");
        var mismatch=d.handle("replay.open_master",Map.of("timeline_id","test","master_hash","wrong"),3,"run/open-wrong");
        if (!"validation_failed".equals(mismatch.get("error_class")) || calls!=1)
            throw new AssertionError("mismatched hash mutated replay");
        System.out.println("Replay mutation journal: 6 checks passed");
    }
}
