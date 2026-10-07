package dev.mcfilm.cinematicbridge.world;

import java.util.Map;

/**
 * Typed world writes (plan v2 §Phase C). There is deliberately NO free-form
 * command operation: the surface is closed over exactly the actions the
 * scene compiler owns, all ``keep``-placement — ``replace`` stays disabled.
 */
public sealed interface WorldOp permits WorldOp.SetTime, WorldOp.SetWeather,
    WorldOp.SetBlockKeep, WorldOp.FillKeep, WorldOp.Summon {

    /** Declared region this write must stay inside (validated by the parser). */
    Box buildRegion();

    record SetTime(long value, Box buildRegion) implements WorldOp {
    }

    record SetWeather(String weather, long durationSeconds, Box buildRegion) implements WorldOp {
    }

    record SetBlockKeep(int x, int y, int z, String block, Box buildRegion, boolean preserveState) implements WorldOp {
        public SetBlockKeep(int x, int y, int z, String block, Box buildRegion) { this(x,y,z,block,buildRegion,false); }
    }

    record FillKeep(int[] start, int[] end, String block, Box buildRegion, boolean preserveState) implements WorldOp {
        public FillKeep(int[] start,int[] end,String block,Box buildRegion) { this(start,end,block,buildRegion,false); }
        public long blockCount() {
            return (long) (Math.abs(end[0] - start[0]) + 1)
                * (Math.abs(end[1] - start[1]) + 1)
                * (Math.abs(end[2] - start[2]) + 1);
        }
    }

    record Summon(String entity, int x, int y, int z, String tag, Box buildRegion) implements WorldOp {
        /** Legacy shape: no ownership tag (count-based proof only). */
        public Summon(String entity, int x, int y, int z, Box buildRegion) {
            this(entity, x, y, z, null, buildRegion);
        }
    }

    /** Closed axis-aligned integer box. */
    record Box(int[] start, int[] end) {

        public static Box of(int x1, int y1, int z1, int x2, int y2, int z2) {
            return new Box(new int[]{x1, y1, z1}, new int[]{x2, y2, z2});
        }

        public long blockCount() {
            return (long) (Math.abs(end[0] - start[0]) + 1)
                * (Math.abs(end[1] - start[1]) + 1)
                * (Math.abs(end[2] - start[2]) + 1);
        }

        public boolean contains(int x, int y, int z) {
            return x >= Math.min(start[0], end[0]) && x <= Math.max(start[0], end[0])
                && y >= Math.min(start[1], end[1]) && y <= Math.max(start[1], end[1])
                && z >= Math.min(start[2], end[2]) && z <= Math.max(start[2], end[2]);
        }

        public boolean contains(Box other) {
            return contains(other.start[0], other.start[1], other.start[2])
                && contains(other.end[0], other.end[1], other.end[2]);
        }

        public Map<String, Object> toMap() {
            java.util.Map<String, Object> map = new java.util.LinkedHashMap<>();
            map.put("start", point(start));
            map.put("end", point(end));
            return map;
        }

        private static Map<String, Object> point(int[] p) {
            Map<String, Object> map = new java.util.LinkedHashMap<>();
            map.put("x", p[0]);
            map.put("y", p[1]);
            map.put("z", p[2]);
            return map;
        }
    }
}
