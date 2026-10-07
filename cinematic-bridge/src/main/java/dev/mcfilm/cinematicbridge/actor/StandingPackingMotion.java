package dev.mcfilm.cinematicbridge.actor;

/** Chen's fixed standing motion: pull the bag clear of the desk before lowering. */
public final class StandingPackingMotion {
    public static final int DURATION=160;
    public static float progress(int elapsed,int duration){if(duration!=DURATION||elapsed<0||elapsed>=duration)throw new IllegalArgumentException("standing packing requires160ticks");return elapsed/(float)(duration-1);}
    public static final BagPackingMotion.Point REST = point(-.375f,.6875f,0);
    public static final BagPackingMotion.Point BOOK = point(-.5f,1.025f,.60f);
    public static final BagPackingMotion.Point LIFT = point(-.5f,1.24f,.60f);
    public static final BagPackingMotion.Point ABOVE = point(-.2f,1.4f,.62f);
    public static final BagPackingMotion.Point BAG = point(-.2f,1.2f,.62f);
    public static final BagPackingMotion.Point CLEAR = point(-.65f,1.2f,0);
    public static final BagPackingMotion.Point LOWER = point(-.65f,.75f,0);
    public static final BagPackingMotion.Point FLOOR = point(-.65f,.20f,0);
    public static BagPackingMotion.Point hand(float p) {
        check(p);
        if(p<.18f)return mix(REST,BOOK,p/.18f);
        if(p<.36f)return mix(BOOK,LIFT,(p-.18f)/.18f);
        if(p<.60f)return mix(LIFT,ABOVE,(p-.36f)/.24f);
        if(p<.72f)return mix(ABOVE,BAG,(p-.60f)/.12f);
        if(p<.82f)return mix(BAG,CLEAR,(p-.72f)/.10f);
        if(p<.92f)return mix(CLEAR,LOWER,(p-.82f)/.10f);
        return mix(LOWER,REST,(p-.92f)/.08f);
    }
    public static BagPackingMotion.Point bag(float p) {
        check(p);
        if(p<.72f)return BAG;
        if(p<.92f)return hand(p);
        float t=(p-.92f)/.08f;
        return point(FLOOR.x(),LOWER.y()+(FLOOR.y()-LOWER.y())*t*t,FLOOR.z());
    }
    public static BagPackingMotion.Point book(float p) {
        check(p);return p<.18f?BOOK:BagPackingMotion.stored(p)?bag(p):hand(p);
    }
    private static BagPackingMotion.Point point(float x,float y,float z) {return new BagPackingMotion.Point(x,y,z);}
    private static BagPackingMotion.Point mix(BagPackingMotion.Point a,BagPackingMotion.Point b,float t) {
        if(t<=0)return a;if(t>=1)return b;t=t*t*(3-2*t);
        return point(a.x()+(b.x()-a.x())*t,a.y()+(b.y()-a.y())*t,a.z()+(b.z()-a.z())*t);
    }
    private static void check(float p) {if(!Float.isFinite(p)||p<0||p>1)throw new IllegalArgumentException("standing packing progress outside0..1");}
    private StandingPackingMotion() {}
}
