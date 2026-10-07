package dev.mcfilm.cinematicbridge.actor;

/** Standing right-hand pickup. Fixed carry anchor and bounded source collar anchor. */
public final class CoatPickupMotion {
    public static final BagPackingMotion.Point REST=new BagPackingMotion.Point(.375f,.6875f,0);
    public static final BagPackingMotion.Point CARRY=new BagPackingMotion.Point(.6f,1.28f,.10f);
    public static float progress(int elapsed,int duration){if(duration<60||duration>100||elapsed<0||elapsed>=duration)throw new IllegalArgumentException("coat pickup clock outside bound");return elapsed/(float)(duration-1);}
    public static boolean gripped(float p){check(p);return p>=.35f;}
    public static BagPackingMotion.Point hand(float p,BagPackingMotion.Point source){check(p);var lift=new BagPackingMotion.Point(source.x(),1.75f,source.z());var pull=new BagPackingMotion.Point(.6f,1.75f,.10f);return p<.35f?mix(REST,source,p/.35f):p<.55f?mix(source,lift,(p-.35f)/.20f):p<.70f?mix(lift,pull,(p-.55f)/.15f):mix(pull,CARRY,(p-.70f)/.20f);}
    public static BagPackingMotion.Point coat(float p,BagPackingMotion.Point source){return gripped(p)?hand(p,source):source;}
    public static float upright(float p){check(p);return Math.min(1,Math.max(0,(p-.70f)/.20f));}
    private static BagPackingMotion.Point mix(BagPackingMotion.Point a,BagPackingMotion.Point b,float p){if(p<=0)return a;if(p>=1)return b;p=p*p*(3-2*p);return new BagPackingMotion.Point(a.x()+(b.x()-a.x())*p,a.y()+(b.y()-a.y())*p,a.z()+(b.z()-a.z())*p);}
    private static void check(float p){if(!Float.isFinite(p)||p<0||p>1)throw new IllegalArgumentException("coat progress outside0..1");}
    private CoatPickupMotion(){}
}
