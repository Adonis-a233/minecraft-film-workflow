# Windows 新表演候选与恢复（2026-10-30）

状态：用户已授权继续拍摄。当前交付是新表演的待审素材，尚非85剪辑单元的新版成片；所有人工审核均 pending。主线仍使用原世界、原角色绑定、ReplayMod。原始世界不写入，新运行均为副本。

## 本轮实现与证据

- `ContactEntryMotion` 使用原两段0.375格骨长，手先接近再建立支撑；Python/Java均限制老人起身必须晚于两侧接触入口。全身接触/释放过渡也同步处理，不能仅放宽校验。
- 新增仅路人可用的 `phone_record`。专用手机持握模型使用新CMD72533；阅读/通话模型不改。模型由本机原v12派生，生成器可交接，素材不随代码再分发。
- 手机相机来自同次实测item_display变换，包含原版渲染器Y轴180度旋转和ReplayMod实体视高1.62格补偿。逐tick检查光心不在拍摄者自身网格内部。这不是视锥无遮挡/剧情取景的完整证明。
- 资源包API启动时曾返回空列表；录制进程的ResourceManager重载行与运行锁哈希作为替代历史证据，出处写入相机provenance。没有把空列表当作已加载证明。
- Java离线完整构建25任务通过；Python相关54项通过。实际轨迹仍存在较大的走路关节逐tick变化，尚未完成自然步态验收。

## 新录制与拒收

|运行|实际范围|结论|
|---|---|---|
|v11-shared-entry-20261030a|2090tick / 104.5秒|完整监控候选；扶人细节首次黑帧拒收，同master补导成功|
|v11-phone-record-20261030a|2090tick / 104.5秒|完整新表演；早期手机导出因光心/网格遮挡由Agent拒收，不作为有效手机故事素材|
|v11-phone-optics-20261030a|200tick / 10秒|短诊断；几何检查发现光心仍在手臂内部，没有伪造可用镜头|
|v11-phone-grip-20261030a|200tick / 10秒|专用持握实机；手机4.9秒147帧720p通过解码/黑帧检查；抽帧无自身头手遮挡，仍需完整视觉/剧情验收|
|v11-shared-grip-20261030a|2090tick / 104.5秒|本轮完整新表演，最新动作JAR和专用持握；具体结果见同目录进度记录|

`execution/<run>/actor-plan.json` 是合同计划，不是导演JSON。运行锁记录实际Mod、资源包和光影文件哈希。手机/监控共享同一master，不重演两个版本。历史回放仅作诊断对照，不充作本轮新素材。

本地证据为 `work/<run>/`：capture-journal、master、trace-summary、candidates、导出记录。视频在 `assets/footage/<run>/`。不提交账号、token、UUID追踪原件、原生回放、世界、临时声音或未获再分发许可的资源。逐角色坐标、动作、道具目标、机位在 execution 内；这些仅覆盖本次E候选，不能宣称全片执行计划完成。

## 启动与恢复

项目根目录 PowerShell：

```powershell
$env:PYTHONPATH='agent/src'
# 先查询状态；不要在未知结果下重发
.venv/Scripts/python.exe scripts/capture_actor_candidate.py work/v11-shared-grip-20261030a --status
# 新运行队列只执行无上游依赖的独立候选；已有journal保留不重录
.venv/Scripts/python.exe scripts/run_candidate_queue.py work/v11-shared-grip-20261030a/candidate-queue.json
# 已保存master补导，需先关闭旧实例，再启动相同运行实例；不要改变它的运行锁
.venv/Scripts/python.exe scripts/launch_game.py --version-dir game/instances/1.21.1-Fabric-0.19.3-fix-20260930 --working-dir game/instances/v11-shared-grip-20261030a --log work/v11-shared-grip-20261030a/recovery-NEW.log
# 新导出ID和输出名称；已存在路径不覆盖
.venv/Scripts/python.exe scripts/export_saved_candidate.py work/v11-shared-grip-20261030a work/v11-shared-grip-20261030a/phone-views.json --export-id recovery-NEW --width 1920 --height 1080
```

若submitted/未知，先读operation resolution、master/render状态和文件，不删journal。失败只补导受影响视角，表演本身失败才新建run重拍。独立候选队列不写人工批准，不替既有总控放行。

## 尚未完成

- E路人先拍路线再转向、惊动、陈的工作意图、老人完整离场及对白口型；完整自然速度视觉/剧情验收。
- 手机竖幅取景及信息遮蔽须审看；当前16:9光学诊断包含落板，不能自动认定为S01/S03可用版本。
- 104.5秒唯一时间轴已有临时声音生成器，落板声来自实际落地tick；临时配音/合成撞击声不作最终声音，脚步、布料、环境及呼喊待补。
- 其余85剪辑单元尚需逐镜可执行合同、初末态和后期映射；醒来、转身、关投影等能力仍按交接缺口核实。不得把本轮E诊断替代全片。

已实现、实机技术通过、Agent抽帧观察、人工视觉已审核四种状态分别记录；本轮没有任何人工视觉批准。

## 本轮审看产物

`assets/footage/v11-shared-grip-20261030a/event-review-with-guide.mp4`：104.5秒/3135帧/720p30，完整解码通过；手机1080p5秒与扶人1080p10.5秒另存同目录。仅供审看，声音为临时参考。逐输出哈希见 [进度记录](execution-progress.json)。拾物1080p黑帧拒收，未发布到footage；同master监控保留。

本次完整母版仍含修复前的触屏目标，必须保留为诊断。已修正专用持握的屏幕目标Z为+0.143125格（原版item mesh Y(pi)翻转后的实际位置）；不把本次母版倒称为修复后表演。下一次整体E采用短段测试后的实现。

停录修复短段 `v11-stop-grip-20261030a` 已实际新录200tick；内部触点误差和导出状态见 [短段结果](stop-grip-result.json)。侧后视角技术通过但遮住屏幕，正面黑帧拒收，故仍不能宣称真实手屏接触视觉通过。仅修复了已证实的专用模型坐标符号，不追溯改变旧母版。

拾物失败视角已从同一master定点补导：`pickup-recovered1080.mp4`，20秒/600帧/1080p30通过解码与黑帧检查。原失败文件保留；没有重拍上游或替换事件事实。
