package dev.mcfilm.cinematicbridge.json;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Minimal JSON parser/serializer so the bridge has zero library dependencies
 * (Minecraft bundles Gson, but the pure core must compile and verify without
 * any runtime at all). Parses to Map/List/String/Double/Boolean/null.
 */
public final class MiniJson {
    private MiniJson() {}

    public static Object parse(String text) {
        Parser parser = new Parser(text);
        Object value = parser.parseValue();
        parser.skipWhitespace();
        if (!parser.atEnd()) {
            throw new IllegalArgumentException("trailing content at offset " + parser.offset);
        }
        return value;
    }

    public static String write(Object value) {
        StringBuilder out = new StringBuilder();
        writeValue(value, out);
        return out.toString();
    }

    private static void writeValue(Object value, StringBuilder out) {
        if (value == null) {
            out.append("null");
        } else if (value instanceof String string) {
            writeString(string, out);
        } else if (value instanceof Boolean || value instanceof Integer || value instanceof Long) {
            out.append(value);
        } else if (value instanceof Double doubleValue) {
            if (doubleValue.isNaN() || doubleValue.isInfinite()) {
                throw new IllegalArgumentException("cannot serialize " + doubleValue);
            }
            out.append(doubleValue);
        } else if (value instanceof Map<?, ?> map) {
            out.append('{');
            boolean first = true;
            for (Map.Entry<?, ?> entry : map.entrySet()) {
                if (!first) {
                    out.append(',');
                }
                first = false;
                writeString(String.valueOf(entry.getKey()), out);
                out.append(':');
                writeValue(entry.getValue(), out);
            }
            out.append('}');
        } else if (value instanceof List<?> list) {
            out.append('[');
            for (int i = 0; i < list.size(); i++) {
                if (i > 0) {
                    out.append(',');
                }
                writeValue(list.get(i), out);
            }
            out.append(']');
        } else {
            throw new IllegalArgumentException("unsupported JSON type: " + value.getClass());
        }
    }

    private static void writeString(String value, StringBuilder out) {
        out.append('"');
        for (int i = 0; i < value.length(); i++) {
            char c = value.charAt(i);
            switch (c) {
                case '"' -> out.append("\\\"");
                case '\\' -> out.append("\\\\");
                case '\n' -> out.append("\\n");
                case '\r' -> out.append("\\r");
                case '\t' -> out.append("\\t");
                default -> {
                    if (c < 0x20) {
                        out.append(String.format("\\u%04x", (int) c));
                    } else {
                        out.append(c);
                    }
                }
            }
        }
        out.append('"');
    }

    private static final class Parser {
        private final String text;
        private int offset;

        Parser(String text) {
            this.text = text;
        }

        boolean atEnd() {
            return offset >= text.length();
        }

        void skipWhitespace() {
            while (offset < text.length() && Character.isWhitespace(text.charAt(offset))) {
                offset++;
            }
        }

        Object parseValue() {
            skipWhitespace();
            if (atEnd()) {
                throw new IllegalArgumentException("unexpected end of JSON");
            }
            char c = text.charAt(offset);
            return switch (c) {
                case '{' -> parseObject();
                case '[' -> parseArray();
                case '"' -> parseString();
                case 't' -> parseKeyword("true", Boolean.TRUE);
                case 'f' -> parseKeyword("false", Boolean.FALSE);
                case 'n' -> parseKeyword("null", null);
                default -> parseNumber();
            };
        }

        private Object parseObject() {
            Map<String, Object> map = new LinkedHashMap<>();
            offset++; // {
            skipWhitespace();
            if (peek() == '}') {
                offset++;
                return map;
            }
            while (true) {
                skipWhitespace();
                String key = parseString();
                skipWhitespace();
                expect(':');
                map.put(key, parseValue());
                skipWhitespace();
                char c = peek();
                if (c == ',') {
                    offset++;
                } else if (c == '}') {
                    offset++;
                    return map;
                } else {
                    throw new IllegalArgumentException("expected , or } at offset " + offset);
                }
            }
        }

        private Object parseArray() {
            List<Object> list = new ArrayList<>();
            offset++; // [
            skipWhitespace();
            if (peek() == ']') {
                offset++;
                return list;
            }
            while (true) {
                list.add(parseValue());
                skipWhitespace();
                char c = peek();
                if (c == ',') {
                    offset++;
                } else if (c == ']') {
                    offset++;
                    return list;
                } else {
                    throw new IllegalArgumentException("expected , or ] at offset " + offset);
                }
            }
        }

        private String parseString() {
            expect('"');
            StringBuilder out = new StringBuilder();
            while (true) {
                char c = text.charAt(offset++);
                if (c == '"') {
                    return out.toString();
                }
                if (c == '\\') {
                    char escape = text.charAt(offset++);
                    switch (escape) {
                        case '"' -> out.append('"');
                        case '\\' -> out.append('\\');
                        case '/' -> out.append('/');
                        case 'n' -> out.append('\n');
                        case 'r' -> out.append('\r');
                        case 't' -> out.append('\t');
                        case 'u' -> {
                            out.append((char) Integer.parseInt(text.substring(offset, offset + 4), 16));
                            offset += 4;
                        }
                        default -> throw new IllegalArgumentException("bad escape \\" + escape);
                    }
                } else {
                    out.append(c);
                }
            }
        }

        private Object parseKeyword(String keyword, Object value) {
            if (text.startsWith(keyword, offset)) {
                offset += keyword.length();
                return value;
            }
            throw new IllegalArgumentException("bad literal at offset " + offset);
        }

        private Object parseNumber() {
            int start = offset;
            while (offset < text.length() && "-+.eE0123456789".indexOf(text.charAt(offset)) >= 0) {
                offset++;
            }
            String raw = text.substring(start, offset);
            if (raw.isEmpty()) {
                throw new IllegalArgumentException("bad number at offset " + start);
            }
            return raw.matches("-?\\d+") ? (Object) Long.parseLong(raw) : (Object) Double.parseDouble(raw);
        }

        private char peek() {
            if (atEnd()) {
                throw new IllegalArgumentException("unexpected end of JSON");
            }
            return text.charAt(offset);
        }

        private void expect(char c) {
            if (atEnd() || text.charAt(offset) != c) {
                throw new IllegalArgumentException("expected '" + c + "' at offset " + offset);
            }
            offset++;
        }
    }
}
