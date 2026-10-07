package dev.mcfilm.cinematicbridge.server;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import dev.mcfilm.cinematicbridge.json.MiniJson;

import java.io.IOException;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.Executors;

/**
 * Loopback-only HTTP front for the dispatcher (plan §9.3): binds
 * 127.0.0.1 explicitly, requires a bearer token on every request, never
 * logs tokens. A small fixed pool (one production session, plus spare
 * threads) keeps status queries responsive while a synchronous v2 write is
 * in flight; contract-3 writes return before touching the game thread.
 */
public final class BridgeHttpServer {

    private final HttpServer server;
    private final String token;
    private final BridgeDispatcher dispatcher;

    public BridgeHttpServer(int port, String token, BridgeDispatcher dispatcher) throws IOException {
        this.token = token;
        this.dispatcher = dispatcher;
        this.server = HttpServer.create(new InetSocketAddress("127.0.0.1", port), 0);
        this.server.setExecutor(java.util.concurrent.Executors.newFixedThreadPool(4, runnable -> {
            Thread thread = new Thread(runnable, "cinematic-bridge-http");
            thread.setDaemon(true);
            return thread;
        }));
        this.server.createContext("/rpc", this::handleRpc);
    }

    public int port() {
        return server.getAddress().getPort();
    }

    public void start() {
        server.start();
    }

    public void stop() {
        server.stop(0);
    }

    private void handleRpc(HttpExchange exchange) throws IOException {
        try {
            if (!"POST".equals(exchange.getRequestMethod())) {
                respond(exchange, 405, Map.of("status", "rejected", "message", "POST only"));
                return;
            }
            String authorization = exchange.getRequestHeaders().getFirst("Authorization");
            if (authorization == null || !authorization.equals("Bearer " + token)) {
                respond(exchange, 401, Map.of("status", "rejected", "error_class", "authentication_failed",
                    "message", "missing or invalid bearer token"));
                return;
            }
            String body = new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
            Object parsed;
            try {
                parsed = MiniJson.parse(body);
            } catch (IllegalArgumentException error) {
                respond(exchange, 400, Map.of("status", "rejected", "message", "bad JSON: " + error.getMessage()));
                return;
            }
            @SuppressWarnings("unchecked")
            Map<String, Object> envelope = (Map<String, Object>) parsed;
            @SuppressWarnings("unchecked")
            Map<String, Object> request = (Map<String, Object>) envelope.get("request");
            if (request == null) {
                respond(exchange, 400, Map.of("status", "rejected", "message", "envelope.request is required"));
                return;
            }
            if (!(request.get("schema_version") instanceof Number schemaVersion)
                || (schemaVersion.intValue() != 1 && schemaVersion.intValue() != 2
                    && schemaVersion.intValue() != 3)) {
                respond(exchange, 400, Map.of("status", "rejected", "message",
                    "request.schema_version must be 1, 2 or 3"));
                return;
            }
            String operationId;
            String idempotencyKey;
            try {
                operationId = requiredText(request, "operation_id");
                idempotencyKey = requiredText(request, "idempotency_key");
            } catch (IllegalArgumentException error) {
                respond(exchange, 400, Map.of("status", "rejected", "message", error.getMessage()));
                return;
            }
            Object method = request.get("method");
            @SuppressWarnings("unchecked")
            Map<String, Object> params = (Map<String, Object>) request.getOrDefault("params", Map.of());
            if (!(method instanceof String methodName)) {
                respond(exchange, 400, Map.of("status", "rejected", "message", "request.method is required"));
                return;
            }
            Map<String, Object> result;
            try {
                result = dispatcher.handle(methodName, params, schemaVersion.intValue(), idempotencyKey);
            } catch (IllegalArgumentException error) {
                result = Map.of("status", "rejected", "error_class", "validation_failed",
                    "message", String.valueOf(error.getMessage()));
            } catch (RuntimeException error) {
                // A dispatcher crash must still answer the caller (and the
                // answer must not claim success).
                result = Map.of("status", "unknown", "error_class", "operation_timeout_unknown",
                    "message", "dispatcher error: " + error);
            }
            // The controller validates every reply against operation-result schema.
            // Dispatcher methods own only their outcome payload; this transport layer
            // attaches the request identity so every successful or rejected reply is a
            // complete, correlatable operation result (contract 2 REQUIRES the key — F1).
            Map<String, Object> operationResult = new LinkedHashMap<>(result);
            operationResult.put("schema_version", schemaVersion.intValue());
            operationResult.put("operation_id", operationId);
            operationResult.put("idempotency_key", idempotencyKey);
            respond(exchange, 200, operationResult);
        } finally {
            exchange.close();
        }
    }

    private void respond(HttpExchange exchange, int code, Map<String, Object> payload) throws IOException {
        byte[] bytes = MiniJson.write(payload).getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().set("Content-Type", "application/json");
        exchange.sendResponseHeaders(code, bytes.length);
        try (OutputStream out = exchange.getResponseBody()) {
            out.write(bytes);
        }
    }

    private static String requiredText(Map<String, Object> value, String key) {
        Object raw = value.get(key);
        if (!(raw instanceof String text) || text.isBlank()) {
            throw new IllegalArgumentException("request." + key + " is required");
        }
        return text;
    }
}
