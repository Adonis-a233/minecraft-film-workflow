package dev.mcfilm.cinematicbridge;
import dev.mcfilm.cinematicbridge.actor.ActorPlan;
import dev.mcfilm.cinematicbridge.json.MiniJson;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Map;
public final class PhoneStopPlanTests {
    public static void main(String[] args)throws Exception{
        String valid=Files.readString(Path.of("../contracts/v3/fixtures/actor/valid-phone-stop.json"));
        ActorPlan.parse(parse(valid));
        reject(valid.replace("classmate:filmer","classmate:chen"));
        reject(valid.replace("\"action\":\"phone\"","\"action\":\"idle\""));
        reject(valid.replace("\"action\":\"phone\"","\"action\":\"phone_sit\""));
        reject(valid.replace("\"duration_ticks\":40","\"duration_ticks\":29").replace("\"start_tick\":100,\"duration_ticks\":100","\"start_tick\":89,\"duration_ticks\":111"));
        reject(valid.replace("\"duration_ticks\":40","\"duration_ticks\":61").replace("\"start_tick\":100,\"duration_ticks\":100","\"start_tick\":121,\"duration_ticks\":79"));
        reject(valid.replace("\"action\":\"phone_stop\"","\"action\":\"phone_stop\",\"actor_ref\":\"CH05\""));
        System.out.println("PhoneStopPlanTests: 7 checks passed");
    }
    @SuppressWarnings("unchecked")private static Map<String,Object> parse(String s){return (Map<String,Object>)MiniJson.parse(s);}
    private static void reject(String s){try{ActorPlan.parse(parse(s));}catch(IllegalArgumentException expected){return;}throw new AssertionError("unsafe phone stop accepted");}
}
