package dev.mcfilm.cinematicbridge;
import dev.mcfilm.cinematicbridge.actor.*;
import dev.mcfilm.cinematicbridge.json.MiniJson;
import java.nio.file.*;
import java.util.Map;
public final class CoatPickupTests{
 public static void main(String[] args)throws Exception{
  String valid=Files.readString(Path.of("../contracts/v3/fixtures/actor/valid-coat-pickup.json"));ActorPlan.parse(parse(valid));reject(valid.replace("classmate:a","classmate:zhou"));reject(valid.replace("\"action\":\"phone\"","\"action\":\"idle\""));reject(valid.replace("\"action\":\"hold_coat\"","\"action\":\"phone\""));reject(valid.replace("399.55","400.55"));reject(valid.replace("153.98","152.0"));
  var shoulder=new BagPackingMotion.Point(.375f,1.4375f,0);var source=new BagPackingMotion.Point(.45f,1.13f,.57f);
  for(int i=0;i<80;i++){float p=CoatPickupMotion.progress(i,80);var h=CoatPickupMotion.hand(p,source);var j=BagPackingMotion.elbow(shoulder,h);if(Math.abs(dist(shoulder,j)-.375)>.00001||Math.abs(dist(j,h)-.375)>.00001)throw new AssertionError("original arm segment length changed");var c=CoatPickupMotion.coat(p,source);if(CoatPickupMotion.gripped(p)&&dist(h,c)>.00001)throw new AssertionError("coat left holding hand");if(!CoatPickupMotion.gripped(p)&&!c.equals(source))throw new AssertionError("coat moved before contact");}
  if(!CoatPickupMotion.hand(0,source).equals(CoatPickupMotion.REST)||!CoatPickupMotion.hand(1,source).equals(CoatPickupMotion.CARRY))throw new AssertionError("pickup endpoints");System.out.println("CoatPickupTests:6 plan checks and80 arm/attachment samples passed");
  for(int i=0;i<=100;i++){float p=i/100f;var c=CoatPickupMotion.coat(p,source);double angle=-Math.PI/2*(1-CoatPickupMotion.upright(p));for(double y:new double[]{-.75,0})for(double z:new double[]{-.15,.15}){double vy=c.y()+.8*(Math.cos(angle)*y-Math.sin(angle)*z),vz=c.z()+.8*(Math.sin(angle)*y+Math.cos(angle)*z);if(vz>=.55&&vy<.999)throw new AssertionError("coat clipped desk during lift/turn");}}
  System.out.println("CoatPickupTests:101 desk-clearance samples passed");
 }
 private static double dist(BagPackingMotion.Point a,BagPackingMotion.Point b){return Math.sqrt(Math.pow(a.x()-b.x(),2)+Math.pow(a.y()-b.y(),2)+Math.pow(a.z()-b.z(),2));}
 @SuppressWarnings("unchecked")private static Map<String,Object> parse(String s){return (Map<String,Object>)MiniJson.parse(s);}
 private static void reject(String s){try{ActorPlan.parse(parse(s));}catch(IllegalArgumentException expected){return;}throw new AssertionError("unsafe coat plan accepted");}
}
