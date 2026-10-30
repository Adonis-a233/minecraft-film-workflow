# 社区素材补查：从现成角色和动画出发

2026-10-30。用户要求继续找成熟社区资源，而不是因旧rig不兼容就停止。本报告替代“只能沿用原生动作库”的选型结论；既有逐幕剧本不改。外部素材检索、筛选和路线选择由规划端负责，Windows只执行明确试验。

## 已取得的实际文件

1. **BBS 2.3.3 / Fabric 1.21.1**：版本ID `OXLA4IUx`，已从官方Modrinth CDN下载10,739,246字节，核对发布者SHA512及ZIP CRC。精确URL/路径/SHA256在 `download-lock.json`。实际 `fabric.mod.json` 要求Java21、Fabric Loader>=0.16.14、Fabric API。
2. **BoltedJames Cycles Pack**：从作者帖子链接下载1,811,062字节，ZIP CRC通过；实有6份 `.miframes`、5个预览GIF和作者README。包含1静止、2走路、3跑步。所有关键帧JSON已解析，格式27、Mine-imator1.1.4、tempo24；不能当作20tick数据直接复制。

两个文件都在Mac `work/community-20261030/`，不伪称二进制已进Git。仓库保存精确下载清单和文件内证据，Windows无需搜索。使用 `python scripts/fetch-selected-film-resources.py --manifest docs/community-assets-20261030/download-lock.json` 取同字节文件，只下载不安装。

### BBS内部可直接定位的资源

本次实际解析 `assets/bbs/assets/actions.bobj` 得到**85个命名动作条目**；它们不是85个本片专用动作，也不是全部适合剧情。完整名称、骨骼、关键帧计数见 `bbs-file-evidence.json`。

优先测试 `idle`、`running`、`sprinting`、`crouching_idle`、`sleeping`、`emote_pointing`、`emote_thinking`、`emote_exhausted`。其中running与sprinting语义要按播放器实际绑定核对，不能只按英语名字推断速度。`emote_shrug/confused/yes/no/wave`只取克制片段，不能整段喜剧化套用。

**动作与模型必须成套**：`models/emoticons/steve/default.bobj`及`models/emoticons/alex/slim.bobj`是actions.bobj路线的优先骨架。另有MichaelCreeper_的 `models/player/steve_bends/`、`alex_bends/`及3D外层版本，均附 `.bbmodel`与`.bbs.json`。实查这些弯曲player模型的 `animations` 为空，不能声称它们自动带85动作；若改用它们，需要重定向或关键帧编排。眼睛与嘴模型在 `models/player/eyes*`、`models/player/mouth/`。

许可证据不一致：Modrinth项目页标ARR，实际包内LICENSE_bbs是MIT声明。**可把官方完整包作为隔离试验输入，不把抽出的动画/作者美术另行宣称MIT后上传。** 不安装Emotecraft Flashback插件来配BBS，也不假设BBS演员会由ReplayMod完整记录。

