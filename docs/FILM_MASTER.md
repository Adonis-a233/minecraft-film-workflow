# 声明式镜头、章节与全片总控

`film-master-preview/run` 把镜头导出、逐幕剪辑和全片拼接接在一个 JSON 计划下。Agent 可以编写计划；文件校验、游戏写操作、剪辑和证据记录由确定性代码执行。每个输出都有固定路径与哈希，已有文件不会被覆盖。

## 旧稿示例

`assets/productions/v10-master-draft-20261009/master-plan.json` 是旧版 **制作草稿** 的迁移样例：8 章（S01–S07 与片尾）、68 个声明式镜头、原生回放母版、分镜机位、两版字幕、图文卡、共享街头事件、连续全片音轨。镜头素材放在 `assets/footage/v10/`（Git LFS），回放母版放在 `assets/replays/v10/`，图文与 ASS 放在 `assets/graphics/v10/`。旧章节 MP4 被复用作配方的临时声音来源；这不代表声音已验收。

克隆并执行 `git lfs pull`、`scripts/bootstrap.ps1` 后，可以在仓库根目录离线查看完整动作清单：

```powershell
$ffmpeg = (Get-Command ffmpeg).Source
$ffprobe = (Get-Command ffprobe).Source
uv run --locked minecraft-film-agent film-master-preview assets/productions/v10-master-draft-20261009/master-plan.json --ffmpeg $ffmpeg --ffprobe $ffprobe
```

`preview` 不写文件：同时报告技术状态与独立的 `review` 状态。已有镜头没有人工审核记录时，章节显示 `waiting_for_review`。执行命令为 `film-master-run`，使用相同 JSON、FFmpeg/ffprobe 参数；它按依赖顺序处理需要重导的镜头、需要重建的章节，再编双版全片；每次新镜头或章节完成后暂停，人工审核通过后再次执行同一命令恢复。旧稿的**完整 510 秒重构尚未运行或验收**，本配方目前只能证明输入声明、哈希和任务图完整。旧 MP4 的技术回归见 [全片拼接说明](FILM_ASSEMBLY.md)。用户已将旧片定为草稿，剧情、表演、物理和声音不以本次迁移结论代替验收。

## 使用自己的版本

1. 复制 `film-plan`、`film-shots` 和八章 `film-chapter` JSON；给新计划、新镜头输出、新章节输出和全片输出指定尚不存在的版本化路径。
2. 改相机、tick 区间、镜头取样、图文、字幕或音频后，更新相应输入 SHA-256 和顶层文件 pin。镜头的 `accepted_spec_digest` 是旧画面的规格指纹；改镜头声明时保留旧值，预览会显示 `accepted_render_spec_changed`，要求实机重导。重导成功后使用收据中的新输出哈希。
3. 改角色资源包时，为受影响的镜头指定新包哈希、启用的资源包 ID 顺序和新输出路径。镜头重导前桥接会查询游戏当前启用的资源包列表，并对实例中的 ZIP、回放母版逐文件校验；任何不一致都拒绝拍摄。
4. 用 `film-master-preview` 检查将重导哪些镜头、重建哪些章节；核对后用 `film-master-run`。实机导出需要运行中的 Minecraft 1.21.1 Fabric 实例、ReplayMod 2.6.27 与本仓库新构建的 Cinematic Bridge，并传 `--instance-dir`、`--endpoint` 和密钥参数（见 CLI `--help`）。不要把密钥写入 JSON 或提交到 Git。

样例资源包中，v8 主场景、v11 的 S07 收拾镜头、v12 的共享街头事件各有独立声明。`NicoRTX_JapaneseSchool_resources.zip` 来自第三方校园素材，本仓库**未重新分发**；实机重导前须自行取得兼容版本，放到 `assets/resourcepacks/external/NicoRTX_JapaneseSchool_resources.zip`，文件 SHA-256 必须为 `004b53d73934c1304ad0769af81c0a0d8f484008d3d4bb6b90e3805b71c2406c`。已有镜头的离线剪辑不依赖本机安装该包。校验并复制八份回放母版和资源包到自己的实例，可运行 `scripts/prepare-v10-instance.ps1 -InstanceDir <实例目录>`；确认预检通过后再加 `-Apply`。脚本拒绝覆盖不同哈希的已有文件。

## 仍需补足的换角边界

