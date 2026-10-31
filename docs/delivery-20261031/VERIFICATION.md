# 交付核对

2026-10-31 Mac文件检查：

- ready交付锁83个文件逐个大小/SHA256一致；锁包含现有地图与完整音轨引用。
- 七张PNG签名、64×32尺寸正确；原图从SkinsDB API下载，保留作者/许可/ID，未做像素修改。只完成平面正面初筛，未验收游戏内UV、动态或最终美术。
- 完整原片FLAC解码为510秒48kHz双声道；66个cue分别完整解码成功，未变速。它们来自现有字幕时码，须审听并对齐Windows当前镜头，不代表纯对白分轨。
- 两份世界/场景ZIP CRC通过；没有实机打开世界或执行补景。
- 光影运行包是标准Modrinth索引，引用已下载校验的官方文件；未将禁止镜像的Complementary ZIP重新上传。
- 动作预设12项、原规划镜头85项；均为交给现有Windows适配器的明确规格，不冒充已经编译、已经运行的BBS Film。
- main通用拆分测试：354 passed、24 skipped。Java构建尝试失败于Mac Java25/Gradle8.10.2不匹配，需Java21再验；未修改Bridge Java源码。本片资源和规划仅进入影片分支。

Windows先运行 `python scripts/verify-production-ready.py`。验证只读，不安装、不修改游戏实例，不替代视觉/剧情/声音验收。
