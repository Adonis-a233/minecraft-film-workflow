# JSON驱动的影片拼接

使用contracts中的film-assembly合同描述自己的章节视频、来源manifest、连续音轨、哈希和输出路径。仓库不附带影片媒体。

运行 `minecraft-film-agent film-assembly-preview <计划路径> --ffmpeg <程序路径> --ffprobe <程序路径>` 只读检查，检查通过后以film-assembly-run执行相同输入。以CLI --help和合同为准。输出必须使用尚不存在的版本路径。

完整解码、帧率、音轨与哈希检查只证明技术结果；仍须审看正常速度视频、镜头衔接、声音和剧情。更改角色或动作需要先重建受影响镜头，不能只拼接旧视频。

总控与审核恢复见 [FILM_MASTER.md](FILM_MASTER.md)。
