package dev.mcfilm.cinematicbridge.replay;

import com.replaymod.replaystudio.pathing.property.AbstractProperty;
import com.replaymod.replaystudio.pathing.property.AbstractPropertyPart;
import com.replaymod.replaystudio.pathing.property.PropertyPart;
import com.google.gson.stream.JsonReader;
import com.google.gson.stream.JsonWriter;
import dev.mcfilm.cinematicbridge.core.FovState;
import java.io.IOException;
import java.util.Collection;
import java.util.List;

/** Pinned ReplayStudio has no native FOV property; supply an interpolatable one. */
public final class ReplayFovProperty extends AbstractProperty<Double> {
    public static final ReplayFovProperty PROPERTY = new ReplayFovProperty();
    private final PropertyPart<Double> part = new AbstractPropertyPart<Double>(this,true) {
        public double toDouble(Double value) { return value; }
        public Double fromDouble(Double old, double value) { return value; }
    };
    private ReplayFovProperty() { super("mcfilm_fov","Field of view",null,70.0); }
    public Collection<PropertyPart<Double>> getParts() { return List.of(part); }
    public void applyToGame(Double value,Object handler) { FovState.set(value); }
    public void toJson(JsonWriter writer,Double value) throws IOException { writer.value(value); }
    public Double fromJson(JsonReader reader) throws IOException { return reader.nextDouble(); }
}
