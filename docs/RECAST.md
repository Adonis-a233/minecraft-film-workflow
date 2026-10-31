# 兼容分部件角色的换角适配器

scripts/film_recast.py与contracts/v1/film-recast.schema.json保留为旧分部件模型的兼容适配器。角色槽位及部件格式受该合同限制，不是任意Minecraft皮肤导入工具，也不是BBS转换器。所需资源包由使用者自行提供。

运行 `python scripts/film_recast.py preview <配方路径>` 核对输入，使用build生成新资源包与manifest；工具拒绝覆盖原输出。配方字段以schema为准。

接入新角色体系时应新增可配置适配器并验证部件、UV与骨架，不直接更改旧合同的既有语义。资源包构建成功后仍需重新导出受影响镜头并审看。
