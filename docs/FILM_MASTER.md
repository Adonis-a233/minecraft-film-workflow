# 声明式镜头、章节与全片总控

按 contracts 中的 film-plan、film-shots、film-chapter 合同准备自己的版本化计划与素材。运行 `minecraft-film-agent film-master-preview <计划路径>` 查看依赖和审核状态，使用 `--help` 查询当前参数。preview检查通过后，用film-master-run执行。每个输出指定新路径，保存输入哈希与审核记录。

现有游戏导出后端依赖Cinematic Bridge及相应ReplayMod实例。BBS原生Film导出需要独立适配器，当前通用CLI不承诺直接执行任意BBS计划。开发者须提供真实实例路径、资源栈、回放与相机合同；不要将导演规划直接当执行合同。

## 内容依赖与审核

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
