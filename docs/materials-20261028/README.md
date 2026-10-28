# 《看见多少》素材选型与试拍清单

检索日期：2026-10-28。依据：七幕导演规划、现有角色包 v12、ActorVisuals、资产署名与版本锁。本轮完成来源检索、版本查询、候选文件下载与静态检查；**没有启动游戏、安装 Mod、替换角色或地图，也没有完成视觉验收**。

## 选型结论

优先做 **现有角色精修＋动作重定向试验＋原场景局部升级＋光影对照**。同时保留 **CPM 角色迁移**作为更高表现力的备选。拟人感首先来自重心、接触、停顿和反应，不能只靠增加皮肤分辨率或安装动作 Mod。

| 需求 | 本轮优先选择 | 备选及取舍 |
|---|---|---|
| 人物精细皮肤 | 为现有七角色重做专用 UV 图集、衣服层次和关节遮盖；先做陈师傅/A 两人 | CPM 自定义模型与动画可单独试验；普通玩家皮肤不能直接套到当前角色 |
| 自然动作 | 保留项目交互动作，加入动捕参考、脚底锁定与人工表演修整 | Emotecraft 内置 Point/Over here 可作手势样本；Fresh Moves 可测试普通玩家的日常步态，不解决当前展示部件动画 |
| 复杂地图 | 校园先核查 NicoRTX Japanese School；宿舍/休息室局部补景 | 街景优先考察佐山城，Greenfield 备选；两者都需重做走位、遮挡与机位标定 |
| 光影 | Complementary Reimagined r5.9.3，与原 r5.2.2 基线对照 | Unbound r5.9.3、Bliss 2.1.2 同机位试拍；后两者的视觉优势未实测 |
| 环境细节 | 原版/现有资源包布景优先；Macaw's Furniture 3.4.1 小范围试验 | Continuity 可作为材质配套；新方块会增加存档与回放依赖 |
| 物理 | 主角交互继续由可重复的轨迹、IK 与接触约束驱动 | Physics Mod 3.0.33 仅作环境特效候选，不当作人物穿模修复方案 |

## 实际检查中发现的三处重要限制

1. **当前人物不是普通皮肤模型。** `ActorVisuals` 隐藏原玩家，创建 10/12 个 item_display；v12 包仅有一张 64×64 的 `palette.png`，部件用色板区域着色。因此更精细的人物需要重新展开各部件 UV、补关节背面和衣服细节；直接替换一张标准 Steve/Alex 皮肤不会成功。绑定文件 `assets/actors/classmate-20261004/visual-binding-v10.json` 当前仍缺失，新拍摄先恢复它。
2. **录制插件主页与旧版本文件存在差异。** [Emotecraft Recording Addon](https://modrinth.com/mod/emotecraft-recording-addon) 当前介绍提及 ReplayMod/Flashback，但本轮取得的 1.21.1 候选 `1.0.1` 的实际文件名是 `emotecraft-flashback-addon-1.0.1.jar`，声明硬依赖 `flashback >=0.15.0`。不能把它作为现有 ReplayMod 环境的可用适配器。另一个 `emotes-replaymod` 的精确 1.21.1/Fabric 查询无匹配版本。**Emotecraft 正式接入当前回放链路仍阻塞**。
3. **不能把最新 Iris 与最新 Sodium 任意搭配。** 下载的 Iris 1.8.8 明确要求 Sodium `0.6.x`；本次 API 查到的 Sodium 最新 1.21.1 候选是 `0.8.13`，不满足它。额外选择 0.6 系列候选，记录在文件清单；尚未通过实际启动验证。

证据：[发布页查询快照](modrinth-evidence.json)、[下载与文件内依赖检查](staged-files.json)。候选版本表不是已求解的整套安装锁；项目级许可证也不自动代表某个历史文件及其内置素材的许可。

## 分项资料

- [角色皮肤、模型与动作库](characters-and-animation.md)：角色美术要求、具体动作样本、格式、接入成本。
- [地图、环境与光影](locations-and-look.md)：地图使用边界、逐场景选择、同机位对照。
- [试拍与执行顺序](pilot-and-adoption.md)：两个小试点、验收门槛、重拍影响和工时估算。
- [候选版本表](candidates.csv)：发布页、版本 ID、许可证、是否已有候选文件。

候选二进制保存在项目 `work/materials-20261028/candidates/`，不进入正式 `mods/`、生产存档或对外资产包。用户已有角色、城镇和学校资源的原授权边界保持不变；本轮未购买、未联系作者、未提交任何发布。
