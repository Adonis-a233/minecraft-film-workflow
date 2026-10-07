# Architecture and contribution guide

## Data flow

agent/ turns a natural-language production request into a typed, reviewable plan. The LLM is not the execution engine: Python models and JSON Schema validate coordinates, actor actions, asset IDs, scene bounds, output destinations and overwrite policy before an operation can reach the game.

contracts/ is the stable wire format. Versioned request/response schemas and fixtures let Python and Java reject malformed or unsupported operations in the same way.

cinematic-bridge/ runs inside the Fabric client. It marshals accepted calls onto the Minecraft client or integrated-server thread, checks the operation and world scope, returns explicit status and keeps a persistent operation journal for restart recovery. The HTTP bridge is bound to loopback; do not expose it to a LAN or the public internet.

assets/ is for the reusable sample media and world. Production outputs should be versioned, hashed and accompanied by a manifest. Temporary runs, logs, tokens, launcher profiles, and complete user instances belong outside the public repository.

## Execution lifecycle

1. Parse and validate a plan without changing the game.
2. Produce a preview and require explicit approval for live writes.
3. Execute only operations represented by the validated contract.
4. Record accepted, pending, succeeded, failed, or unknown status with idempotency evidence.
5. Verify produced media and store hashes/manifests beside the output.

An offline test or a successful Gradle build does not prove that a given set of mods works in a real game. Live acceptance must record Minecraft, Fabric, Java, installed mod versions, world identity, operation evidence, and a short reviewable take.

## Main directories

- agent/src/minecraft_film_agent/: Python CLI, MCP server, models, validation, actors, camera, bridge, production and media components.
- agent/tests/: offline regression suite.
- contracts/v1, contracts/v2, contracts/v3: versioned JSON Schema contracts and test fixtures.
- cinematic-bridge/src/main/java/: Fabric mod source, deterministic actor/motion code, world operations and bridge.
- examples/: minimal scene plan that can be used as a template.
- assets/: example world, character pack, map source and film files.

## Extending the workflow

- Add a new field to a versioned schema and its model/validator tests before using it in an execution path.
- Keep paths relative to an explicit workspace. Never infer the user's launcher directory from the OS profile.
- Add a new adapter behind the same validation, idempotency, timeout, permission and audit boundaries.
- Preserve original recordings and maps. Write a new versioned output instead of overwriting an existing deliverable.
- Keep third-party dependencies pinned and document their source, version, license and redistribution status in mods/README.md.

## Known limitations

- Production environments differ from a clean clone: the Minecraft account and game files must be installed separately.
- Some camera/export paths depend on third-party client mods; Flashback support is fail-closed by default.
- Schematic imports are bounded and do not provide one-click import of an arbitrarily large school or city.
- The example video has passed file-integrity checks, but that is distinct from exhaustive frame-by-frame and normal-speed audio acceptance.
