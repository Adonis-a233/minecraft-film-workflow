# 本轮检查记录

日期：2026-10-28。

- 查询 19 个 Modrinth 项目标识：18 个返回项目信息，1 个标识返回 404；失败项未作为素材采用。
- 精确筛选 Minecraft 1.21.1；Mod 额外筛选 Fabric。候选发布时间不晚于检查日。18 个已查询项目中 emotes-replaymod 无精确匹配文件。
- 下载 10 个候选文件，共 13,047,596 字节。全部与发布方 SHA-512 一致；另计算 SHA-256，ZIP/JAR CRC 检查通过。文件名单见 staged-files.json。
- 实读 Iris、Emotecraft、录制适配插件、CPM 与家具 Mod 的 fabric.mod.json；确认 Iris 1.8.8→Sodium 0.6.x，并额外取得 0.6.13。Emotecraft 内嵌 player-animation-lib 2.0.1 与 bendy-lib 5.1，不默认重复安装最新依赖。
- 实读现有 characters-v12-1.21.1.zip：唯一 PNG 为 64×64 palette，陈师傅 body 的面使用色板 UV。实读 ActorVisuals 的 10/12 部件绑定与隐藏原玩家逻辑；缺失绑定文件问题仍存在。
- 本目录 Markdown 本地链接检查通过。

这些检查只证明文件完整和静态依赖信息。尚未验证：游戏启动、Mod 之间兼容、当前 ReplayMod 的录制/跳转/离线导出、角色纹理/动画表现、新地图转换、性能、正常速度画面与声音。地图和独立动捕数据未下载。未更改生产环境或批准任何候选进入正片。
