# Minecraft Film Workflow

面向 Minecraft Java 1.21.1 / Fabric 的可重复影片制作工作流。

main 提供通用工作流。具体影片规划与资产在 `codex/film-kanjianduoshao-assets` 分支，制作端请使用该分支。新用户可用 `git clone --depth 1 --branch main https://github.com/Adonis-a233/minecraft-film-workflow.git` 获取当前代码。

## 工作流内容

- `agent/`：Python CLI、MCP、计划校验、动作与相机编排、拍摄、剪辑、审核和依赖重建。
- `cinematic-bridge/`：游戏内 Fabric Bridge。
- `contracts/`：可复用的结构化计划与运行合同。
- `examples/minimal-scene-plan.json`：不依赖本片地图与角色的最小计划。
- `mods/`、`LICENSES/`、`upstreams.lock.json`：现有运行依赖、来源和许可。
- `scripts/`：通用安装、超平坦测试世界准备与换角工具。

## 开发与验证

准备 Python 3.12、uv、Java 21；媒体功能另需 FFmpeg/ffprobe。Minecraft 账号、本体、启动器和拍摄实例由使用者提供。

在仓库根目录运行 `uv sync --group dev`，然后运行 `uv run pytest`、`uv run minecraft-film-agent --help`、`uv run minecraft-film-mcp --help`。

Bridge 在 `cinematic-bridge/` 内以 Gradle Wrapper 构建。环境与操作边界见 `docs/ARCHITECTURE.md` 和 `docs/TESTING.md`。

## 接入自己的影片

使用自己的世界副本、演员、动作和镜头资源，按 `contracts/` 编写与校验计划。参考最小示例先做短段试拍，再逐镜审核、保存输入锁与结果。技术通过不代替画面、表演、声音和剧情验收。

本分支不附带具体影片的地图、人物与媒体。分支约定见 `docs/REPOSITORY_SPLIT.md`。离线测试不代替Minecraft实机拍摄验收。
