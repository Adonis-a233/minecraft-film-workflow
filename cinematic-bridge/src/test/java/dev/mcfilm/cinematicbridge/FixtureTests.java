package dev.mcfilm.cinematicbridge;

import dev.mcfilm.cinematicbridge.json.MiniJson;
import dev.mcfilm.cinematicbridge.json.MiniSchema;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Stream;

/**
 * Contract-v2 fixture suite: consumes the SAME canonical fixtures as the
 * Python suite (agent/tests/test_contract_v2.py) — the shared source of
 * truth (plan v2 §Phase A). Runs pure JDK, offline.
 *
 * Run: java FixtureTests [contracts/v2]
 */
public final class FixtureTests {

    private static int passed = 0;
    private static final List<String> failures = new ArrayList<>();

    public static void main(String[] args) throws Exception {
        Path root = Path.of(args.length > 0 ? args[0] : "contracts/v2");
        Map<String, MiniSchema> schemas = loadSchemas(root);
        check("all five v2 schemas loaded", schemas.size() == 5);

        testRequestFixtures(root, schemas);
        testResultFixtures(root, schemas);
        testStateFixtures(root, schemas);
        testRequiredFieldMutations(root, schemas);
        testSchemaFreeze(root, schemas);

        System.out.println("passed: " + passed + ", failed: " + failures.size());
        failures.forEach(failure -> System.out.println("FAIL " + failure));
        if (!failures.isEmpty()) {
            System.exit(1);
        }
    }

    // -- fixture groups --------------------------------------------------------

    static void testRequestFixtures(Path root, Map<String, MiniSchema> schemas) throws IOException {
        MiniSchema requestSchema = schemas.get("operation-request");
        int valid = 0;
        int malformed = 0;
        for (Path path : listJson(root.resolve("fixtures/requests"))) {
            Map<String, Object> envelope = readEnvelope(path);
            Object request = envelope.get("request");
            boolean ok = requestSchema.isValid(request);
            if (path.getFileName().toString().startsWith("malformed-")) {
                malformed++;
                check("malformed request rejected by Java: " + path.getFileName(), !ok);
            } else {
                valid++;
                check("request validates in Java: " + path.getFileName(), ok);
            }
        }
        check("request fixtures present (>=4 valid, >=3 malformed)", valid >= 4 && malformed >= 3);
    }

    static void testResultFixtures(Path root, Map<String, MiniSchema> schemas) throws IOException {
        MiniSchema resultSchema = schemas.get("operation-result");
        int valid = 0;
        int malformed = 0;
        for (Path path : listJson(root.resolve("fixtures/results"))) {
            Map<String, Object> result = readObject(path);
            boolean ok = resultSchema.isValid(result);
            if (path.getFileName().toString().startsWith("malformed-")) {
                malformed++;
                check("malformed result rejected by Java: " + path.getFileName(), !ok);
            } else {
                valid++;
                check("result validates in Java: " + path.getFileName(), ok);
                if (ok) {
                    check("status agrees with journal_state: " + path.getFileName(),
                        journalAgreesWithStatus(result));
                }
            }
        }
        check("result fixtures present (>=8 valid, >=1 malformed)", valid >= 8 && malformed >= 1);
    }

    static void testStateFixtures(Path root, Map<String, MiniSchema> schemas) throws IOException {
        for (Path path : listJson(root.resolve("fixtures/game-state"))) {
            check("game-state validates in Java: " + path.getFileName(),
                schemas.get("game-state").isValid(readObject(path)));
        }
        check("game-state fixtures present", listJson(root.resolve("fixtures/game-state")).size() >= 3);
        for (Path path : listJson(root.resolve("fixtures/mocap-state"))) {
            check("mocap-state validates in Java: " + path.getFileName(),
                schemas.get("mocap-state").isValid(readObject(path)));
        }
        check("mocap-state fixtures present", listJson(root.resolve("fixtures/mocap-state")).size() >= 5);
        for (Path path : listJson(root.resolve("fixtures/capabilities"))) {
            check("capabilities validate in Java: " + path.getFileName(),
                schemas.get("capabilities").isValid(readObject(path)));
        }
        check("capabilities fixture present", !listJson(root.resolve("fixtures/capabilities")).isEmpty());
    }

