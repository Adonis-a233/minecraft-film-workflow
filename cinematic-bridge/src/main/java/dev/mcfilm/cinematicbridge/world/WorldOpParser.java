package dev.mcfilm.cinematicbridge.world;

import java.util.List;
import java.util.Map;

/**
 * Parses and FULLY validates typed world-write params (plan v2 §Phase C).
 * Java revalidates everything the Python controller already checked — the
 * two validations are independent defense lines, not trust.
 *
 * Limits (documented in contracts/v2/capabilities.schema.json):
 * per-fill ≤ 32,768 blocks, declared region ≤ 262,144 blocks, x/z within
 * ±30,000,000, y within [-64, 319], time within [0, 24000], resource ids
 * namespaced lowercase. ``replace`` placement does not exist on this surface.
 */
public final class WorldOpParser {

    public static final int MAX_PER_FILL = 32_768;
    public static final int MAX_REGION_BLOCKS = 262_144;
    public static final String RESOURCE_PATTERN = "^[a-z0-9_.-]+:[a-z0-9_./-]+$";

    private WorldOpParser() {
    }

    public static WorldOp parse(String method, Map<String, Object> params) {
        return switch (method) {
            case "world.set_time" -> parseSetTime(params);
            case "world.set_weather" -> parseSetWeather(params);
            case "world.set_block_keep" -> parseSetBlock(params);
            case "world.fill_keep" -> parseFill(params);
            case "world.summon" -> parseSummon(params);
            default -> throw new IllegalArgumentException("unknown world op: " + method);
        };
    }

    public static WorldOp.SetTime parseSetTime(Map<String, Object> params) {
        long value = requireLong(params, "value");
        if (value < 0 || value > 24_000) {
            throw new IllegalArgumentException("value must be within [0, 24000]");
        }
        return new WorldOp.SetTime(value, requireRegion(params));
    }

    public static WorldOp.SetWeather parseSetWeather(Map<String, Object> params) {
        String weather = requireText(params, "weather");
        if (!weather.equals("clear") && !weather.equals("rain") && !weather.equals("thunder")) {
            throw new IllegalArgumentException("weather must be clear|rain|thunder");
        }
        long duration = params.get("duration_seconds") instanceof Number number
            ? number.longValue() : 300;
        if (duration < 1 || duration > 86_400) {
            throw new IllegalArgumentException("duration_seconds must be within [1, 86400]");
        }
        return new WorldOp.SetWeather(weather, duration, requireRegion(params));
    }

    public static WorldOp.SetBlockKeep parseSetBlock(Map<String, Object> params) {
        WorldOp.Box region = requireRegion(params);
        int[] position = requirePoint(params);
        if (!inWorldBounds(position[0], position[1], position[2])) {
            throw new IllegalArgumentException("position escapes world bounds");
        }
        if (!region.contains(position[0], position[1], position[2])) {
            throw new IllegalArgumentException("setblock target escapes the declared build_region");
        }
        if (params.containsKey("preserve_state") && !(params.get("preserve_state") instanceof Boolean))
            throw new IllegalArgumentException("preserve_state must be a boolean");
        return new WorldOp.SetBlockKeep(position[0], position[1], position[2],
            requireBlockState(params, "block"), region, Boolean.TRUE.equals(params.get("preserve_state")));
    }

    public static WorldOp.FillKeep parseFill(Map<String, Object> params) {
        WorldOp.Box region = requireRegion(params);
        WorldOp.Box fill = boxOf(point(params.get("start"), "start"),
            point(params.get("end"), "end"));
        if (fill.blockCount() > MAX_PER_FILL) {
            throw new IllegalArgumentException("fill covers " + fill.blockCount()
                + " blocks; per-fill limit is " + MAX_PER_FILL);
        }
        if (!region.contains(fill)) {
            throw new IllegalArgumentException("fill escapes the declared build_region");
        }
        if (params.containsKey("preserve_state") && !(params.get("preserve_state") instanceof Boolean))
            throw new IllegalArgumentException("preserve_state must be a boolean");
        return new WorldOp.FillKeep(fill.start(), fill.end(), requireResource(params, "block"), region,
            Boolean.TRUE.equals(params.get("preserve_state")));
    }

