package dev.mcfilm.cinematicbridge;
import dev.mcfilm.cinematicbridge.actor.ActorPlan;
import dev.mcfilm.cinematicbridge.actor.BagPackingMotion;
import dev.mcfilm.cinematicbridge.json.MiniJson;
import java.nio.file.*;
import java.util.Map;
public final class BagPackingTests {
    public static void main(String[] args)throws Exception{
        String valid=Files.readString(Path.of("../contracts/v3/fixtures/actor/valid-bag-packing.json"));ActorPlan.parse(parse(valid));ActorPlan.parse(parse(valid.replace("classmate:zhou","classmate:a")));
        reject(valid.replace("classmate:zhou","classmate:chen"));reject(valid.replace("\"action\":\"sit\"","\"action\":\"phone_sit\""));reject(valid.replace("\"duration_ticks\":100","\"duration_ticks\":79").replace("\"start_tick\":120,\"duration_ticks\":80","\"start_tick\":99,\"duration_ticks\":101"));reject(valid.replace("\"duration_ticks\":100","\"duration_ticks\":121").replace("\"start_tick\":120,\"duration_ticks\":80","\"start_tick\":141,\"duration_ticks\":59"));
        boolean hidden=false;
        for(int tick=0;tick<100;tick++){
            float p=BagPackingMotion.progress(tick,100);var h=BagPackingMotion.hand(p);double distance=Math.sqrt(Math.pow(h.x()+.375,2)+Math.pow(h.y()-1.2975,2)+Math.pow(h.z(),2));if(distance>.75001||distance<.01)throw new AssertionError("hand outside original arm length");
            var shoulder=new BagPackingMotion.Point(-.375f,1.2975f,0);var joint=BagPackingMotion.elbow(shoulder,h);
            if(Math.abs(dist(shoulder,joint)-.375)>.00001||Math.abs(dist(joint,h)-.375)>.00001)throw new AssertionError("original upper/forearm length changed");
            var b=BagPackingMotion.book(p);if(p>=.18f&&!BagPackingMotion.stored(p)&&(b.x()!=h.x()||b.y()!=h.y()||b.z()!=h.z()))throw new AssertionError("book left hand before storage");
            if(hidden&&!BagPackingMotion.stored(p))throw new AssertionError("book reappeared");hidden=BagPackingMotion.stored(p);
            if(hidden&&!b.equals(BagPackingMotion.bag(p)))throw new AssertionError("stored book left moving bag");
            if(p>=.72f&&p<.92f&&!h.equals(BagPackingMotion.bag(p)))throw new AssertionError("bag left holding hand");
            if(BagPackingMotion.bag(p).y()<.20f)throw new AssertionError("bag went through floor");
        }
        if(!BagPackingMotion.hand(0).equals(BagPackingMotion.REST)||!BagPackingMotion.hand(1).equals(BagPackingMotion.REST))throw new AssertionError("packing rest endpoints differ");
        if(dist(BagPackingMotion.bag(1),BagPackingMotion.BAG_FLOOR)>.00001)throw new AssertionError("bag did not settle beside chair");
        float lastY=BagPackingMotion.BAG_LOWER.y();for(int i=92;i<=100;i++){float y=BagPackingMotion.bag(i/100f).y();if(y>lastY+.00001)throw new AssertionError("released bag rose");lastY=y;}
        System.out.println("BagPackingTests:6 plan checks and100 geometry/attachment/storage samples passed");
    }
    private static double dist(BagPackingMotion.Point a,BagPackingMotion.Point b){return Math.sqrt(Math.pow(a.x()-b.x(),2)+Math.pow(a.y()-b.y(),2)+Math.pow(a.z()-b.z(),2));}
    @SuppressWarnings("unchecked")private static Map<String,Object> parse(String s){return (Map<String,Object>)MiniJson.parse(s);}
    private static void reject(String s){try{ActorPlan.parse(parse(s));}catch(IllegalArgumentException expected){return;}throw new AssertionError("unsafe packing plan accepted");}
}
