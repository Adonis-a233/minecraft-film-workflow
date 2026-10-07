package dev.mcfilm.cinematicbridge;
import dev.mcfilm.cinematicbridge.actor.ActorPlan;
import dev.mcfilm.cinematicbridge.json.MiniJson;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Map;

public final class SupportPlanTests {
    public static void main(String[] args)throws Exception {
        String valid=Files.readString(Path.of("../contracts/v3/fixtures/actor/valid-support-rise.json"));
        ActorPlan.parse(parse(valid));
        reject(valid.replace("\"actor_ref\":\"CH05\"","\"actor_ref\":\"missing\""));
        reject(valid.replace("\"actor_ref\":\"CH05\"","\"actor_ref\":\"CH04\""));
        reject(valid.replace("classmate:chen","classmate:a"));
        reject(valid.replace("\"duration_ticks\":120","\"duration_ticks\":60").replace("\"start_tick\":160,\"duration_ticks\":40","\"start_tick\":100,\"duration_ticks\":100"));
        reject(valid.replace("\"action\":\"idle\"","\"action\":\"idle\",\"actor_ref\":\"CH05\""));
        String push=Files.readString(Path.of("../contracts/v3/fixtures/actor/valid-push-contact.json"));
        ActorPlan.parse(parse(push));
        reject(push.replace("\"actor_ref\":\"CH05\"","\"actor_ref\":\"missing\""));
        reject(push.replace("classmate:chen","classmate:safety"));
        reject(push.replace("\"duration_ticks\":10","\"duration_ticks\":21").replace("\"start_tick\":50,\"duration_ticks\":70","\"start_tick\":61,\"duration_ticks\":59"));
        reject(push.replace("\"action\":\"idle\"","\"action\":\"reach\""));
        reject(push.replace("\"action\":\"recoil_to\"","\"action\":\"walk_to\""));
        System.out.println("SupportPlanTests: 12 checks passed");
    }
    @SuppressWarnings("unchecked")private static Map<String,Object> parse(String s){return (Map<String,Object>)MiniJson.parse(s);}
    private static void reject(String s){try{ActorPlan.parse(parse(s));}catch(IllegalArgumentException expected){return;}throw new AssertionError("unsafe support plan accepted");}
}
