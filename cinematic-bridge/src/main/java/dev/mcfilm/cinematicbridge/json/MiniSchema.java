package dev.mcfilm.cinematicbridge.json;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * Minimal JSON Schema (draft 2020-12 subset) validator, pure JDK. Exists so
 * the bridge can validate the SAME canonical contract-v2 fixtures the Python
 * suite consumes (plan v2 §Phase A): the two languages must not be allowed to
 * drift. Supports exactly the keywords our contracts use — anything unknown
 * is ignored, anything unsupported in a NEW contract must be added here, never
 * silently assumed.
 *
 * Supported: type (string or array), required, properties,
 * additionalProperties:false, const, enum, pattern, minLength, maxLength,
 * minimum, maximum, items, minItems, maxItems.
 */
public final class MiniSchema {
    private final Map<String, Object> schema;

    private MiniSchema(Map<String, Object> schema) {
        this.schema = schema;
    }

    public static MiniSchema of(String schemaJson) {
        return new MiniSchema(asMap(MiniJson.parse(schemaJson), "<schema>"));
    }

    /** Returns one human-readable violation per failure; empty means valid. */
    public List<String> validate(Object instance) {
        List<String> errors = new ArrayList<>();
        check(schema, instance, "", errors);
        return errors;
    }

    public boolean isValid(Object instance) {
        return validate(instance).isEmpty();
    }

    @SuppressWarnings("unchecked")
    private void check(Map<String, Object> schemaNode, Object value, String path, List<String> errors) {
        Object type = schemaNode.get("type");
        if (type != null && !matchesType(type, value)) {
            errors.add((path.isEmpty() ? "<root>" : path) + ": expected type " + type + ", got " + describe(value));
            return;
        }
        Object constant = schemaNode.get("const");
        if (constant != null && !jsonEquals(constant, value)) {
            errors.add((path.isEmpty() ? "<root>" : path) + ": expected const " + MiniJson.write(constant)
                + ", got " + MiniJson.write(value));
        }
        Object enumeration = schemaNode.get("enum");
        if (enumeration instanceof List<?> options) {
            boolean member = false;
            for (Object option : options) {
                if (jsonEquals(option, value)) {
                    member = true;
                    break;
                }
            }
            if (!member) {
                errors.add((path.isEmpty() ? "<root>" : path) + ": " + MiniJson.write(value)
                    + " is not one of " + MiniJson.write(options));
            }
        }
        if (value instanceof String string) {
            checkString(schemaNode, string, path, errors);
        } else if (value instanceof Number number) {
            checkNumber(schemaNode, number, path, errors);
        } else if (value instanceof Map<?, ?> map) {
            checkObject(schemaNode, (Map<String, Object>) map, path, errors);
        } else if (value instanceof List<?> list) {
            checkArray(schemaNode, list, path, errors);
        }
    }

    @SuppressWarnings("unchecked")
    private void checkObject(Map<String, Object> schemaNode, Map<String, Object> map, String path,
                             List<String> errors) {
        if (schemaNode.get("additionalProperties") instanceof Boolean strict
            && !strict && schemaNode.get("properties") instanceof Map<?, ?> properties) {
            for (String key : map.keySet()) {
                if (!properties.containsKey(key)) {
                    errors.add(path(key, path) + ": unexpected property");
                }
            }
        }
        if (schemaNode.get("required") instanceof List<?> required) {
            for (Object requiredKey : required) {
                if (!map.containsKey(String.valueOf(requiredKey))) {
                    errors.add(path(String.valueOf(requiredKey), path) + ": required property is missing");
                }
            }
        }
        if (schemaNode.get("properties") instanceof Map<?, ?> properties) {
            for (Map.Entry<?, ?> entry : properties.entrySet()) {
                String key = String.valueOf(entry.getKey());
                if (map.containsKey(key) && entry.getValue() instanceof Map<?, ?> childSchema) {
                    check((Map<String, Object>) childSchema, map.get(key), path(key, path), errors);
                }
            }
        }
    }

