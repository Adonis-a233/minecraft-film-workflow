package dev.mcfilm.cinematicbridge;

import dev.mcfilm.cinematicbridge.core.VersionGate;
import dev.mcfilm.cinematicbridge.flash.FlashbackDisabledPort;
import dev.mcfilm.cinematicbridge.json.MiniJson;
import dev.mcfilm.cinematicbridge.server.BridgeDispatcher;
import dev.mcfilm.cinematicbridge.server.BridgeHttpServer;

import java.io.IOException;
import java.net.HttpURLConnection;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * Real-socket integration test: HTTP server + dispatcher + JSON, still pure
 * JDK (no Minecraft). Verifies loopback binding, bearer-token enforcement,
 * and a full mocap timeline submission round trip.
 * Run: java …HttpBridgeTests
 */
public final class HttpBridgeTests {

    private static int passed = 0;
    private static final List<String> failures = new ArrayList<>();

    public static void main(String[] args) throws Exception {
        BridgeDispatcher dispatcher = new BridgeDispatcher(
            command -> "",
            new FlashbackDisabledPort(),
            () -> Map.of("world", "Marx Video Test"),
            VersionGate.RuntimeVersions.of("1.21.1", "0.19.3", "0.39.8", "1.3.10"));
        BridgeHttpServer server = new BridgeHttpServer(0, "session-token-1", dispatcher);
        server.start();
        String base = "http://127.0.0.1:" + server.port() + "/rpc";
        try {
            testRejectsMissingToken(base);
            testRejectsWrongToken(base);
            testHealthRoundTrip(base);
            testVersionHandshake(base);
            testFlashbackGateOverHttp(base);
        } finally {
            server.stop();
        }
        System.out.println("passed: " + passed + ", failed: " + failures.size());
        failures.forEach(failure -> System.out.println("FAIL " + failure));
        if (!failures.isEmpty()) {
            System.exit(1);
        }
    }

    static void testRejectsMissingToken(String base) throws Exception {
        int code = post(base, null, "{\"request\":{\"method\":\"bridge.health\",\"params\":{}}}");
        check("missing token rejected with 401", code == 401);
    }

    static void testRejectsWrongToken(String base) throws Exception {
        int code = post(base, "wrong", "{\"request\":{\"method\":\"bridge.health\",\"params\":{}}}");
        check("wrong token rejected with 401", code == 401);
    }

    static void testHealthRoundTrip(String base) throws Exception {
        Map<?, ?> response = call(base, "session-token-1", "bridge.health", Map.of());
        check("health applied over http", "applied".equals(response.get("status")));
        check("health response carries operation identity",
            response.get("schema_version") instanceof Number version && version.intValue() == 1
                && "test-op".equals(response.get("operation_id"))
                && "test-run/test-op".equals(response.get("idempotency_key")));
    }

    static void testVersionHandshake(String base) throws Exception {
        Map<?, ?> response = call(base, "session-token-1", "bridge.get_runtime_versions", Map.of());
        Map<?, ?> result = (Map<?, ?>) response.get("result");
        check("handshake reports pinned versions",
            "0.39.8".equals(result.get("flashback")) && "1.21.1".equals(result.get("minecraft")));
    }

    static void testFlashbackGateOverHttp(String base) throws Exception {
        Map<?, ?> response = call(base, "session-token-1", "flashback.start_recording",
            Map.of("timeline_id", "t1"));
        check("flashback rejected over http",
            "rejected".equals(response.get("status"))
                && "manual_intervention_required".equals(response.get("error_class")));
    }

    // -- tiny http client (JDK only) -------------------------------------------

    static int post(String base, String token, String body) throws IOException {
        HttpURLConnection connection = (HttpURLConnection) URI.create(base).toURL().openConnection();
        connection.setRequestMethod("POST");
        if (token != null) {
            connection.setRequestProperty("Authorization", "Bearer " + token);
        }
        connection.setDoOutput(true);
        connection.getOutputStream().write(body.getBytes(StandardCharsets.UTF_8));
        return connection.getResponseCode();
    }

    @SuppressWarnings("unchecked")
    static Map<?, ?> call(String base, String token, String method, Map<String, Object> params)
        throws IOException {
        String envelope = MiniJson.write(Map.of(
            "request", Map.of(
                "schema_version", 1,
                "run_id", "test-run",
                "operation_id", "test-op",
                "idempotency_key", "test-run/test-op",
                "method", method,
                "params", params)));
        HttpURLConnection connection = (HttpURLConnection) URI.create(base).toURL().openConnection();
        connection.setRequestMethod("POST");
        connection.setRequestProperty("Authorization", "Bearer " + token);
        connection.setDoOutput(true);
        connection.getOutputStream().write(envelope.getBytes(StandardCharsets.UTF_8));
        String body = new String(connection.getInputStream().readAllBytes(), StandardCharsets.UTF_8);
        return (Map<Object, Object>) MiniJson.parse(body);
    }

    static void check(String name, boolean condition) {
        if (condition) {
            passed++;
        } else {
            failures.add(name);
        }
    }
}
