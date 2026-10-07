package dev.mcfilm.cinematicbridge;
import dev.mcfilm.cinematicbridge.actor.ActorPlan;
import dev.mcfilm.cinematicbridge.json.MiniJson;
import java.nio.file.*;
import java.util.*;
public final class MouthPlanTests {
 @SuppressWarnings("unchecked")static Map<String,Object> parse(String s){return (Map<String,Object>)MiniJson.parse(s);}
 @SuppressWarnings("unchecked")static Map<String,Object> actor(Map<String,Object> m){return (Map<String,Object>)((List<?>)m.get("actors")).getFirst();}
 static void reject(Map<String,Object> m){try{ActorPlan.parse(m);}catch(IllegalArgumentException ok){return;}throw new AssertionError("invalid mouth track accepted");}
 public static void main(String[] args)throws Exception{
  String src=Files.readString(Path.of("../contracts/v3/fixtures/actor/valid-mouth-frames.json"));var plan=ActorPlan.parse(parse(src));if(plan.actors().getFirst().mouthFrames().size()!=200)throw new AssertionError();
  for(Object bad:List.of(-1,3,true,"1",1.5)){var m=parse(src);actor(m).put("mouth_frames",Collections.nCopies(200,bad));reject(m);}
  for(int len:List.of(199,201)){var m=parse(src);actor(m).put("mouth_frames",Collections.nCopies(len,0));reject(m);}
  var m=parse(src);actor(m).put("skin_ref",null);actor(m).put("steps",List.of(Map.of("start_tick",0,"duration_ticks",200,"action","idle")));reject(m);
  m=parse(src);actor(m).remove("mouth_frames");if(!ActorPlan.parse(m).actors().getFirst().mouthFrames().isEmpty())throw new AssertionError();
  System.out.println("MouthPlanTests: 10 checks passed");
 }
}
