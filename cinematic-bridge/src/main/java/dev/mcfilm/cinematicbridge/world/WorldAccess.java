package dev.mcfilm.cinematicbridge.world;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Read/execute surface the Minecraft client implements (pure interface; the
 * mod binds it to the loaded world, tests bind a fake). Reads exist so every
 * write can be PROVEN by observation — a command that was merely dispatched
 * is never reported as applied.
 */
public interface WorldAccess {

    boolean blockExists(String blockId);

    boolean entityTypeExists(String entityTypeId);

    /** True only when an entity spawned here will be tracked by identity reads. */
    default boolean entityPositionReady(int x, int y, int z) { return false; }

    String blockAt(int x, int y, int z);
    default String blockStateAt(int x,int y,int z) { return blockAt(x,y,z); }
    default String canonicalBlockState(String state) { return blockExists(state) ? state : null; }

    /** How many blocks of the given id sit inside the box (inclusive). */
    long countBlocks(String blockId, int[] start, int[] end);

    long timeOfDay();

    boolean raining();

    boolean thundering();

    default double rainGradient() { return -1; }
    default double thunderGradient() { return -1; }

    /** Entities of the given type within the axis-aligned radius box. */
    long countEntities(String entityTypeId, int x, int y, int z, int radius);

    /** UUIDs of the given entity type in the radius box (identity-level proof). */
    default java.util.List<String> entityIds(String entityTypeId, int x, int y, int z, int radius) {
        throw new UnsupportedOperationException("entity identity reads require a game-backed world");
    }

    /** UUID of the first entity carrying this scoreboard tag, or null. */
    default String firstEntityWithTag(String tag) {
        throw new UnsupportedOperationException("entity tag reads require a game-backed world");
    }

    /** Positions whose state is air (any air variant) inside the box. */
    default long countAir(int[] start, int[] end) {
        return countBlocks("minecraft:air", start, end);
    }

    /**
     * Runs one vanilla slash command (no leading slash) on the client thread.
     * Output is the command's own observable effect — this returns nothing
     * about success; every write PROVES itself through the read methods.
     */
    void runCommand(String command);

    /** Static schematic placement: keep existing cells; preserve the authored state. */
    default void setBlockKeepExact(int x,int y,int z,String state) {
        throw new UnsupportedOperationException("exact schematic placement requires a game-backed world");
    }

    default void fillKeepExact(int[] start,int[] end,String state) {
        for (int y=Math.min(start[1],end[1]);y<=Math.max(start[1],end[1]);y++)
            for (int z=Math.min(start[2],end[2]);z<=Math.max(start[2],end[2]);z++)
                for (int x=Math.min(start[0],end[0]);x<=Math.max(start[0],end[0]);x++) {
                    String before=blockAt(x,y,z);
                    if (before.equals("minecraft:air") || before.equals("minecraft:cave_air") || before.equals("minecraft:void_air"))
                        setBlockKeepExact(x,y,z,state);
                }
    }

    static Map<String, Object> proof(String key, Object value) {
        Map<String, Object> map = new LinkedHashMap<>();
        map.put(key, value);
        return map;
    }
}
