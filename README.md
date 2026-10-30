# Minecraft Film Workflow

面向 Minecraft Java 1.21.1 / Fabric 的可重复影片制作工作流。

此分支是本地拆分预览，尚未替换远程 main。影片《看见多少》的完整交付保留在 `codex/film-kanjianduoshao-assets` 本地分支；等待 Windows 拉取现有远程后，再安排发布切换。

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

此预览已去除本片规划、地图、角色、媒体与专用下载清单。部分历史操作文档仍含旧影片路径，迁移状态见 `docs/REPOSITORY_SPLIT.md`；完整游戏拍摄尚需独立实例验收。
