# Minecraft Film Workflow

> 最新完整资源与原片音轨交接：[2026-10-31 READY包](docs/delivery-20261031/START-HERE.md)。以此文件的皮肤、音轨与时间冲突处理规则为准。

面向 Minecraft Java 版 1.21.1 的文字驱动制片工作流。它把分镜和演员动作写成结构化计划，由可检查、可重复的 Python/Java 代码执行；每次运行会保留计划、结果、校验信息和素材哈希，避免靠手动操控或截图记忆来复现镜头。

Repository: https://github.com/Adonis-a233/minecraft-film-workflow

## 这个项目包含什么

- **agent/**：Python 制片 Agent、MCP 服务、计划校验、资产登记、动作编译、相机和剪辑流程。
- **contracts/**：场景、演员、相机、世界操作、运行状态和剪辑计划的 JSON Schema。
- **cinematic-bridge/**：Minecraft Fabric 客户端模组。它在游戏主线程执行通过校验的操作，并留下可恢复的操作日志。
- **scripts/**：安装 Python 开发依赖、运行检查，以及创建隔离超平坦测试存档的脚本。
- **mods/redistributable/**：已确认可按各自许可证再分发的少量运行模组。
- **assets/**：样例成片、角色资源包、城市拍摄存档和校园地图来源。
- **examples/minimal-scene-plan.json**：最小结构化场景计划。
- **examples/film-assembly-v10.json**：可重新生成双版 v10 成片的八章拼接清单。
- **examples/film-recast-v10.json**：兼容分部件角色模型的换角示例。
- **assets/productions/v10-master-draft-20261009/**：旧稿 8 章、68 个镜头的声明式总控样例；镜头素材和回放母版分别在 `assets/footage/v10/`、`assets/replays/v10/`。

当前影片是 8 分 30 秒、1920×1080、30 fps 的**制作草稿与工作流经验样例**，需要大量重构，尚未作为最终影片验收。字幕版和无对白字幕版保留在 Git LFS 中；已有的完整解码、恒定帧率及哈希检查只说明这些旧文件可读取、可复现，不代表剧情呈现、表演和声音达到交付标准。范围见 ASSET-CREDITS.md。

v10 草稿的全片双版拼接已可由一个 JSON 命令重现，且两版输出与原草稿文件的哈希完全相同。操作见 [全片拼接说明](docs/FILM_ASSEMBLY.md)。镜头导出、逐幕剪辑与全片依赖已迁入 [声明式总控样例](docs/FILM_MASTER.md)，可离线预览八章动作清单。[换角输入说明](docs/RECAST.md) 可生成新角色资源包；完整换角实机重导、旧稿全部重建和影片质量仍未验收，三个旧镜头暂按固定片段导入。

## Windows 接续制作

**最新迭代：[从技术排练转入镜头生产](docs/execution-20261031/NEXT-EXECUTION.md)**（2026-10-31）。本片资料在 `codex/film-kanjianduoshao-assets` 分支维护。

**最新选型修正：[社区角色与动作资源实查](docs/community-assets-20261030/README.md)。** 已下载并解析BBS内置85动作及社区6个循环，不再把旧rig限制当成不寻找新素材的理由。

**先读 [唯一执行入口与固定资源路径](docs/execution-20261030/START-HERE.md)。** 包含远程逐文件核对、三项精确下载、85镜执行台账与禁止擅自替换的边界。旧候选文档不再作为自由选型任务单。

先读 [开拍阻塞与就绪审查](docs/readiness-20261028/README.md) 和 [Windows 交接单](docs/readiness-20261028/windows-handoff.md)。用户保留的 Windows 原实例是后续核对依据；本次 Mac 缺少的绑定、资源及媒体不能直接认定 Windows 同样缺失。

- [影片实际审阅与优化](docs/review-20261027/README.md)
- [《看见多少》七幕与片尾规划](docs/production-v11/README.md)：85 个剪辑单元，导演规划尚需编译和现场标定。
- [人物、动作、地图与光影素材选型](docs/materials-20261028/README.md)：候选版本、来源、哈希与试拍方法。
- [代码修复及验证范围](docs/WORKFLOW_FIXES_20261027.md)：资源依赖指纹、逐镜审核和恢复。

在已有 Windows 仓库中先检查并保存自己的改动，再使用 `git pull --ff-only` 更新；不要覆盖原实例、绑定、动作源或存档。候选二进制位于本次 Mac 的忽略目录 `work/`，不会随 Git 同步；Windows 可按 [候选文件清单](docs/materials-20261028/staged-files.json) 中的官方来源重新取得，并核对 SHA-256。仅下载不等于安装或通过试拍。当前文档不承诺无人值守拍完整片，未关闭的执行缺口见就绪审查。

## 快速开始

### 1. 安装前置软件

- Windows 10/11 或 Linux；当前脚本以 Windows PowerShell 为主。
- Minecraft Java Edition 1.21.1，需通过自己的正版启动器安装并接受 Mojang EULA。
- Fabric Loader 0.19.3。
- Java 21；构建基线使用 Java 21。
- Python 3.12。
- Git、Git LFS 和 Astral uv。
- FFmpeg 与 ffprobe；运行媒体校验/剪辑相关功能时需要，项目不捆绑它们。

Minecraft 本体、账号、启动器、共享资源缓存和用户配置不在仓库中。

### 2. 克隆源码及大文件

~~~powershell
git lfs install
git clone https://github.com/Adonis-a233/minecraft-film-workflow.git
cd minecraft-film-workflow
git lfs pull
~~~

如果只想运行代码测试而暂时不下载电影，可在克隆前设置 GIT_LFS_SKIP_SMUDGE=1；之后可用 git lfs pull --include="assets/videos/*" 取回电影文件。

### 3. 安装 Python 依赖并运行检查

~~~powershell
.\scripts\bootstrap.ps1
uv run minecraft-film-agent --help
uv run minecraft-film-mcp --help
~~~

脚本使用 uv.lock 锁定依赖，并运行 Python 回归测试。它不会启动 Minecraft、读取启动器账号、连接外部世界或录制视频。

发布副本首次在 Python 3.12.13 上验证为 334 passed、7 skipped；这 7 项需要本机 FFmpeg/ffprobe。完整范围见 docs/TESTING.md。

### 4. 构建 Fabric Bridge

~~~powershell
cd cinematic-bridge
.\gradlew.bat check
~~~

Gradle Wrapper 固定 Gradle 8.10.2；Java 编译目标为 21。构建从 Fabric 与 Modrinth 官方 Maven 获取固定版本的开发依赖，Carpet 的 compile-only JAR 使用仓库内已授权分发的固定副本。

### 5. 准备游戏实例

把 mods/redistributable/ 中的 JAR 复制到 Minecraft 1.21.1 Fabric 实例的 mods/，再从各模组官方页面安装下表中未打包的版本。把 assets/resourcepacks/characters-v12-1.21.1.zip 放入 resourcepacks/ 并在游戏里启用。将 assets/worlds/city-campus/CityCampus-world.zip 解压到 saves/CityCampus/，确保 saves/CityCampus/level.dat 存在。存档已移除玩家档案、统计和进度记录。

拍摄用的非再分发模组必须由使用者从作者发布页取得，版本清单和来源见 mods/README.md。游戏本体和启动器必须从 Mojang/Microsoft 官方渠道取得。

## 工作流

1. 用 contracts/ 中的 schema 写场景计划，明确演员、XYZ 路径、朝向、动作区间、机位和输出目标。
2. Python Agent 校验计划、边界、目标路径、素材来源和不覆盖规则；dry-run 先生成预览。
3. 经审批后，Agent 通过本机 Cinematic Bridge 发送结构化请求。Bridge 再执行允许的游戏操作，并把操作状态写入日志。
4. 录制与剪辑步骤保存输入哈希、运行 manifest、导出信息和解码/CFR 结果。
5. 每段 5–10 秒完成后单独审看，再决定是否进入下一段或替换镜头。

MCP 服务只监听本机回环地址。API 密钥通过运行时环境变量或受保护的密钥文件提供；不要把真实密钥、启动器配置、实例配置或运行日志提交到 Git。

## 游戏与模组版本

| 组件 | 固定版本 | 仓库是否包含 |
|---|---:|---|
| Minecraft Java Edition | 1.21.1 | 否；必须从官方启动器安装 |
| Fabric Loader | 0.19.3 | 否；安装器链接见 mods/README.md |
| Fabric API | 0.116.15+1.21.1 | 是 |
| Motion Capture | 1.3.10-fabric-1.21.1 | 是 |
| Fabric Carpet | 1.4.147+v240613 | 是；演员排练辅助 |
| Cinematic Bridge | 0.1.0 | 源码包含；需在本地构建 |
| ReplayMod | 1.21-2.6.27 | 否；通过 Modrinth 获取 |
| Flashback | 0.39.8 | 否；需从作者发布页获取 |
| Axiom | 6.0.2 | 否；人工编辑工具，许可证未完成审查 |
| Complementary Reimagined | r5.2.2 | 否；可选光影，幻想风预设 |
| Java | 21 | 否；本地构建和运行环境 |

运行时版本、许可状态、下载链接及固定哈希见 mods/README.md。Minecraft 原版文件和不能再分发的模组不会打包。Northfield 校园建筑来源依 CC BY-NC 4.0 标注；样例素材的其他来源边界见 ASSET-CREDITS.md。

## 当前能力边界

2026-10-27 的代码、计划与影片抽帧审阅见 [工作流优化审阅](docs/review-20261027/README.md)，包含问题证据、优先级、制作模板及短场景试点。该审阅不是实机修复或影片质量验收。

- 离线 Python 回归覆盖了计划校验、路径保护、资产、演员动作、MCP 客户端、剪辑和交付等模块。
- Fabric Bridge 有确定性世界操作、状态查询、Mocap 命令面和演员动画代码；实际功能仍受已安装模组与当前世界能力限制。
- ReplayMod 的编译绑定是可选依赖；Flashback 端口默认 fail-closed。项目没有声称空白电脑 clone 后就能免安装游戏、免装模组、免配置账号一键拍完。
- 大型校园地图不能通过当前有限块数的 schematic 导入器一键载入；本仓库提供的是已准备好的样例世界存档。
- 样例影片是工作流输出，不代表公开项目已完成对所有场景的完整实机复刻验收。
- `film-master-preview` 可从仓库内固定的镜头素材和 JSON 计划生成八章待建清单；`film-master-run` 的 510 秒旧稿重建尚未执行。实机重导还需要自行取得未再分发的 NicoRTX 校园资源包并通过资源包栈校验。

## 开源与素材

自有工作流代码采用 GPL-3.0-or-later，完整文本见 LICENSE。第三方模组、地图、角色包、Minecraft 内容及影片素材有各自的来源和条件；它们不因代码许可证而自动变成 GPL。非商业样例用途、署名与修改记录见 ASSET-CREDITS.md。请勿把本地密钥、个人账号配置、玩家档案或未清理的实例快照提交到公开仓库。

English summary: a deterministic, text-driven filmmaking toolkit for Minecraft Java 1.21.1 and Fabric. It includes a Python planning/MCP agent, JSON contracts, a Fabric bridge, pinned mod notes, sanitized sample world data, character resources, and two full-film examples stored with Git LFS. Minecraft itself is not included. See the sections above and mods/README.md for setup and runtime limits.
