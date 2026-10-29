# Windows 实拍交接（2026-10-29）

结论：原 Windows 资产可用，已产生新的 ReplayMod 表演和待审视频。这里是执行准备与诊断交付，不是新版影片完成。85 个导演剪辑单元仍未全部编译为可拍计划。

## 保留与版本

- 远端 main 核对为 `98b29b78aaa247f2f81c0a6f037624190086ce2d`。在其上建立 `codex/windows-v11-20261029`，未合并本地三次独有的架构变更。
- 原本地 main 留在 `codex/windows-pre-v11-20261029`；155 项删除状态存于 `stash@{0}`（名称 windows-v11-20261029a-preserve-before-main），另存 `work/windows-v11-20261029a/pre-sync.patch` 与 status。不要清 stash，也不要把恢复出的全部本地资产一起加入 Git。
- 原拍摄实例：`game/instances/1.21.1-Fabric-0.19.3-fix-20260930`。本次只在新的实例/世界副本写入；每次准备对源世界逐文件 SHA256 前后比对。原始世界与旧回放保留。
- `assets/actors/classmate-20261004/visual-binding-v10.json` 和原启动器从保留分支恢复。绑定及地图/皮肤/声音二进制仅本机保留，本提交不替它们宣称再分发许可。

## 本机锁

- Minecraft 1.21.1、Fabric 0.19.3、ReplayMod 1.21-2.6.27；原 Axiom 6.0.2、Mocap 1.3.10、Flashback 0.39.8、Iris 1.8.8、Sodium 0.6.9、Carpet 1.4.147 保留。录制/相机/导出均用 ReplayMod。
- 资源包次序 NicoRTX_JapaneseSchool_resources → Fabric/Mod → Classmate_Kanjian2_1.21.1_v12；ComplementaryReimagined_r5.2.2。未安装素材候选清单中的新 Mod/皮肤/地图。
- Java `C:/Users/27303/.jdks/ms-21.0.10/bin/java.exe`；Python `.venv/Scripts/python.exe`；FFmpeg `tools/ffmpeg/bin/`。启动堆上限4G；共享 Minecraft 缓存明确为 `C:/Users/27303/AppData/Roaming/.minecraft`，不会扫描猜测。
- 实测显卡 RTX 5060 Laptop，nvidia-smi 总显存8151 MiB；游戏日志证实同一 OpenGL Renderer，驱动616.92。未测峰值显存，不能据此外推4K/新增光影容量。
- [当前紧凑路线运行栈哈希](runtime-stack-lock.json) 覆盖实际部署 JAR、所有 Mod/资源包/光影目录内容及选中次序。每个本地包的 `environment-lock.json` 是复制时快照；**实际部署以 capture.json 的 bridge_hash 和 runtime-lock/final-runtime-lock 为准**。早期包 final-runtime-lock 为事后观测，不能追溯证明整个录制期间均未变化。
- token、账号、原生回放、世界和声音均不提交。运行时从该新实例 `config/cinematicbridge.token` 读取，不打印内容。

## 产物与审核

[逐运行进度/哈希](execution-progress.json)；可执行 actor-plan 和已测机位位于 [execution](execution/)。这些是诊断合同，不等同于85个正式剪辑镜头。

| 本地 run_id | 新表演内容 | 范围/限制 |
|---|---|---|
| v11-contact-20261029b | 推离、失衡、落板，4人200ticks | 冷开首导出全黑并拒收；后续5秒细节和回跳10秒通过；没有散物/拾物，不是完整E |
| v11-pack-20261029a | 周然坐姿收包200ticks | 3机位；未证明S01通知/持物跨段连续 |
| v11-phone-20261029a | 陈接听→放手机→坐姿200ticks | 3机位；并非通用手机状态机 |
| v11-coat-20261029a | A手机→取衣→持衣200ticks | 3机位；没有持衣走出门 |
| v11-dialogue-20261029a | 双人嘴形200ticks | 无同步声音 |
| v11-dialogue-sync-20261029a | 重新表演，按临时原声音RMS驱动口型 | 2机位；另有 dialogue-with-temp-voice.mp4；2秒入声，10秒视频，AAC，完整解码通过；临时配音未听审 |
| v11-standpack-20261029b | 陈20idle→160站姿收包→20idle | 3机位；未包含接电话/走门边 |
| v11-compact-pickup-20261029b | 停录→走入→四件拾物，1720ticks | 首次实机验证1520tick紧凑路线，3导出；仍需76秒拾物 |