S01 的 39–45 秒收拾包镜头、S03 的 55–57 秒收手机和 72–75 秒取衣镜头，暂以固定哈希的视频片段导入。它们的回放和机位资料留在原项目，但当时启用的资源包版本缺少足够证据，本例没有伪造可重导声明。更换相关角色后，这三段也必须建立经核对的镜头声明并重渲，不能沿用旧视频。片尾固定图文与剧情图文卡不是角色画面。S07 收拾镜头的 v11 资源包版本有部署记录，因此已作为可依赖镜头登记。

目前换角工具生成兼容的分部件模型资源包，`film-master` 能按镜头规格变化级联到章节与全片；**“给一张普通 64×64 皮肤 PNG 直接一键出片”仍不成立**。分部件建模格式、镜头中角色参与关系与上述三段回放还需补齐。当前版本的 Java/Python 离线测试和 S01 局部重建不能代替新资源包的真实实机重导验收。

## 2026-10-27 修复：内容指纹与审核关卡

实施范围、验证和旧稿换行 pin 阻塞见 [修复记录](WORKFLOW_FIXES_20261027.md)。

镜头内容指纹现为第 2 版：包含有序的全部启用资源包 `(profile_id, sha256)`、母版、相机、tick、尺寸、fps 和可选 `render_dependencies`，不再包含输出路径。次级资源包重新 pin 后也会使旧镜头失效；未启用的包不会影响镜头。迁移镜头路径时必须保留并验证原输出哈希；有收据时新路径的声明哈希还必须与收据一致，程序不会回退到旧路径。

**旧 `accepted_spec_digest` 和旧渲染收据不会自动升级。** 第 1 版没有保存足够的次级包证据，预览会将其列为 stale。保留旧草稿原样；建立新版本计划和输出路径，核对完整资源栈后重导。不要直接重算并填入新指纹来消除 stale，这不能证明旧影片是在当前环境下生成的。

可在单个镜头增加 `render_dependencies`，例如：

```json
"render_dependencies": [
  {"path": "assets/render-locks/pilot-environment.json", "sha256": "<实际文件的64位SHA-256>"}
]
```

这是字段示意，尖括号必须换成实际哈希。锁文件可记录 shader ZIP/选项、Iris/Sodium/导出器版本；需直接 pin 的文件也可逐项列入。缺失或改变会使镜头失效，并在连接游戏前阻止导出。此机制只检查声明的文件，不会自动证明游戏启用了对应 shader。原有资源包和回放仍由桥接核对实例文件。动作、地图初态和 rig 改动需要新录制的回放母版；改这些文件后重导旧回放不能产生新表演。

### 人工审核与恢复

1. 执行 `film-master-preview`，取得待审核目标的 `review.target`、`review.spec_digest`、`review.output_hashes`，并找到对应输出文件。
2. 正常速度审看；对接触处检查关键帧，章节与成片还必须听声音。将下列记录保存到独立 JSON 文件，按实际结果填写。
3. 执行 `uv run minecraft-film-agent film-master-review <计划路径> <审核JSON路径>`。此命令不需要游戏连接或 FFmpeg。
4. 再执行原 `film-master-run`。未审核或 rejected 会保持暂停；新镜头完成后先审镜头，章节完成后先审章节，全片完成后还需终审。

审核 JSON 示例（占位哈希不能直接提交）：

```json
{
  "target": "shot:PILOT_SUPPORT_FRONT",
  "spec_digest": "<从当前preview复制>",
  "output_hashes": {"output": "<从当前preview复制>"},
  "reviewer": "实际审核人",
  "reviewed_at": "2026-10-27T16:00:00+08:00",
  "decision": "approved",
  "normal_speed_watched": true,
  "checks": {
    "geometry": "pass",
    "performance": "pass",
    "composition": "pass",
    "continuity": "pass",
    "sound": "not_applicable"
  },
  "notes": "记录实际检查范围、证据和发现。"
}
```

`target` 还可以是 `chapter:S02` 或 `film`；章节和成片的 `output_hashes` 包含 `clean`、`subtitles` 两项，声音必须为 `pass`。无声单镜头允许 `sound: not_applicable`。拒绝时填 `decision: rejected` 并在 notes 记录原因；修复后使用新 take/版本路径和当前绑定重新审核。程序检查字段完整性、正常速度审看声明和哈希匹配，无法替代审核人的真实观看或认证其身份。

记录保存在 `work/film-master/<plan_id>/human-reviews.json`，追加保留历史；与执行共用计划锁。内容、输出或上游规格变更使对应旧批准失效；仅镜头文件搬迁且哈希一致可复用批准。`master-journal.json` 的 `needs_review` 是正常暂停，只有全部技术任务和人工审核完成才记 `succeeded`。未声明的外部制作依赖、动作段初末态与三段固定视频的资源归属尚未自动建模。
