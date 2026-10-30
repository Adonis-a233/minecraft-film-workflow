package dev.mcfilm.cinematicbridge.actor;

import org.joml.Vector3f;

/** Two original .375-block bones; hand approaches before contact carries load. */
public final class ContactEntryMotion {
    public record Frame(Vector3f shoulder,Vector3f elbow,Vector3f hand,float progress){}
    public static Frame sample(Vector3f fromShoulder,Vector3f fromElbow,Vector3f fromHand,
                               Vector3f toShoulder,Vector3f toElbow,Vector3f toHand,float progress){
        float t=Math.max(0,Math.min(1,progress));t=t*t*(3-2*t);
        Vector3f shoulder=new Vector3f(fromShoulder).lerp(toShoulder,t);
        Vector3f hand=new Vector3f(fromHand).lerp(toHand,t);
        Vector3f d=new Vector3f(hand).sub(shoulder);float length=d.length();
        if(!Float.isFinite(length)||length<.001f||length>.75001f)throw new IllegalArgumentException("contact approach exceeds original reach: "+length);
        d.div(length);
        Vector3f mid=new Vector3f(shoulder).add(hand).mul(.5f);
        Vector3f pole=new Vector3f(fromElbow).lerp(toElbow,t).sub(mid);
        pole.sub(new Vector3f(d).mul(pole.dot(d)));
        if(pole.lengthSquared()<1e-8f){pole.set(0,0,1).sub(new Vector3f(d).mul(d.z));}
        if(pole.lengthSquared()<1e-8f){pole.set(1,0,0).sub(new Vector3f(d).mul(d.x));}
        Vector3f elbow=new Vector3f(mid).add(pole.normalize().mul((float)Math.sqrt(Math.max(0,.375*.375-length*length/4))));
        return new Frame(shoulder,elbow,hand,t);
    }
    private ContactEntryMotion(){}
}
