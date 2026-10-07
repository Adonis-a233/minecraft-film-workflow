package dev.mcfilm.cinematicbridge.actor;
import org.joml.Quaternionf;
import org.joml.Vector3f;

/** Fixed low squat geometry; props remain on the road until the selected hand contacts them. */
public final class GroceryPickupMotion {
    public static final int DURATION=400,CYCLE=90,ENTRY=20;
    public static final float PALM_OFFSET=.17f;
    public static final float HIP=.25f;
    public static final float LEAN=(float)Math.toRadians(80);
    public static final float SHOULDER_Y=HIP+.6875f*(float)Math.cos(LEAN);
    public static final float SHOULDER_Z=.6875f*(float)Math.sin(LEAN);
    private static final float[][] SOURCES={{-.55f,.0125f,.05f},{-.15f,.0125f,.90f},{.55f,.0125f,.75f},{-.65f,.0125f,.65f}};
    public static BagPackingMotion.Point bag(){return point(0,.275f,1.2f);}
    public static BagPackingMotion.Point bagEntry(){return point(0,.72f,1.2f);}
    public static BagPackingMotion.Point storedHand(){return point(0,.445f,1.2f);}
    public static boolean left(int index){checkIndex(index);return index!=2;}
    public static BagPackingMotion.Point shoulder(boolean left){return point(left?-.375f:.375f,SHOULDER_Y,SHOULDER_Z);}
    public static BagPackingMotion.Point rest(boolean left){return point(left?-.5f:.5f,.22f,.5f);}
    public static BagPackingMotion.Point source(int index){checkIndex(index);var v=SOURCES[index];return point(v[0],v[1],v[2]);}
    public static boolean gripped(float p){check(p);return p>=.3f&&p<.8f;}
    public static boolean collected(float p){check(p);return p>=.8f;}
    public static BagPackingMotion.Point hand(int index,float p){
        check(p);var rest=rest(left(index));var source=source(index);var item=point(source.x(),source.y()+PALM_OFFSET,source.z());var lifted=point(item.x(),item.y()+.35f,item.z());
        if(p<.3f)return mix(rest,item,p/.3f);
        if(p<.4f)return mix(item,lifted,(p-.3f)/.1f);
        if(p<.65f)return mix(lifted,bagEntry(),(p-.4f)/.25f);
        if(p<.8f)return mix(bagEntry(),storedHand(),(p-.65f)/.15f);
        var clear=point(rest.x(),.22f,.9f);
        if(p<.9f)return mix(storedHand(),clear,(p-.8f)/.1f);
        return mix(clear,rest,(p-.9f)/.1f);
    }
    public static BagPackingMotion.Point item(int index,float p){check(p);if(!gripped(p)&&!collected(p))return source(index);var h=hand(index,Math.min(p,.8f));return point(h.x(),h.y()-PALM_OFFSET,h.z());}
    public static float upright(float p){check(p);float t=Math.max(0,Math.min(1,(p-.4f)/.25f));return t*t*(3-2*t);}
    public static final class ElbowFrame {
        private Vector3f direction,bend;
        public BagPackingMotion.Point solve(BagPackingMotion.Point shoulder,BagPackingMotion.Point hand){
        Vector3f d=new Vector3f(hand.x()-shoulder.x(),hand.y()-shoulder.y(),hand.z()-shoulder.z());float length=d.length();
        if(!Float.isFinite(length)||length<.01f||length>.75001f)throw new IllegalArgumentException("grocery reach outside original arms");
        d.div(length);
        Vector3f pole;
        if(direction==null){pole=new Vector3f(0,1,0).sub(new Vector3f(d).mul(d.y));}
        else{
            if(direction.dot(d)<-.99f)throw new IllegalArgumentException("grocery hand direction reverses in one tick");
            pole=new Quaternionf().rotationTo(direction,d).transform(new Vector3f(bend));
            pole.sub(new Vector3f(d).mul(pole.dot(d)));
        }
        if(pole.lengthSquared()<.01f)throw new IllegalArgumentException("grocery elbow pole is singular");
        pole.normalize();
        float radius=(float)Math.sqrt(Math.max(0,.375*.375-length*length/4));
        Vector3f up=new Vector3f(0,1,0).sub(new Vector3f(d).mul(d.y));float upLength=up.length();
        if(upLength>.001f){
            up.div(upLength);float phi=(float)Math.atan2(d.dot(new Vector3f(up).cross(pole)),up.dot(pole));
            float adjustment=Math.max(-(float)Math.toRadians(8),Math.min((float)Math.toRadians(8),-phi));
            phi+=adjustment;
            // Account for the original forearm's width, not just center points.
            float minimum=(Math.max(.26f,.50f-hand.y())-(shoulder.y()+hand.y())/2)/(radius*upLength);
            if(minimum>1.0001f)throw new IllegalArgumentException("grocery elbow cannot clear the floor: "+shoulder+" "+hand+" ratio="+minimum);
            float limit=(float)Math.acos(Math.max(-1,Math.min(1,minimum)));
            phi=Math.max(-limit,Math.min(limit,phi));
            pole=new Quaternionf().fromAxisAngleRad(d,phi).transform(new Vector3f(up));
        }
        direction=new Vector3f(d);bend=new Vector3f(pole);pole.mul(radius);
        return point((shoulder.x()+hand.x())/2+pole.x,(shoulder.y()+hand.y())/2+pole.y,(shoulder.z()+hand.z())/2+pole.z);
        }
    }
    /** Transport the prior bone frame by its minimal swing; preserve wrist roll. */
    public static Quaternionf rotation(Vector3f from,Vector3f to,Quaternionf previous){
        Vector3f y=new Vector3f(from).sub(to).normalize();
        Vector3f priorY=new Quaternionf(previous).transform(new Vector3f(0,1,0));
        if(priorY.dot(y)<-.99f)throw new IllegalArgumentException("grocery bone direction reverses in one tick");
        return new Quaternionf().rotationTo(priorY,y).mul(previous).normalize();
    }
    private static BagPackingMotion.Point point(float x,float y,float z){return new BagPackingMotion.Point(x,y,z);}
    private static BagPackingMotion.Point mix(BagPackingMotion.Point a,BagPackingMotion.Point b,float t){if(t<=0)return a;if(t>=1)return b;t=t*t*(3-2*t);return point(a.x()+(b.x()-a.x())*t,a.y()+(b.y()-a.y())*t,a.z()+(b.z()-a.z())*t);}
    private static void checkIndex(int i){if(i<0||i>=4)throw new IllegalArgumentException("unregistered grocery index");}
    private static void check(float p){if(!Float.isFinite(p)||p<0||p>1)throw new IllegalArgumentException("pickup phase outside0..1");}
    private GroceryPickupMotion(){}
}
