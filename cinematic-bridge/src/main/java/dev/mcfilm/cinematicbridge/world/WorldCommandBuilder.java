package dev.mcfilm.cinematicbridge.world;

/**
 * Deterministic vanilla command strings for typed ops. Placement is always
 * ``keep``; the strings mirror exactly what the Python scene compiler emits
 * so evidence stays comparable across simulation and live runs.
 */
public final class WorldCommandBuilder {

    private WorldCommandBuilder() {
    }

    public static String command(WorldOp op) {
        return switch (op) {
            case WorldOp.SetTime setTime -> "time set " + setTime.value();
            case WorldOp.SetWeather weather -> "weather " + weather.weather() + " "
                + weather.durationSeconds() + "s";
            case WorldOp.SetBlockKeep setBlock -> "setblock " + setBlock.x() + " " + setBlock.y()
                + " " + setBlock.z() + " " + setBlock.block() + " keep";
            case WorldOp.FillKeep fill -> "fill " + fill.start()[0] + " " + fill.start()[1] + " "
                + fill.start()[2] + " " + fill.end()[0] + " " + fill.end()[1] + " " + fill.end()[2]
                + " " + fill.block() + " keep";
            case WorldOp.Summon summon -> {
                if (summon.tag() == null) {
                    yield "summon " + summon.entity() + " " + summon.x() + " "
                        + summon.y() + " " + summon.z();
                }
                yield "summon " + summon.entity() + " " + summon.x() + " "
                    + summon.y() + " " + summon.z() + " {Tags:[\"" + summon.tag() + "\"]}";
            }
        };
    }
}