    private void checkArray(Map<String, Object> schemaNode, List<?> list, String path, List<String> errors) {
        if (schemaNode.get("minItems") instanceof Number minimum && list.size() < minimum.intValue()) {
            errors.add((path.isEmpty() ? "<root>" : path) + ": fewer than " + minimum + " items");
        }
        if (schemaNode.get("maxItems") instanceof Number maximum && list.size() > maximum.intValue()) {
            errors.add((path.isEmpty() ? "<root>" : path) + ": more than " + maximum + " items");
        }
        if (schemaNode.get("items") instanceof Map<?, ?> rawItemSchema) {
            Map<String, Object> itemSchema = castSchema(rawItemSchema);
            for (int i = 0; i < list.size(); i++) {
                check(itemSchema, list.get(i), path + "[" + i + "]", errors);
            }
        }
    }

    private void checkString(Map<String, Object> schemaNode, String value, String path, List<String> errors) {
        if (schemaNode.get("minLength") instanceof Number minimum && value.length() < minimum.intValue()) {
            errors.add((path.isEmpty() ? "<root>" : path) + ": shorter than minLength " + minimum);
        }
        if (schemaNode.get("maxLength") instanceof Number maximum && value.length() > maximum.intValue()) {
            errors.add((path.isEmpty() ? "<root>" : path) + ": longer than maxLength " + maximum);
        }
        if (schemaNode.get("pattern") instanceof String pattern && !value.matches(pattern)) {
            errors.add((path.isEmpty() ? "<root>" : path) + ": " + describe(value) + " does not match " + pattern);
        }
    }

    private void checkNumber(Map<String, Object> schemaNode, Number value, String path, List<String> errors) {
        if (schemaNode.get("minimum") instanceof Number minimum && value.doubleValue() < minimum.doubleValue()) {
            errors.add((path.isEmpty() ? "<root>" : path) + ": below minimum " + minimum);
        }
        if (schemaNode.get("maximum") instanceof Number maximum && value.doubleValue() > maximum.doubleValue()) {
            errors.add((path.isEmpty() ? "<root>" : path) + ": above maximum " + maximum);
        }
    }

    private static boolean matchesType(Object type, Object value) {        if (type instanceof List<?> options) {
            for (Object option : options) {
                if (matchesOneType(String.valueOf(option), value)) {
                    return true;
                }
            }
            return false;
        }
        return matchesOneType(String.valueOf(type), value);
    }

    private static boolean matchesOneType(String type, Object value) {
        return switch (type) {
            case "object" -> value instanceof Map;
            case "array" -> value instanceof List;
            case "string" -> value instanceof String;
            case "boolean" -> value instanceof Boolean;
            case "integer" -> value instanceof Long || value instanceof Integer;
            case "number" -> value instanceof Number;
            case "null" -> value == null;
            default -> false;
        };
    }

    private static boolean jsonEquals(Object left, Object right) {
        if (left instanceof Number leftNumber && right instanceof Number rightNumber) {
            return leftNumber.doubleValue() == rightNumber.doubleValue();
        }
        return left == null ? right == null : left.equals(right);
    }

    private static String path(String key, String parent) {
        return parent.isEmpty() ? key : parent + "/" + key;
    }

    private static String describe(Object value) {
        if (value == null) {
            return "null";
        }
        if (value instanceof String string) {
            return "\"" + (string.length() > 40 ? string.substring(0, 40) + "…" : string) + "\"";
        }
        return value.getClass().getSimpleName();
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> castSchema(Object raw) {
        return (Map<String, Object>) raw;
    }

    private static Map<String, Object> asMap(Object parsed, String what) {
        if (!(parsed instanceof Map<?, ?> map)) {
            throw new IllegalArgumentException(what + " is not a JSON object");
        }
        @SuppressWarnings("unchecked")
        Map<String, Object> result = (Map<String, Object>) map;
        return result;
    }
}
