package dev.mcfilm.cinematicbridge;
import dev.mcfilm.cinematicbridge.actor.MouthModels;
import dev.mcfilm.cinematicbridge.json.MiniJson;
import java.util.*;
import java.util.zip.*;
import java.nio.file.*;
public final class MouthModelTests {
 @SuppressWarnings("unchecked")public static void main(String[] args)throws Exception{
  try(var zip=new ZipFile("../assets/resourcepacks/characters-v12-1.21.1.zip")){
   var models=(Map<String,Object>)MiniJson.parse(new String(zip.getInputStream(zip.getEntry("assets/minecraft/models/item/stick.json")).readAllBytes(),java.nio.charset.StandardCharsets.UTF_8));
   var overrides=(List<Map<String,Object>>)models.get("overrides");int checks=0;
   for(String role:List.of("a","zhou","teacher","chen","elder","filmer","safety"))for(int frame=0;frame<3;frame++){
    int id=MouthModels.modelData(role,frame);String selected=null;
    for(var entry:overrides){var predicate=(Map<String,Object>)entry.get("predicate");if(((Number)predicate.get("custom_model_data")).intValue()<=id)selected=(String)entry.get("model");}
    String expected="kanjian2:actor/"+role+"/head"+(frame==0?"":"_mouth_"+frame);if(!expected.equals(selected))throw new AssertionError(role+" mouth"+frame+" selected "+selected);checks++;
   }
   System.out.println("MouthModelTests: "+checks+" actual resource pack selections passed");
  }
 }
}
