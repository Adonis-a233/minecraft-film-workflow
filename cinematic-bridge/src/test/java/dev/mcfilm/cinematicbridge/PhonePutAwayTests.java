package dev.mcfilm.cinematicbridge;
import dev.mcfilm.cinematicbridge.actor.ActorPlan;
import dev.mcfilm.cinematicbridge.actor.PhonePutAwayMotion;
import dev.mcfilm.cinematicbridge.json.MiniJson;
import java.nio.file.*;
import java.util.Map;
public final class PhonePutAwayTests {
    public static void main(String[] args)throws Exception{
        String valid=Files.readString(Path.of("../contracts/v3/fixtures/actor/valid-phone-putaway.json"));
        ActorPlan.parse(parse(valid));
        ActorPlan.parse(parse(valid.replace("phone_sit","phone").replace("phone_putaway_sit","phone_putaway").replace("\"action\":\"sit\"","\"action\":\"idle\"")));
        reject(valid.replace("classmate:zhou","classmate:chen"));
        reject(valid.replace("\"action\":\"phone_sit\"","\"action\":\"phone\""));
        reject(valid.replace("\"action\":\"sit\"","\"action\":\"idle\""));
        reject(valid.replace("\"duration_ticks\":40","\"duration_ticks\":29").replace("\"start_tick\":100,\"duration_ticks\":100","\"start_tick\":89,\"duration_ticks\":111"));
        reject(valid.replace("\"duration_ticks\":40","\"duration_ticks\":61").replace("\"start_tick\":100,\"duration_ticks\":100","\"start_tick\":121,\"duration_ticks\":79"));
        float previous=-1;
        for(int t=0;t<40;t++){
            float p=PhonePutAwayMotion.progress(t,40),a=PhonePutAwayMotion.lowering(p);
            if(a<previous)throw new AssertionError("lowering is not monotonic");previous=a;
            if(!PhonePutAwayMotion.visible(p)&&a!=1)throw new AssertionError("phone hidden before hand reaches side");
        }
        if(PhonePutAwayMotion.lowering(0)!=0||PhonePutAwayMotion.lowering(1)!=1||PhonePutAwayMotion.visible(1))throw new AssertionError("bad endpoint");
        System.out.println("PhonePutAwayTests: 7 plan checks and40 motion samples passed");
    }
    @SuppressWarnings("unchecked")private static Map<String,Object> parse(String s){return (Map<String,Object>)MiniJson.parse(s);}
    private static void reject(String s){try{ActorPlan.parse(parse(s));}catch(IllegalArgumentException expected){return;}throw new AssertionError("unsafe put-away accepted");}
}
