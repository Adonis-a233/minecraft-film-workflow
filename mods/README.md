# Runtime and development dependencies

The JARs in redistributable/ are included with their existing licenses and hashes. Other game/mod binaries are intentionally fetched by each user from the original publisher; a fixed version number does not grant permission to re-upload a binary.

## Included JARs

| File | Version | License | SHA-256 |
|---|---|---|---|
| redistributable/fabric-api-0.116.15+1.21.1.jar | 0.116.15+1.21.1 | Apache-2.0 | a61a10f730ab8aa45ff42486ee65699e6e51c28a0c168deb161e7d4029473aa3 |
| redistributable/Mocap-FABRIC-1.21.1-1.3.10.jar | 1.3.10-fabric-1.21.1 | LGPL-3.0 | 97186f8469f434141b03bf87332a456cb193ef259dc9fb5896c82fba02f66c57 |
| redistributable/fabric-carpet-1.21-1.4.147+v240613.jar | 1.4.147+v240613 | MIT | 079fc8a4e073eb24b010ffcc588e59f93b984143e17d8ef19fbb0b6aff0f19d9 |

The Carpet JAR is a compile-time API dependency and an optional rehearsal helper. It is not required to run the Python-only planning tests.

## Install separately

Use these exact versions for the sample project. Read the current publisher instructions before installing or upgrading; newer versions are not assumed compatible.

| Component | Version | Source |
|---|---|---|
| Minecraft Java Edition | 1.21.1 | [Official Minecraft download](https://www.minecraft.net/download) |
| Fabric Loader | 0.19.3 | [Fabric installer](https://fabricmc.net/use/installer/) |
| Java | 21 | [Adoptium Temurin](https://adoptium.net/) |
| ReplayMod | 1.21-2.6.27 | [Modrinth release](https://modrinth.com/mod/replaymod/version/YQ20Mjid), GPL-3.0-or-later |
| Flashback | 0.39.8 | [Modrinth project](https://modrinth.com/mod/flashback); use the exact version, do not redistribute its JAR |
| Axiom | 6.0.2 | [Modrinth project](https://modrinth.com/mod/axiom); license audit is incomplete, human editing only |
| Complementary Reimagined | r5.2.2 | [Official shader project](https://modrinth.com/shader/complementary-reimagined); optional fantasy preset |

The Java bridge's compile-only ReplayMod dependency is pinned to Modrinth version ID YQ20Mjid through the official Modrinth Maven repository. The runtime mod is not bundled here.

## Build dependency pins

- Gradle Wrapper: 8.10.2
- Fabric Loom: 1.8.9
- Minecraft mappings: Yarn 1.21.1+build.3
- Fabric Loader API: 0.19.3
- Fabric API: 0.116.15+1.21.1
- ReplayMod compile-only artifact: maven.modrinth:Nv2fQJo5:YQ20Mjid
- Carpet compile-only JAR: bundled MIT artifact above, verified at build time

Do not copy Minecraft libraries/assets from a local launcher cache into this repository. If a mod fails to load, capture the sanitized version list and error summary; never attach launcher profiles or account tokens.