所有视频为1280×720/30fps诊断候选，位于 `assets/footage/<run_id>/`。本地 `work/<run_id>/master.json` 指向本次新录制的 `.mcpr` 及哈希；不是重导旧回放。capture-journal、actor-result、trace-summary、candidates.json、blackdetect日志均在同包。

技术验收只覆盖时长、尺寸、帧数、CFR、完整解码、黑帧检测及轨迹。**人工视觉/剧情/听审记录均未获得，所有候选 pending，没有写入任何人工批准。** Agent抽帧观察另记，不能代替完整正常速度验收。

## 拾物实现与已知差距

旧3040ticks路径保持兼容。新增1520ticks模式把每件物的三段绕行缩为一段直走；所有蹲下、触物、抬起、直立、入袋、撤手原时长保留，不变速肢体。Python、Java ActorPlan/Service/Visuals、GroceryProps所有权时钟和JSON合同同步更新；逐tick路径仍检查地面、空间、区域、朝向、位移，未放宽现场容差。

Gradle全构建通过，原路线3040与新路线1520均检查连接和关节；Python相关167项通过。新实机轨迹：1520拾物帧，最大根位移0.03783171格/tick，最大关节逐帧11.7359度，肘连接误差1.63e-7格；四次抓取tick360/730/1100/1470，入袋525/895/1265/1635；最终四物均仍存在且collected=true。详见 [实际轨迹数值](compact-trajectory-check.json)。这不是穿模或自然度证明。

第一轮 v11-compact-pickup-20261029a 在tick200因入口不符失败。两人起始相距0.4格，后续碰撞使路人偏离；保留失败trace、终态查询和失败回放。B轮改远处停录后实际走入，入点误差0.003953格、停止漂移0，未重发旧take。

**76秒仍不符合导演稿23.5–32.5秒窗口。** 该模式只是可复核的路线优化，不宣称已完成短单件拾物/多角色移交动作。完整E需继续实现按件所有权的短动作与自然步态，或显式调整E时基及全部消费者；不能把76秒无标记剪进32.5秒连续监控。

## 启动、查询、恢复

在项目根目录 PowerShell：

```powershell
$env:PYTHONPATH='agent/src'
# 只读查询当前对应运行（实例必须已启动；不要把不同实例token混用）
.venv/Scripts/python.exe scripts/capture_actor_candidate.py work/v11-compact-pickup-20261029b --status
# 队列保留已有journal，不重录；只执行 independent=true 且无depends_on的诊断
.venv/Scripts/python.exe scripts/run_candidate_queue.py work/windows-v11-20261029a/candidate-queue.json
```

新录制必须新run；以下为复现同类诊断的例子，不能覆盖已有路径：

```powershell
.venv/Scripts/python.exe scripts/prepare_v11_windows.py --source-instance game/instances/1.21.1-Fabric-0.19.3-fix-20260930 --source-world KJDS_SharedReleaseEvent_20261006f --source-plan docs/production-v11/windows-20261029/execution/v11-compact-pickup-20261029b/actor-plan.json --run-id v11-compact-retry-20261030a --pilot source
Copy-Item cinematic-bridge/build/libs/cinematic-bridge-0.1.0.jar game/instances/v11-compact-retry-20261030a/mods/cinematic-bridge-0.1.0.jar
.venv/Scripts/python.exe scripts/configure_actor_candidate.py work/v11-compact-retry-20261030a game/instances/v11-compact-retry-20261030a docs/production-v11/windows-20261029/execution/v11-compact-pickup-20261029b/views.json
.venv/Scripts/python.exe scripts/launch_game.py --version-dir game/instances/1.21.1-Fabric-0.19.3-fix-20260930 --working-dir game/instances/v11-compact-retry-20261030a --quick-play-singleplayer KJDS_v11_compact_retry_20261030a --log work/v11-compact-retry-20261030a/game.log
.venv/Scripts/python.exe scripts/capture_actor_candidate.py work/v11-compact-retry-20261030a
```

