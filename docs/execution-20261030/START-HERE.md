# Windows 唯一交接入口：逐段执行，不再重新选型

可复制的执行提示词：[WINDOWS-PROMPT.md](WINDOWS-PROMPT.md)。

日期：2026-10-30。本文收敛旧交接文档中的开放选项；不修改用户剧本，不降低视觉要求。用户后续明确指令优先。旧素材候选表是研究记录，不是安装任务表。

## 1. 先核对真正交付了什么

远程基准 `98b29b78aaa247f2f81c0a6f037624190086ce2d` 的四组文档共51个文件已逐一比较 Git blob，与本地提交完全相同。逐文件证据见 `remote-audit.json`。这仅证明仓库同步，不证明 LFS 大文件可下载或影片合格。

- 已交付：七幕＋片尾，85个剪辑单元的导演卡；剧本提取与出处；角色/美术/动作/场景约定；候选版本与兼容问题；动作合同缺口；依赖及真实审核机制。
- 未交付：新绘制的七角色精细图集、全部适配完成的动作曲线、新地图实机勘景结果、最终世界/机位坐标、v11可直接录制的完整执行包、Windows试拍与人工视觉签核。
- 85张卡并非85段已录好的表演，不是每张都已有可执行路径或资源实体。局部坐标仍需映射到真实世界。
- 旧 `work/materials-20261028/candidates/` 是Mac本地忽略目录，不会被git拉取。现在提供精确下载锁和脚本，不再要求Windows自行搜索。
- 原DOCX个人下载路径不在仓库；正文与来源哈希在 `docs/production-v11/script-extract.md`、`script-source.json`。没有上传个人下载目录。

**因此不能宣称“全适配完成，只差按录制按钮”。不能让执行端以擅自删动作、旧角色顶替最终美术、装随机动作Mod来掩盖缺项。**

## 2. 本轮固定选择与现成路径

所有路径相对仓库根目录。Windows实际盘符必须从原实例读取，不编造 `D:\...`。

| 层 | 决定与精确入口 | 使用边界 |
|---|---|---|
| 剧本/镜头 | `docs/production-v11/script-extract.md`；`production-bible.md`；`shared-event.md`；`acts/S01.md`至`S07.md`与`credits.md` | 不重写剧情；每镜卡全部字段逐项执行，不能仅看总表 |
| 七角色现有美术 | `assets/resourcepacks/characters-v12-1.21.1.zip`；角色身份 `a/zhou/teacher/chen/elder/filmer/safety` | 新拍摄适配基线；不是精细美术成品；旧回放必须保留各自v8/v11/v12资源栈，不全局换v12 |
| 角色绑定 | 在原Windows项目中恢复 `assets/actors/classmate-20261004/visual-binding-v10.json` | 本仓库Mac无实体；记录找到的真实绝对路径/哈希及其匹配的部件。缺失则阻塞，不伪造一份同名文件 |
| 主场景与街道 | `assets/worlds/city-campus/CityCampus-world.zip`，来源 `ASSET-CREDITS.md` | 本轮用原世界副本＋按镜头补景；不是新复杂城市地图已完成。不得把Sayama/Greenfield纳入当天拍摄依赖 |
| 校园附加材质 | 原实例已有的 `assets/resourcepacks/external/NicoRTX_JapaneseSchool_resources.zip`；SHA256 `004b53d73934c1304ad0769af81c0a0d8f484008d3d4bb6b90e3805b71c2406c` | 仅在依赖它的现有场景/回放启用；不拿网上新版覆盖旧锁。仓库不重新分发此包。找不到则暂停对应场景，不能擅自改教室 |
| 动作库 | 项目原生Java动作库，精确文件见下表 | 适配当前分部件演员的唯一生产主线。外部人体动捕未转好，不能假装选个FBX即可替换 |
| 光影主试验 | Complementary Reimagined **r5.9.3**，版本ID **Bqen1mJX** | 与原实例基线同机位对照；尚未视觉通过，不一键覆盖原配置 |
| 光影运行配对 | Iris **1.8.8+1.21.1**（**zsoi0dso**）＋Sodium **0.6.13+1.21.1**（**u1OEbNKx**） | 精确版本范围匹配，完整原实例兼容性仍需试机；原Java21/Fabric/ReplayMod/Bridge其他版本先保持 |
| 环境美术 | 现有方块/资源包：教室补窗外树冠与走廊；宿舍补床柜书桌；休息室补工具柜、工衣与生活痕迹；街道补店面、围挡和远景 | 布景保持前中后景；表演区、接触锚点与摄影视锥优先。这些是固定布景规格，尚非已搭好的地图 |