    public static WorldOp.Summon parseSummon(Map<String, Object> params) {
        WorldOp.Box region = requireRegion(params);
        int[] position = requirePoint(params);
        if (!inWorldBounds(position[0], position[1], position[2])) {
            throw new IllegalArgumentException("position escapes world bounds");
        }
        if (!region.contains(position[0], position[1], position[2])) {
            throw new IllegalArgumentException("summon target escapes the declared build_region");
        }
        // Optional ownership tag (v3): the tag makes the actor uniquely
        // addressable, so the proof never relies on nearby-count heuristics.
        String tag = null;
        if (params.get("tag") != null) {
            tag = requireText(params, "tag");
            if (!tag.matches("[A-Za-z0-9_.+-]{1,64}")) {
                throw new IllegalArgumentException("tag must match [A-Za-z0-9_.+-]{1,64}");
            }
        }
        return new WorldOp.Summon(requireResource(params, "entity"), position[0], position[1],
            position[2], tag, region);
    }

    // -- shared validators ------------------------------------------------------

    public static WorldOp.Box requireRegion(Map<String, Object> params) {
        Object raw = params.get("build_region");
        if (!(raw instanceof Map<?, ?> regionMap)) {
            throw new IllegalArgumentException("build_region is required for every world write");
        }
        @SuppressWarnings("unchecked")
        Map<String, Object> region = (Map<String, Object>) regionMap;
        WorldOp.Box box = boxOf(point(region.get("start"), "build_region.start"),
            point(region.get("end"), "build_region.end"));
        if (box.blockCount() > MAX_REGION_BLOCKS) {
            throw new IllegalArgumentException("build_region covers " + box.blockCount()
                + " blocks; region limit is " + MAX_REGION_BLOCKS);
        }
        for (int[] corner : List.of(box.start(), box.end())) {
            if (!inWorldBounds(corner[0], corner[1], corner[2])) {
                throw new IllegalArgumentException("build_region escapes world bounds");
            }
        }
        return box;
    }

    public static String requireResource(Map<String, Object> params, String key) {
        String value = requireText(params, key);
        if (!value.matches(RESOURCE_PATTERN)) {
            throw new IllegalArgumentException(key + " must be a namespaced resource id");
        }
        return value;
    }

    public static String requireBlockState(Map<String,Object> params,String key) {
        String value=requireText(params,key);
        if (!value.matches("[a-z0-9_.-]+:[a-z0-9_./-]+(\\[[a-z0-9_]+=[a-z0-9_.-]+(,[a-z0-9_]+=[a-z0-9_.-]+)*\\])?"))
            throw new IllegalArgumentException("invalid block state syntax");
        int start=value.indexOf('[');
        if (start>=0) {
            var keys=new java.util.HashSet<String>();
            for (String pair:value.substring(start+1,value.length()-1).split(","))
                if (!keys.add(pair.split("=")[0])) throw new IllegalArgumentException("duplicate block property");
        }
        return value;
    }

    public static String requireText(Map<String, Object> params, String key) {
        if (!(params.get(key) instanceof String text) || text.isBlank()) {
            throw new IllegalArgumentException(key + " must be a non-blank string");
        }
        return text;
    }

    public static long requireLong(Map<String, Object> params, String key) {
        if (!(params.get(key) instanceof Number number)) {
            throw new IllegalArgumentException(key + " must be a number");
        }
        return number.longValue();
    }

    public static int[] requirePoint(Map<String, Object> params) {
        return point(params, "position");
    }

    public static int[] point(Object raw, String what) {
        if (!(raw instanceof Map<?, ?> rawMap)) {
            throw new IllegalArgumentException(what + " must be an object {x, y, z}");
        }
        @SuppressWarnings("unchecked")
        Map<String, Object> map = (Map<String, Object>) rawMap;
        return new int[]{
            intOf(map.get("x"), what + ".x"),
            intOf(map.get("y"), what + ".y"),
            intOf(map.get("z"), what + ".z")};
    }

    public static boolean inWorldBounds(int x, int y, int z) {
        return x >= -30_000_000 && x <= 30_000_000
            && y >= -64 && y <= 319
            && z >= -30_000_000 && z <= 30_000_000;
    }

    private static WorldOp.Box boxOf(int[] start, int[] end) {
        return new WorldOp.Box(start, end);
    }

    private static int intOf(Object value, String what) {
        if (!(value instanceof Number number) || number.doubleValue() != number.longValue()) {
            throw new IllegalArgumentException(what + " must be an integer");
        }
        return number.intValue();
    }
}
