# Bannerlord `.tpac` 资产格式规范（逆向结果）

> 本文档由实际工程逆向得出，所有结论都经过与原版/官方编辑器产出的资产做**字节级比对**验证。
> 配套工具：`mbtool`（C#，建立在 TpacTool.Lib 之上并修其缺陷）与 `tools/tpac.py`（独立 Python 读取器，用于交叉验证）。

## 逆向出来的 .tpac 格式知识（最宝贵的部分，务必保留）

### 1 文件结构

```
u32 magic 'TPAC' | u32 version(=2) | 16B 包GUID | u32 资产数 | u32 indexSize | u32 reserve
每个资产：
  16B 类型GUID | 16B 资产GUID | u32 资产版本 | 变长字符串 名字
  u64 metadata长度 | metadata 字节 | **u64 校验和** | u32 段数
  每段：u64 偏移 | u64 实际长度 | u64 存储长度 | 16B 段GUID | 16B 段类型GUID
        u64 数据哈希 | u32 标志 | u8 存储格式(0=未压缩 1=LZ4HC)
  u32 依赖数 | 依赖数×48B
```
- `indexSize` = 所有资产记录的总字节（**不含 36 字节文件头**）；段的 `偏移` 是**绝对文件偏移**。
- 段数据哈希 = **`xxh64(解压后的数据)`**（14/14 段验证通过）。
- **metadata 校验和 = `xxh64(u64le(metadata长度) ‖ metadata)`**（954/954 验证通过，含原版与编辑器产出）。

### 2 网格资产内部结构

- **Metamesh** 资产 → metadata 含：`version` / `Material(GUID)` / `UnknownFloat`(通常 3.4e38) / `bodyPart字符串` / `ClothMetamesh`(GUID) / `ClothUint`+`ClothString` / 子网格数组 / `Original` / `Variations` / 2 个 bool。
- 每个 **子网格(Mesh)**：`IsCompleteMesh` / `Lod` / `UnknownUint1`(=2) / `SecondMaterial(GUID)` / **`SubVersion`**(当前版本=2，**写错会导致解析偏移**) / `Guid` / `Name` / `Flags` / `Material(GUID)` / 4 个 vec4 / 顶点数们 / bbox / `UnknownInt2`(=用到的骨骼数) / `MaterialFlags` / `UnknownFloat1`(=1) / `ClothingMaterial` / `UnknownInt3`(=120) / 3 个 bool。
- 数据段：每子网格一对 `MeshEditData` + `VertexStreamData`，外加一个 metamesh 级的 `EditmodeMiscData`。

### 3 `VertexStreamData` 的二进制布局（**踩坑最多的地方**）

```
i32 索引数量
[索引数组]   ← 数量 < 65535 用 u16，否则先用 WriteStructArray 写一次数量再写 i32
[尺寸表]     ← 14 组 (u64 偏移, u64 长度) = 28 个 u64 = 224 字节
[数组们]     ← 顺序固定：
   Colors1, Colors2, Uv1, Uv2, Positions, 另一组Positions, Normals, Tangents,
   BoneWeights, BoneIndices, 压缩法线(X11Y11Z10), 压缩坐标(Half4),
   压缩切线(X10Y11Z10W1), [Q-Tangent(SnormShort4，仅当 metamesh 版本≥1)]
```
- **关键坑**：尺寸表里的"偏移"是**从尺寸表自身开头算起**的，所以**第一个数组的偏移必须是 224**（无 Q-Tangent 时 208），而不是 0。写成 0 会让引擎按偏移取数组时**整体错位 224 字节** → 渲染出扭曲/炸开的怪物。而顺序读取的解析器（TpacTool）完全看不出问题。
- 数组**不写长度前缀**（TpacTool 原版写盘器错误地写了，已修）。
- `u32 标志`：`VertexStreamData` 段为 1，其它为 0。

### 4 网格格式细节（都已用原版数据验证）

- **顶点坐标空间**：Z 轴向上、+Y 为角色正面、+X 为角色右侧，**人体高约 1.8 单位**（原版头发 mesh 的 bbox z∈[1.53,1.82] 可证）。
- **骨骼索引**：0..27 共 28 根，顺序 = `human_skeleton.fbx` 里骨骼名末尾的 `_N` 编号。**已用原版网格反查验证**：索引 1 的顶点质心在左腿、5 在右腿、14~18 在左臂、21~25 在右臂。
- **权重**：每顶点 4 个 u8 影响，和≈255（原版是 254）。
- **Q-Tangent**：存的是旋转四元数 (x,y,z,w)，其旋转矩阵的**三列依次为 (N, T, N×T)**；在 16497 个原版顶点上逐点吻合（误差仅来自 short 量化）。
- **压缩坐标** = float 坐标的 half 表示，W 分量 = 1.0。
- **压缩切线**的符号位 bit31：`1 表示 W 为负`。

### 5 物品/材质相关

- 材质贴图槽位：**0=反照率、1=第二色/遮罩、2=法线、4=高光**。
- 材质模板用 `plain_white_skinned`（不透明，单色图+法线+高光，shader `328d3572…` 是角色/布料标准 shader，<reference mod> 也用这个）；带 alpha 的用 `battania_dress_c_alpha_mat`。
- **`covers_*` 标志**：`ArmorComponent` 里没有对应属性，它们被反序列化成 **`MeshesMask`（`SkinMask` 位掩码）**，由原生代码决定隐藏哪些皮肤网格。
- **`covers_legs="true"` 原版只用在 `LegArmor` 上**（36/36），放在 BodyArmor 上**无效** → 这就是"原版靴子盖住自定义鞋子"的原因。

---

## 5. 已修复的关键 Bug（附证据）

| # | Bug | 症状 | 证据 |
|---|---|---|---|
| 1 | **尺寸表偏移基准写成 0**（应为 224） | 网格扭曲/炸开成巨物 | 修复后 3 个原版网格共 38 段**逐字节一致** |
| 2 | 数组多写了长度前缀（TpacTool 原版 Bug） | 同上，且数组整体错位 | 同上 |
| 3 | metadata 校验和写 0 | 引擎可能拒绝资产 | 复现出 `xxh64(len‖meta)`，954/954 全中 |
| 4 | 段哈希写 0 | 同上 | 复现出 `xxh64(data)`，14/14 全中 |
| 5 | Mesh `SubVersion` 硬编码为 1（实际 2） | 元数据解析偏移 | 逐字段对比原版 |
| 6 | Texture/Material/Skeleton 的元数据版本硬编码 | 元数据长度不对 | 补全序列化器后逐字节一致 |
| 7 | Material 没有序列化器（原库直接抛异常） | 无法写材质 | 实现了完整序列化器 |
| 8 | LZ4 压缩器把 match 长度扩展写在偏移之前（顺序错） | 压缩数据非法 | 用 `python-lz4` 参考实现交叉验证通过 |
| 9 | 照抄了原版 `uses_cloth_simulation` 却没抄 `ClothMetamesh` | 布料解算炸飞（前两张"巨大"截图） | 对照件补全 ClothMetamesh 后大小正常 |
| 10 | 索引宽度歧义（>65535 个索引时读写器判断依据不同） | 顶点流错位 | 按 <60000 拆分大组为多个子网格 |
| 11 | `bodyPart` 标签填了 `human_body` | 与两个可用参考 mod 唯一的差别字段 | 已改为空字符串（与 <reference mod> / 上次那份一致） |

---
