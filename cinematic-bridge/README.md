# Cinematic Bridge

Fabric client mod for Minecraft Java 1.21.1. It exposes a loopback HTTP bridge and executes validated operations through the Minecraft client or integrated-server threads.

## Build

Requirements: JDK 21 and network access to Fabric Maven and Modrinth Maven.

From this directory:

~~~powershell
.\gradlew.bat check
~~~

The Gradle Wrapper pins 8.10.2. Fabric Loom, Minecraft, mappings, Fabric Loader, Fabric API, ReplayMod compile-only API and Carpet compile-only API are all version-pinned. ReplayMod is resolved from its official Modrinth Maven coordinate; it is not embedded in the output jar.

## Runtime behavior

- Bridge HTTP binds to loopback only.
- Requests use versioned JSON contracts in the sibling contracts directory.
- Accepted writes are scoped and journaled for idempotent recovery.
- The bridge does not accept unrestricted shell or file-system requests.
- Flashback integration remains disabled by default.
- Live operation still requires a compatible Minecraft/Fabric instance and separately installed runtime mods.

Build and unit-test success does not constitute live game acceptance. The root README and mods/README.md contain the full runtime setup.
