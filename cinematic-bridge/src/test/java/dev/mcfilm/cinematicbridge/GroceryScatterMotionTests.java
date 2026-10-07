package dev.mcfilm.cinematicbridge;
import dev.mcfilm.cinematicbridge.actor.GroceryScatterMotion;

public final class GroceryScatterMotionTests {
    public static void main(String[] args) {
        var opening=GroceryScatterMotion.fromOpening(.328125,.675,.015625,-.55,-.35,0);
        require(opening.x()==.328125&&opening.y()==.675&&opening.z()==.015625,"release must originate at visible bag mouth");
        for(int tick=1;tick<6;tick++){
            var a=GroceryScatterMotion.fromOpening(.328125,.675,.015625,-.55,-.35,tick-1);
            var b=GroceryScatterMotion.fromOpening(.328125,.675,.015625,-.55,-.35,tick);
            var c=GroceryScatterMotion.fromOpening(.328125,.675,.015625,-.55,-.35,tick+1);
            require(Math.abs(c.y()-2*b.y()+a.y()+GroceryScatterMotion.GRAVITY)<1e-12,"bag mouth ballistic acceleration");
        }
        var settled=GroceryScatterMotion.fromOpening(.328125,.675,.015625,-.55,-.35,20);
        require(settled.grounded()&&settled.y()==.0125&&settled.x()==-.55&&settled.z()==-.35,"bag mouth floor contact");
        require(settled.equals(GroceryScatterMotion.fromOpening(.328125,.675,.015625,-.55,-.35,1000)),"bag mouth settled drift");
        for(double height:new double[]{0,3,Double.NaN}){
            try{GroceryScatterMotion.fromOpening(0,height,0,1,1,0);throw new AssertionError("invalid release accepted");}catch(IllegalArgumentException expected){}
        }
        double[][] offsets={{-.55,-.35},{-.15,.50},{.55,.35},{-.65,.25}};
        for(var offset:offsets) {
            var start=GroceryScatterMotion.sample(offset[0],offset[1],0);
            require(start.x()==0&&start.z()==0&&start.y()==.75&&!start.grounded(),"release changed");
            for(int tick=1;tick<Math.floor(GroceryScatterMotion.LANDING_TICK);tick++) {
                var a=GroceryScatterMotion.sample(offset[0],offset[1],tick-1);
                var b=GroceryScatterMotion.sample(offset[0],offset[1],tick);
                var c=GroceryScatterMotion.sample(offset[0],offset[1],tick+1);
                require(Math.abs(c.y()-2*b.y()+a.y()+GroceryScatterMotion.GRAVITY)<1e-12,"airborne acceleration varies");
                require(Math.abs(c.x()-2*b.x()+a.x())<1e-12&&Math.abs(c.z()-2*b.z()+a.z())<1e-12,"horizontal speed varies");
            }
            var land=GroceryScatterMotion.sample(offset[0],offset[1],GroceryScatterMotion.LANDING_TICK);
            require(land.grounded()&&land.x()==offset[0]&&land.z()==offset[1]&&land.y()==.0125,"landing misses support");
            for(int n=0;n<=1000;n++) {
                var p=GroceryScatterMotion.sample(offset[0],offset[1],n/20.);
                require(p.y()>=.0125,"floor penetration");
                if(n/20.>=GroceryScatterMotion.LANDING_TICK)require(p.equals(land),"settled item drift or bounce");
            }
        }
        for(double invalid:new double[]{-1,Double.NaN,Double.POSITIVE_INFINITY}) {
            try{GroceryScatterMotion.sample(.1,.1,invalid);throw new AssertionError("invalid elapsed accepted");}
            catch(IllegalArgumentException expected){}
        }
        System.out.println("GroceryScatterMotionTests: constant acceleration, exact contact and 4004 floor/stability samples passed; landing="+GroceryScatterMotion.LANDING_TICK+" ticks");
    }
    private static void require(boolean ok,String message){if(!ok)throw new AssertionError(message);}
}
