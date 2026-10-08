# 角色外观 JSON 输入

示例 `examples/film-recast-v10.json` 将角色 `a` 临时替换为 `zhou` 的模型，用于验证兼容资源包生成。实际使用时，把 `pack` 改成另一份含同样部件文件的兼容资源包，并同步更改 `recast_id` 与 `output_pack`。字段约束见 `contracts/v1/film-recast.schema.json`。

```powershell
py -3 scripts/film_recast.py preview examples/film-recast-v10.json
py -3 scripts/film_recast.py build examples/film-recast-v10.json
```

工具核对角色部件文件和纹理引用，生成新的资源包与哈希 manifest；不改原包，也拒绝覆盖已有输出。普通 Minecraft 玩家皮肤 PNG 不能直接导入这里：本片演员由 ItemDisplay 分部件 3D 模型与调色板组成，人物动作、嘴型、手机和衣服变体依赖现有模型结构。

**生成资源包不等于重新出片。** v10 的旧 MP4 已经烘焙角色画面。要在新外观下拍完整片，仍须在隔离 Minecraft 实例中加载新包，按原回放与镜头轨道重新导出受影响镜头，并更新七幕片源；之后才能运行 [全片拼接入口](FILM_ASSEMBLY.md)。镜头与逐幕重编的总控 JSON 尚未完成。