下载入口：在仓库根运行 `python scripts/fetch-selected-film-resources.py`（或已配置的 `uv run --locked python scripts/fetch-selected-film-resources.py`）。只取上面三个冻结文件，校验长度和SHA256，放入 `work/materials-20261028/candidates/`；不自动安装。完整官方CDN URL、文件名、哈希见 `selected-downloads.json`。已有文件哈希不符时停止，保留现场，不覆盖。

使用范围和原始许可见 `ASSET-CREDITS.md`、`docs/materials-20261028/locations-and-look.md`；影片制作许可不等于地图/模型/资源包再分发许可。Iris为LGPL，Sodium为Polyform Shield，Complementary为自定义许可，不把三者统称自由素材。发布页：[Reimagined固定版本](https://modrinth.com/shader/complementary-reimagined/version/Bqen1mJX)、[Iris固定版本](https://modrinth.com/mod/iris/version/zsoi0dso)、[Sodium固定版本](https://modrinth.com/mod/sodium/version/u1OEbNKx)。

**不进入本轮生产安装清单**：CPM、Fresh Moves、EMF/ETF、3D Skin Layers、Emotecraft及其Flashback插件、Physics Mod、Macaw家具、Unbound、Bliss、Sayama、Greenfield。原因是分部件演员不直接兼容、回放链路冲突或迁移/验证未完成，而非作品不够好。禁止把“候选”逐项全装一遍。更复杂地图和精细角色要求仍未兑现，不能据此标记完成；新选型由规划端负责给出替代锁，Windows不发散调研。

### 固定动作实现定位

目录 `cinematic-bridge/src/main/java/dev/mcfilm/cinematicbridge/actor/`：

| 动作 | 首先复用/检查的源码 |
|---|---|
| 静止、听说、视线、手机、嘴型、基础姿态 | `ActorVisuals.java`、`MouthModels.java` |
| 行走、重心、脚底接触 | `GroundedStrideRig.java`、`WalkSurface.java`、`ActorService.java` |
| 推离、跌坐、扶起 | `ActorService.java`、`ActorVisuals.java`、`FallMotion.java`、`FallenPoses.java` |
| 拾物 | `GroceryPickupMotion.java`、`GroceryApproachRig.java`、`GroceryProps.java`、`GroceryScatterMotion.java` |
| 学生/陈收包 | `BagPackingMotion.java`、`StandingPackingMotion.java`、`PackingArmPose.java`、`BagPackingVisual.java` |
| 取外衣 | `CoatPickupMotion.java`、`CoatPickupVisual.java` |
| 手机收回 | `PhonePutAwayMotion.java`、`ActorVisuals.java` |
| 合同/限制 | `ActorPlan.java`及`agent/src/minecraft_film_agent/actors.py` |

这张表是代码来源映射，不是已完成的新拟人动画库。醒来/自然转身/投影操作，以及短拾物仍缺完整实现或证据；冲突逐条见 `docs/readiness-20261028/action-gaps.md`。禁止直接把3040ticks拾物压缩为4秒、只放宽校验、不改真实运动；禁止用静止、瞬移、遮挡或删动作冒充实现。

## 3. 分段推进与交付门槛

先建本机 `work/v11-execution/`，把本目录 `shot-execution-ledger.csv`复制进去作为运行台账；保留仓库模板未审核状态。每次更新写入本次commit、输入哈希、镜头/动作段ID、实际路径和证据。下列产物名称是待生成要求，**目前不是现成文件**。

1. **同步和现场定位**：保存Windows独有改动后更新远程；核对本入口存在。仅搜索原项目/实例和启动器登记目录，记录 `environment-lock.json`：项目、实例、世界副本、绑定、Java21、FFmpeg、Bridge JAR与源码、ReplayMod版本、资源栈顺序和输出盘。找不到单个必需文件就报告具体缺项；不把Mac缺文件结论当作Win缺文件。
2. **精确资源准备**：只取锁内三文件、核对原角色/地图实体和LFS指针。建立实例副本，不污染原实例。输出 `asset-resolution.json`，每个资源为resolved/blocked，写实际路径与哈希。人物精修未交付时允许基线排练，不允许正式镜头伪装成新版美术成片。
3. **执行包编译与能力核对**：逐条对照动作冲突，不再调研动作库。允许恢复原动作源、现场标定、生成/修复执行合同、脚本和调用连接；不允许自行更换角色方案或改剧情。输出 `stage-lock.json`与合同可验证的actor/camera/production计划，给出真实运行/恢复入口。`planning-index.json`不是执行合同，禁止直接提交运行。缺新美术或完整动作设计时记为规划/资产交付阻塞，不转化为Windows自由创作任务。
4. **首个短段**：在副本录静止→走停转→持手机；同场景同机位测试基线与选定光影。导出正常速度视频与接触关键帧，核对关节、UV、脚滑、闪烁、主体曝光、回放前后跳和暂停恢复。机器报告与视觉判断分开记录。不通过只修这个试段，禁止录全片试运气。
5. **共享事件分段**：按 `shared-event.md` 的CP1推离/落板、CP2扶起、CP3转移、CP4拾物、CP5结束逐段验证；锁同一时间线，接触段不拆坏。连续监控最终引用同一母版，禁止手机/监控分别演不同动作。没有合格完整动作则对应后续引用阻塞。
6. **逐镜生产**：复用锁定的共享事件后，课堂S01/S06→宿舍S03/S05/S07→休息室S04/S07→UI/后期；各幕内部镜头按编号推进。逐镜读完整卡，恢复入口与道具状态→拍动作段→保存→回放/导出→审看→登记；任何共享事件引用受步骤5约束。不可见的机位或未校准路径不能只凭JSON通过开拍。
7. **逐幕和全片验收**：按S01至S07再片尾完整带声审看；检查对白、节奏、因果、连续性与美术。不以解码、帧率、哈希或“命令成功”代替视觉/剧情验收。

每个动作段保存：输入锁、入口/出口状态、执行命令及operation ID、录像/回放路径、正常速度片段、关键帧、技术结果、视觉问题与重拍范围。不得仅输出“已完成”文字。

## 4. 权限、失败与无人值守约束

- 允许思考：如何调用已有工作流、如何验证真实状态、如何标定/编译、如何定位故障并最小范围修复。禁止擅自思考并执行新的剧本/资源选型/美术方向。
- 每次报告只列：本段ID、已生成证据、通过/待审/阻塞、下一段。不能把长篇规划代替运行产物。
- 同输入同原因连续失败2次，停止重复尝试该段；记录错误、操作ID、受影响镜头、缺项。已证明无依赖的任务可继续；禁止无上限重录、强制绕过校验或批量装Mod。
- `needs_review`不是已批准。人工未审时不能捏造reviewer/approved；程序/Agent视觉初筛单列记录。现有默认待审暂停应保留。无人值守继续仅限已实现的独立候选队列，不靠伪造审核推进。
- 动作/rig/世界改动：重录受影响母版及其消费者；机位改动：复用合格母版重导；UI/声音改动：重做对应后期。共享事件变化检查S01/S02/S03/S05/S06全部引用。
- 不覆盖或删除Windows原实例、绑定、动作和未提交工作。输出不把密钥、个人目录、无授权第三方地图/素材写入远程。
- 真实缺失的新角色精修、动作适配或地图成品必须反馈规划端；执行端不得“先用差不多的东西交差”。这也是当前无法承诺Windows纯执行拍完整片的原因。
