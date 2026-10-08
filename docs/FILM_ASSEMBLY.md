# JSON 驱动的全片拼接

`examples/film-assembly-v10.json` 固定了 v10 八章的双版片源、每章来源 manifest 哈希、连续音轨哈希、输出规格及路径。15 个独立章节 MP4 保存在 `assets/renders/`，通过 Git LFS 下载；片尾两版共用同一段画面。FLAC 连续音轨可无损解码回拍摄时使用的 48 kHz、双声道、16-bit PCM。

安装 FFmpeg 与 ffprobe 后，在仓库根目录运行（把可执行文件路径按实际安装位置替换）：

```powershell
$ffmpeg = (Get-Command ffmpeg).Source
$ffprobe = (Get-Command ffprobe).Source
uv run --locked minecraft-film-agent film-assembly-preview examples/film-assembly-v10.json --ffmpeg $ffmpeg --ffprobe $ffprobe
uv run --locked minecraft-film-agent film-assembly-run examples/film-assembly-v10.json --ffmpeg $ffmpeg --ffprobe $ffprobe
```

`preview` 只读，验证章节 manifest、源文件哈希、视频规格、FLAC 解码后的 PCM 哈希和输出路径。`run` 直接拼接八章 H.264 视频，复用一条连续音轨生成两版 MP4；双版须通过完整解码、恒定帧率、黑场、音频包时间戳和音轨一致性检查才发布。输出进入 `work/film-assembly-output/`，证据进入 `work/film-assembly/<film_id>/result.json`。入口拒绝覆盖已存在的输出；再运行要改新的 `film_id` 和输出文件名。

本例在原项目中运行后，clean 和 subtitles 的 SHA-256 分别为 `9ea4b939cc16235cba4cf35b838e2276cba45c438bb3156b0f9729a53fcba037`、`3234117a8c9725c502138a70e7f987e02091a9ca502181c2f04cfd1965eaeddf`，与已有 v10 **草稿**逐字节一致。这个回归只证明**现有章节到草稿影片**的确定性拼接；用户已明确本次构建需要大量重构，仅作为经验收集。

现有正式拍摄控制器可执行结构化演员动作和单镜头导出，但 v10 各幕最终的回放 ID、相机轨道、竖屏插入、ASS 图文、章节首帧修复仍分散在逐幕制片记录和脚本中。更换角色外观后，必须先重新渲染受影响画面，再用新章节更新此 JSON；直接运行本例只会拼出原角色画面。

本次工作流审计发现原制片项目 `work/classmate-mayuan-20261004/` 中有 347 个 `.py` 文件（含探索、试拍和废弃候选，并非 347 个正式环节）。全片拼接原先由 `build-full-loading-review-v10.py`、`build-full-shared-release-review.py` 等临时脚本串联；这一段现在由 `film-assembly-preview/run` 覆盖。镜头导出、逐幕剪辑、剧本对白比对和人工视觉审阅仍需继续迁入可检查的正式格式。
