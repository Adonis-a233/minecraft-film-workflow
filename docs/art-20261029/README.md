# 美术优先制作批次 · 2026-10-29

结论：转入美术阶段，正式拍摄后置。本批交付陈师傅/A的首轮UV精修候选、四场背景补景模块、三款光影本地文件。角色/补景均为候选，不称作已批准美术定稿。

依据：`docs/materials-20261028/characters-and-animation.md`、`locations-and-look.md`、`pilot-and-adoption.md`。按“原角色精修→原场景局部升级→光影单变量对照”执行，保留现有七角色身份、主地图、10/12部件与确定性动作链路。没有混装CPM/Fresh Moves/家具/物理Mod，没有开启新拍摄。

## 本机产物

| 内容 | 路径 | 已完成 | 未完成 |
|---|---|---|---|
| 陈师傅 / A | `assets/art/v11-art-20261029e/` | 128/256两档专用UV、每档两张图集、两份可编辑.bbmodel、28部件模型覆盖、正侧背对照与静态姿态图、源哈希与rig锁 | 动作中关节遮盖、手机接触、实机材质/光影、人工审核 |
| 四场局部补景 | `assets/art/v11-sets-20261029b/` | C教室书柜、D宿舍收纳/衣架、W休息室工具/水具架、E围挡/支架，均有.schem、格子清单、离线色块图 | 在原世界副本内的放置、构图、遮挡、碰撞与光照核对 |
| 光影候选 | `work/art-look-20261029a/` | Reimagined5.9.3、Unbound5.9.3、Bliss2.1.2下载、与10月28日记录的SHA256逐项一致、附内置许可证 | 启用、同机位对照、性能和视觉验收 |

角色预览：`atlas-256/chen-comparison.png`、`a-comparison.png`；姿态：同目录`chen-pose-check.png`与`a-pose-check.png`。128档同文件名。候选e为当前版本；a/b/c/d是构建/渲染迭代痕迹，不覆盖或删除。

纹理细节：陈保留原工衣配色、安全帽、反光条和胸牌，加入衣缝、口袋和袖口；A保留原衣服、背包与发型轮廓，加入衣摆、袋缝和头发分束。没有用增加肢体尺寸遮盖关节，也没有套普通玩家皮肤。128档优先作中远景比较，256档保留作近景比较；尚未决定正式分辨率。

补景采用原版方块，四个模块都只是背景块，不包含替换演员使用的桌椅、手机或动作道具。D/W模块宽7格、高5/4格；不是现实尺寸家具CAD，离线示意图将小方块显示为完整方块，花盆/炼药锅等实际轮廓须后续在游戏静态美术检查。禁止直接覆盖既有场景或粘贴进演出通道。

## 验证边界

- 角色源包SHA256 `739ac8196aa0d7ce24abe46cef010227db478eae20cb956ed34d3258ec02617e`，绑定SHA256 `552cac54b798016962f5c26b5a51b938515f341af601ac82996a8dcb0e104fd7`。构建前后未变。
- 两档每个模型去除纹理/UV字段后与原JSON相等；骨长、部件、rotation/from/to、CMD入口保持原样；所有已有方块六面均保留。闭合面保留不等于旋转关节没有缝隙。
- UV独立打包，有一像素边缘扩展；高mipmap条件尚未验证。离线预览不模拟Iris、MC纹理插值或ReplayMod。
- 四份schematic由当前`load_schematic`读取，DataVersion3955，YZX顺序、尺寸、实际非空气方块数与设计清单一致；没有粘贴进世界。
- 原人物衍生包、.bbmodel和图像仅本机保留。公开提交仅含生成工具/文档/哈希；原人物授权不会因重新绘制纹理而消失。光影候选按原内置条款本地保留，不重新打包发布。

## 后续顺序

1. 精修陈/A的关节接缝与手/袖/手机局部，对比中性与屈肘/屈膝；先修改美术源，保留动作锚点。完成这两人的共同标准再推广其余五人。
2. 选D/W背景模块，在独立美术世界副本做静态布置与正反打检查；保持原场景和演员接触高度。C/E再按前中后景补齐，不下载/迁移整城来替代局部设计。
3. 静态无光影检查后，按原r5.2.2→Reimagined5.9.3→Unbound/Bliss逐个对照；记录天气、时间、曝光、显存。未启用阶段不提前宣称新光影可用。
4. 角色/布景/光影锁定后，才恢复24秒动作标定、接触试点及正式拍摄。人工审核记录仍须真实填写。

## 暂停的拍摄工作

`v11-contact-entry-20261029a`在tick1402失败，原因CH05演员消失/身份变化，未重发。旧游戏日志记录正常停止并保存全部世界；转美术时25575无监听。此前接触代码与104.5秒时基属于尚未提交的拍摄WIP，完整diff保存在`work/art-pivot-20261029a/pre-art-filming-wip.patch`；此次只提交美术工具与说明，保留这些本地改动，不继续修拍摄。

## 复现

运行`build_actor_art_candidate.py`需要Pillow和numpy，运行`build_set_art_kits.py`另需nbtlib和项目agent包。本机使用Codex bundled Python（工具返回的明确路径），通过PYTHONPATH添加`agent/src`及项目`.venv/Lib/site-packages`。所有输出目录必须不存在；脚本拒绝覆盖，永不安装、粘贴或启动Minecraft。

```powershell
$env:PYTHONPATH='agent/src;C:/Users/27303/Documents/Codex/Minecraft-Film-Project/.venv/Lib/site-packages'
$artPython='C:/Users/27303/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
& $artPython scripts/build_actor_art_candidate.py --source-pack game/instances/1.21.1-Fabric-0.19.3-fix-20260930/resourcepacks/Classmate_Kanjian2_1.21.1_v12.zip --binding assets/actors/classmate-20261004/visual-binding-v10.json --output assets/art/new-unique-character-run
& $artPython scripts/build_set_art_kits.py assets/art/new-unique-set-run
```
