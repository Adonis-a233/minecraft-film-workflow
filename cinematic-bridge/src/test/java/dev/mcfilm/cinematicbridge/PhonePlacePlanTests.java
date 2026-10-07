package dev.mcfilm.cinematicbridge;
import dev.mcfilm.cinematicbridge.actor.ActorPlan;
import dev.mcfilm.cinematicbridge.json.MiniJson;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Map;
public final class PhonePlacePlanTests {
    public static void main(String[] args)throws Exception{
        String valid=Files.readString(Path.of("../contracts/v3/fixtures/actor/valid-phone-place.json"));ActorPlan.parse(parse(valid));
        reject(valid.replace("classmate:chen","classmate:filmer"));
        reject(valid.replace("\"action\":\"phone_call_sit\"","\"action\":\"phone_sit\""));
        reject(valid.replace("\"action\":\"phone_place_sit\"","\"action\":\"phone_place_sit\",\"actor_ref\":\"CH04\""));
        reject(valid.replace("\"y\":2.025625","\"y\":2.5"));
        reject(valid.replace("\"z\":117.17","\"z\":118.0"));
        reject(valid.replace("\"action\":\"sit\"","\"action\":\"phone_sit\""));
        reject(valid.replace("\"start_tick\":60,\"duration_ticks\":60","\"start_tick\":60,\"duration_ticks\":39").replace("\"start_tick\":120,\"duration_ticks\":80","\"start_tick\":99,\"duration_ticks\":101"));
        reject(valid.replace("\"start_tick\":60,\"duration_ticks\":60","\"start_tick\":60,\"duration_ticks\":81").replace("\"start_tick\":120,\"duration_ticks\":80","\"start_tick\":141,\"duration_ticks\":59"));
        System.out.println("PhonePlacePlanTests: 9 checks passed");
    }
    @SuppressWarnings("unchecked")private static Map<String,Object> parse(String s){return (Map<String,Object>)MiniJson.parse(s);}
    private static void reject(String s){try{ActorPlan.parse(parse(s));}catch(IllegalArgumentException expected){return;}throw new AssertionError("unsafe phone placement accepted");}
}