启动前确认25575无其他拍摄实例占用。构建命令：

```powershell
& C:/Users/27303/.jdks/ms-21.0.10/bin/java.exe -cp tools/gradle/gradle-8.10.2/lib/gradle-launcher-8.10.2.jar org.gradle.launcher.GradleMain -p cinematic-bridge --offline --no-daemon build --console=plain
```

运行中断先 `--status`，检查 `capture-journal.json` 和 operation resolution；submitted/未知结果不自动重发。已保存master可重新打开，已完成导出只校验同哈希，不覆盖。失败只新建受影响take/视角；不要清历史journal以强行续跑。队列若发现未决take/render会保留游戏进程并停止，正常needs_review才关闭其自己启动的窗口。

## 尚未放行

- [85镜状态清单](shot-readiness.json)：均没有虚构坐标、批准或ready标志；诊断引用不能替代逐镜初末态、道具持有者、最终相机与声音映射。
- 完整共享事件：推离/落板/扶人/停录/拾物需同一新master且正常速度审看；手机必须来自路人真实rig锚点及同一转动，当前固定外部机位只能叫取景诊断。声音事件需唯一时间轴，消费者S01/S02/S03/S05/S06一起更新。
- 醒来/床边落脚无已核实完整实现；肩髋转身/独立视线未过现场验收；教师关投影尚未实现动作与画面同tick联动。不能拿stand_up、look_at或后期黑屏冒充。
- 取外衣后的移动、接听到收包的状态、放手机后的重新接听，仍受已记录合同限制；拆段需要可验证道具交接。
- 新素材候选未试装；七角色沿用本机原绑定。全片1920×1080正式录制/声音/人工剧情验收尚未完成。

## 完整事件诊断与定点修复补记

`v11-shared-compact-20261029a` 新录四角色2080ticks、8320条轨迹，104秒连续高位版和5秒取景诊断技术通过。首次10秒扶人细节在回跳后全黑，已拒收；仅从同一新master补导，不重演上游。这一104秒版本沿用旧表演节拍，不是新稿32.5秒E；尚无同源声音时间轴，也没有真实路人手持相机曲线。

[逐关节筛查](joint-screening.json) 暴露推离入口99.93度、扶人入口82–83度跳变，仍需接近/搭手/负重过渡实现后重拍受影响段；未据此自动批准。路人兼任落板控制造成tick140手机突然消失/前臂105.21度跳变，现已修复为独立道具触发不改变持机视觉。新短拍 `v11-board-phone-20261029a` 同窗口138–142手机始终可见，最大关节变化3.42e-6度；两版3秒导出技术通过。[实机证据](phone-continuity-check.json)。修复只装新副本，旧共享母版仍保留原缺陷，不伪称已自动替换。

抽帧观察：紧凑拾物首件抓取与入袋可见，袋子与余物存在；身体蹲姿仍需正常速度检查，抽帧不够证明无穿模/自然度。正式人工visual review仍为0。

恢复闭环已实测：重新打开同一新master补导扶人10秒，黑帧检查通过；随后正常退出、重启对应副本世界，bridge确认in_world/目标save_name/unpaused/no blocking screen，无重发actor任务；最后正常关闭游戏。[恢复结果](recovery-result.json)。再次逐文件核对原SharedReleaseEvent世界，哈希与准备前相同。