    static void testRequiredFieldMutations(Path root, Map<String, MiniSchema> schemas) throws IOException {
        Map<String, Object> envelope = readEnvelope(root.resolve("fixtures/requests/world-set-time.json"));
        @SuppressWarnings("unchecked")
        Map<String, Object> request = (Map<String, Object>) envelope.get("request");
        List<?> requiredRequest = requiredOf(schemas.get("operation-request"));
        check("operation-request declares required fields", !requiredRequest.isEmpty());
        for (Object field : requiredRequest) {
            Map<String, Object> mutated = new LinkedHashMap<>(request);
            mutated.remove(String.valueOf(field));
            check("removing request field fails in Java: " + field,
                !schemas.get("operation-request").isValid(mutated));
        }

        Map<String, Object> result = readObject(root.resolve("fixtures/results/applied-world-set-time.json"));
        List<?> requiredResult = requiredOf(schemas.get("operation-result"));
        check("operation-result requires idempotency_key (F1 guard)",
            requiredResult.contains("idempotency_key"));
        for (Object field : requiredResult) {
            Map<String, Object> mutated = new LinkedHashMap<>(result);
            mutated.remove(String.valueOf(field));
            check("removing result field fails in Java: " + field,
                !schemas.get("operation-result").isValid(mutated));
        }
    }

    static void testSchemaFreeze(Path root, Map<String, MiniSchema> schemas) throws IOException {
        // Contract 1 stays frozen; v2 must not silently redefine it.
        Map<String, Object> v1 = readObject(root.getParent().resolve("v1/operation-request.schema.json"));
        @SuppressWarnings("unchecked")
        Map<String, Object> v1Properties = (Map<String, Object>) v1.get("properties");
        @SuppressWarnings("unchecked")
        Map<String, Object> v1Method = (Map<String, Object>) v1Properties.get("method");
        @SuppressWarnings("unchecked")
        List<Object> v1Methods = (List<Object>) v1Method.get("enum");
        check("v1 keeps its one-shot mocap.start_recording", v1Methods.contains("mocap.start_recording"));
        @SuppressWarnings("unchecked")
        Map<String, Object> v1Version = (Map<String, Object>) v1Properties.get("schema_version");
        Object v1Const = v1Version.get("const");
        check("v1 keeps its schema_version const 1", v1Const instanceof Number number && number.intValue() == 1);
    }

    // -- helpers ----------------------------------------------------------------

    static Map<String, MiniSchema> loadSchemas(Path root) throws IOException {
        Map<String, MiniSchema> schemas = new LinkedHashMap<>();
        for (String name : List.of(
            "operation-request", "operation-result", "capabilities", "game-state", "mocap-state")) {
            schemas.put(name, MiniSchema.of(Files.readString(root.resolve(name + ".schema.json"), StandardCharsets.UTF_8)));
        }
        return schemas;
    }

    /** Recovers the declared required list from a schema via MiniSchema itself. */
    static List<?> requiredOf(MiniSchema schema) {
        List<Object> missing = new ArrayList<>();
        for (String violation : schema.validate(new LinkedHashMap<String, Object>())) {
            if (violation.endsWith(": required property is missing")) {
                String key = violation.substring(0, violation.indexOf(':'));
                missing.add(key);
            }
        }
        return missing;
    }

    static boolean journalAgreesWithStatus(Map<String, Object> result) {
        Object journal = result.get("journal_state");
        Object status = result.get("status");
        if (journal == null) {
            return true;
        }
        return switch (String.valueOf(status)) {
            case "applied", "observed", "failed" -> String.valueOf(journal).equals("observed");
            case "queued" -> String.valueOf(journal).equals("queued");
            case "running" -> String.valueOf(journal).equals("dispatched");
            case "rejected" -> String.valueOf(journal).equals("rejected");
            case "unknown" -> String.valueOf(journal).equals("unknown");
            default -> false;
        };
    }

    static Map<String, Object> readEnvelope(Path path) throws IOException {
        Object parsed = MiniJson.parse(Files.readString(path, StandardCharsets.UTF_8));
        if (!(parsed instanceof Map<?, ?> map) || !(map.get("request") instanceof Map<?, ?>)) {
            throw new IllegalStateException("fixture is not a request envelope: " + path);
        }
        @SuppressWarnings("unchecked")
        Map<String, Object> envelope = (Map<String, Object>) map;
        return envelope;
    }

    static Map<String, Object> readObject(Path path) throws IOException {
        Object parsed = MiniJson.parse(Files.readString(path, StandardCharsets.UTF_8));
        if (!(parsed instanceof Map<?, ?> map)) {
            throw new IllegalStateException("fixture is not a JSON object: " + path);
        }
        @SuppressWarnings("unchecked")
        Map<String, Object> object = (Map<String, Object>) map;
        return object;
    }

    static List<Path> listJson(Path directory) throws IOException {
        if (!Files.isDirectory(directory)) {
            return List.of();
        }
        try (Stream<Path> entries = Files.list(directory)) {
            List<Path> paths = new ArrayList<>();
            entries.filter(path -> path.getFileName().toString().endsWith(".json")).sorted().forEach(paths::add);
            return paths;
        }
    }

    static void check(String name, boolean condition) {
        if (condition) {
            passed++;
        } else {
            failures.add(name);
        }
    }
}
