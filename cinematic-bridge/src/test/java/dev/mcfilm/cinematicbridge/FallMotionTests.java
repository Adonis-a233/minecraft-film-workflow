package dev.mcfilm.cinematicbridge;
import dev.mcfilm.cinematicbridge.actor.FallMotion;
public final class FallMotionTests {
    public static void main(String[] args) {
        float prior=0;
        for(int i=0;i<260;i++) {
            float p=FallMotion.progress(i);
            if(p<prior||p>1||p-prior>.13)throw new AssertionError("fall pose discontinuity");
            if(i>=11&&p!=1)throw new AssertionError("settled fall moved");
            prior=p;
        }
        if(FallMotion.progress(0)>=.1||FallMotion.progress(11)!=1)throw new AssertionError("fall endpoints");
        try{FallMotion.progress(-1);throw new AssertionError("invalid clock");}catch(IllegalArgumentException expected){}
        System.out.println("FallMotionTests:260 monotonic/step/settled pose samples passed");
    }
}