来源：[作者发布页](https://modrinth.com/mod/bbs-mod)、[作者模型文档](https://github.com/mchorse/bbs-mod-wiki/wiki/Models)。新版文件内容以本轮实查为准，旧GitHub归档的1.20.x说明不能否定当前1.21.1发行包。

### Cycles Pack的具体选择

作者原帖：[Cycles Pack](https://www.mineimatorforums.com/index.php?/topic/72227-cycles-pack/)。README保留作者署名，作者明确表示无需署名但欢迎署名；未把这种使用说明扩张为随意再分发许可。

已看5个GIF各4个等间隔帧，未看完整正常速度。初选 **Walk Cycle 1** 用于学生/路人日常步态；**Run Cycle 2** 用于克制跑动参考；Run1手臂和腾跃较夸张，不作救援默认动作；Run3明显前倾，仅作为急跑对照。最终脚滑、循环接缝和速度仍需正常速度检查。Idle文件没有对应GIF，不能声称预览通过。

适配不是从零写运动：将 `.miframes` 的part_name、旋转/位置/弯曲通道映射到目标骨架，按tempo24转换时间，保留曲线与根运动，之后只修接触和角色比例。BEND_ANGLE等通道不是旧item_display的同名字段，必须显式转换。若改走BBS，先在同一目标骨架上验证，不把两套骨架混着套。

## 大型皮肤库与逐角色候选

已实际打开并进入作品/分类的库：

- [Planet Minecraft](https://www.planetminecraft.com/skins/)：作者作品页、Java/Bedrock、Steve/Alex和下载入口可追踪；本轮主要筛选来源。
- [The Skindex](https://www.minecraftskins.com/search/skin/construction-worker/1/)：工人皮肤及作者库，作为补充。
- [NameMC学生库](https://namemc.com/minecraft-skins/tag/student)：适合查外观，但不能把穿着者当原创作者或许可人。
- [LittleSkin皮肤库](https://littleskin.cn/skinlib)：中文社区入口，本环境只取到动态页面外壳，尚未获得可核实的具体作品。
- [MCSkins HD入口](https://mcskins.top/)：有128×128分类；本轮打开了CharmieXD的Tokyo Revange boss base。该作品题材不适合本片，不因HD就选。

下面是已定位到作品的角色筛选表，**尚未完成画面质量与再利用许可审核，不是已验收的七张精细皮肤**。本环境PMC文件与预览请求返回403，浏览器工具两次超时；没有把网页下载按钮当作PNG已取得。

| 角色 | 具体作者作品 | 初筛理由与待修处 |
|---|---|---|
| 陈师傅 | [ClearPixels — Construction Worker 2](https://www.planetminecraft.com/skin/clearpixels-construction-worker-2/) | Java/Steve，作者列安全帽、反光背心、工具带、手套、靴子；适合先审工人造型；脸部年龄、配色须看预览决定 |
| 工友/safety | [ClearPixels — Land Surveyor](https://www.planetminecraft.com/skin/clearpixels-land-surveyor/) | 同作者职业服装系列，便于统一材质风格，与陈保留辨识度 |
| A | [Nelopsia — Flynn in Uniform](https://www.planetminecraft.com/skin/flynn-in-uniform-school-project/) | 同作者School Project系列；角色脸型、发色不自动改写本片，先审服装/头发层次 |
| 周然 | [Nelopsia — Flyke in Uniform](https://www.planetminecraft.com/skin/school-projext-uniform-06/) | 与A配对审同系列，不能因名字相似就视为相同模型；需确认Alex手臂宽度 |
| 教师 | [StarryWayWishes — Sapphire Moon Teacher Uniform Male](https://www.planetminecraft.com/skin/sapphire-moon-teacher-uniform-male/) | 作者明确教师制服；这是制服素材，不能当完整教师角色完成。先与学生制服配色比较 |
| 老人 | [Optifine — Grandfather / Old-man Skin](https://www.planetminecraft.com/skin/grandfather-old-man-skin/) | Java/Steve，有明确原作者；是否符合本片老人而非喜剧卡通需视觉筛选 |
| 路人/filmer | [JustaFlqmingo — olive jacket](https://www.planetminecraft.com/skin/olive-jacket-7087429/) | 已定位作者单项作品页，Java/Alex；作为日常外套候选，仍须核实配色、脸部和授权；**未验收** |

明确排除：lushbug的Construction Worker 4109919，作者自己说明背带裤来自Skinseed但不知原作者，来源链不完整；影视动漫IP皮肤不因热度高优先。Dreamiere Main1为HD Bedrock/Alex校服作品，证明社区有HD校服供给，但性别/风格不符合本轮主角，不强行塞进七人名单。

精细度评价看脸/发型/衣褶/二层结构与镜头距离，不只看128/256数字。标准皮肤进入现有色板rig需要UV重铺；进入BBS标准UV人物或Emoticons模型则可评估直接换纹理的低成本路线。此处允许改变演员实现以使用成熟资源，不再规定只能旧rig。

## 专门的表演资源：已找到具体条目

| 资源 | 明确覆盖 | 获取/适配情况 |
|---|---|---|
| [BladerInc Realistic Turning](https://www.mineimatorforums.com/index.php?/topic/71273-realistic-turning-animation/) | 自然转身；作者有演示和Reference.miobject链接 | 已追到原文件地址，Discord旧链接本轮SSL失败；作为第二来源，不能声称已下载 |
| [guitt Breathing](https://www.mineimatorforums.com/index.php?/topic/97910-breathing-animation-shortness-of-breath-animation/) | 呼吸/急促呼吸.miframes | 作者提供4个主镜像，Google本轮SSL失败；记录确切来源，非“自己找一个呼吸动作” |
| [Mineshaft Background characters cycles](https://www.mineimatorforums.com/index.php?/topic/74035-background-characters-cycles/) | 背景人物循环、行走 | 原帖把下载放视频说明，本轮未取得最终文件 |
| [ActorCore Daily Motion清单](https://file.reallusion.com/ActorCore_Daily_Motion_Animation_List.pdf) | Male_Walk_relaxed、Male_Sit_talk_Anim、Male_Stand_to_sit_Anim、Walk_while_thinking_Anim | 制作商官方18项清单已核；未登录下载或购买。比笼统搜索“自然动作”更贴近课堂/休息室 |
| [MoCap Online Mobility](https://mocaponline.com/products/mobility) | 起步、停步、90度转身、蹲起 | 专业动捕，优先Walk_F、Stand_Relaxed_To_Walk_F、Walk_F_To_Stand_Relaxed_RU、Stand_Relaxed_L_90/R_90；FBX/Blender均有，付费未购 |
| [MoCap Online Conversation](https://mocaponline.com/collections/archviz-animations/products/convo) | 克制对话、倾听、悲伤、方向手势 | 初选Convo_01_Low_Key、Convo_11_Listening、Convo_07_Sad，避免整段高幅度夸张表演；付费未购 |
| [MoCap Online Office/Desk](https://mocaponline.com/collections/archviz-animations/products/desk) | 坐姿、站姿与活动过渡 | 适合S04/S07生活动作来源，不能仅凭产品说明认定已有本片收包/扶人组合 |
| [MoCap Online作者免费Demo](https://mocaponline.itch.io/mocap-online-demo) | 多类动作的管线测试样本，232MB | 未取回，不把免费样本等同全套付费库；官网还写有AI用途附加许可，需核清Agent处理和传统影片使用的边界再接入 |

这些库证明现成运动/表演供应充分。需要定制的主要是**本片接触关系**：推离老人、双人扶起、袋子与手机/外衣的抓放；不能因需要修接触就否定基础动作库价值。

## 选型决定与Windows下一段

**优先验证 BBS Emoticons人物＋包内基础动作＋社区皮肤的路线**，而非立即继续加固旧色板演员。BBS弯曲player模型为比较组，Cycles/专业动捕为运动来源补充。新版BBS的录制/导出可以成为独立实现；必须实测其演员与ReplayMod互操作，不能假定保留ReplayMod是唯一解。

在实例副本只做一个12秒试段：0–2s静止；2–6s步行停步；6–8s指示；8–10s思考反应；10–12s恢复中性姿态。模型与动作要匹配。用同一人物皮肤与旧rig比较肘膝连接、衣服变形、步态/停步、面部及可重复导出。先复用包内模型与纹理验证动画链路，随后换候选皮肤验证UV；不能把这一步样片标成七角色最终美术。

规划端负责输出皮肤确切文件/身份映射与转换规格；Windows只负责按既定片段实机跑和回传证据。试验没通过不全片迁移；试验通过后再把既有85镜编译到选定演员后端。地图/光影之前的候选继续保留，不能拿本报告作为放弃精细美术和复杂场景的理由。
