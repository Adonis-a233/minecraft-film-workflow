# 角色外观 JSON 输入

示例 `examples/film-recast-v10.json` 将角色 `a` 临时替换为 `zhou` 的模型，用于验证兼容资源包生成。实际使用时，把 `pack` 改成另一份含同样部件文件的兼容资源包，并同步更改 `recast_id` 与 `output_pack`。字段约束见 `contracts/v1/film-recast.schema.json`。

```powershell
py -3 scripts/film_recast.py preview examples/film-recast-v10.json
py -3 scripts/film_recast.py build examples/film-recast-v10.json
```

工具核对角色部件文件和纹理引用，生成新的资源包与哈希 manifest；不改原包，也拒绝覆盖已有输出。普通 Minecraft 玩家皮肤 PNG 不能直接导入这里：本片演员由 ItemDisplay 分部件 3D 模型与调色板组成，人物动作、嘴型、手机和衣服变体依赖现有模型结构。

**生成资源包不等于重新出片。** v10 的旧 MP4 已经烘焙角色画面。当前 [声明式总控](FILM_MASTER.md) 已登记 68 个镜头和八章配方，可按规格变化安排镜头重导、逐幕重编和双版全片拼接。要换外观，仍须在隔离 Minecraft 实例中启用新包、重导所有受影响镜头，并给输出使用新版本路径。三段旧镜头缺少当时资源包版本证据，现阶段只能按固定视频导入；涉及这些角色时，须先补齐回放与机位声明，不能直接复用。完整换角的实机重导与成片质量尚未验收。
