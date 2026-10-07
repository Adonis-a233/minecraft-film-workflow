package dev.mcfilm.cinematicbridge.actor;

/** Fixed local-space book/bag motion. No user-controlled geometry or item IDs. */
public final class BagPackingMotion {
    public record Point(float x,float y,float z) {}
    public static final Point REST=new Point(-.375f,.61777f,.31696f);
    public static final Point BOOK=new Point(-.3f,.865f,.60f);
    public static final Point LIFT=new Point(-.3f,1.08f,.60f);
    public static final Point BAG_ABOVE=new Point(-.2f,1.24f,.62f);
    public static final Point BAG=new Point(-.2f,1.04f,.62f);
    public static final Point BAG_LOWER=new Point(-.5f,.70f,.20f);
    public static final Point BAG_FLOOR=new Point(-.5f,.20f,.20f);
    public static float progress(int elapsed,int duration){if(duration<80||duration>120||elapsed<0||elapsed>=duration)throw new IllegalArgumentException("packing clock outside bound");return elapsed/(float)(duration-1);}
    public static boolean stored(float p){check(p);return p>=.72f;}
    public static Point hand(float p){
        check(p);
        if(p<.18f)return mix(REST,BOOK,p/.18f);
        if(p<.36f)return mix(BOOK,LIFT,(p-.18f)/.18f);
        if(p<.60f)return mix(LIFT,BAG_ABOVE,(p-.36f)/.24f);
        if(p<.72f)return mix(BAG_ABOVE,BAG,(p-.60f)/.12f);
        if(p<.92f)return mix(BAG,BAG_LOWER,(p-.72f)/.20f);
        return mix(BAG_LOWER,REST,(p-.92f)/.08f);
    }
    public static Point bag(float p){check(p);if(p<.72f)return BAG;if(p<.92f)return hand(p);float t=(p-.92f)/.08f;return new Point(BAG_FLOOR.x,BAG_LOWER.y+(BAG_FLOOR.y-BAG_LOWER.y)*t*t,BAG_FLOOR.z);}
    public static Point book(float p){check(p);return p<.18f?BOOK:stored(p)?bag(p):hand(p);}
    public static Point elbow(Point shoulder,Point hand){
        return elbow(shoulder,hand,false);
    }
    public static Point elbowLateral(Point shoulder,Point hand){return elbow(shoulder,hand,true);}
    private static Point elbow(Point shoulder,Point hand,boolean lateral){
        double x=hand.x-shoulder.x,y=hand.y-shoulder.y,z=hand.z-shoulder.z,d=Math.sqrt(x*x+y*y+z*z);
        if(!Double.isFinite(d)||d>.75001||d<.01)throw new IllegalArgumentException("packing reach outside two .375-block segments");
        x/=d;y/=d;z/=d;double bx=lateral?-1+x*x:x*y,by=lateral?x*y:-1+y*y,bz=lateral?x*z:z*y,n=Math.sqrt(bx*bx+by*by+bz*bz);
        if(n<.001){if(lateral)throw new IllegalArgumentException("packing lateral elbow pole singular");bx=1;by=0;bz=0;n=1;}double k=Math.sqrt(Math.max(0,.375*.375-d*d/4))/n;
        return new Point((float)((shoulder.x+hand.x)/2+bx*k),(float)((shoulder.y+hand.y)/2+by*k),(float)((shoulder.z+hand.z)/2+bz*k));
    }
    private static Point mix(Point a,Point b,float t){t=Math.min(1,Math.max(0,t));t=t*t*(3-2*t);return new Point(a.x+(b.x-a.x)*t,a.y+(b.y-a.y)*t,a.z+(b.z-a.z)*t);}
    private static void check(float p){if(!Float.isFinite(p)||p<0||p>1)throw new IllegalArgumentException("packing progress outside0..1");}
    private BagPackingMotion() {}
}
