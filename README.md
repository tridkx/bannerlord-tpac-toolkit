# mb-tools —— 《骑马与砍杀2：霸主》资产包（`.tpac`）逆向工具集

一套用来**读写、检查、生成** Bannerlord `.tpac` 资产包的工具，以及配套的格式说明。
包含一个 C# 命令行工具、若干 Python 逆向/诊断脚本、一个**带动画的离线预览器**，和几个 Windows 辅助脚本。

> 面向的场景：想用代码（而不是 Modding Kit 的 GUI 导入流程）离线、可重复地生成模型/贴图/材质资产包，
> 或者想检查官方编辑器产出的包到底写了什么。

---

## 目录

```
mbtool/          C# 命令行工具：读取 / 检查 / 构建 / 往返验证 .tpac
  src/Program.cs   CLI 入口（info / mesh / mat / tex / skel / metacheck / segcheck / ...）
  src/Builder.cs   资产包构建器（从 JSON 描述生成 pack0.tpac）
  src/Anim.cs      读游戏原版骨骼动画（animlist / cliplist / clip / anim / skeljson）
  src/ExportMod.cs 从任意 .tpac 导出整套资产（几何 + 材质 + 贴图原始数据）
  src/XxHash64.cs  xxh64 实现（含 metadata 校验和封装）
  src/LZ4Block.cs  LZ4 块编解码（不依赖第三方库）
  src/HalfCheck.cs half-float 自检
preview/         ★ 离线动画预览器（把游戏原版动画套到皮套网格上，不开游戏就能看动起来）
  mbpreview_gui.py    GUI：实时播放 + 按钮条/时间轴，可打开任意 .tpac
  mb-preview.py       CLI：一条命令出序列图 + GIF
  anim_pose.py        核心：套游戏动画 → 逐帧 npz（LBS）
  import_mod.py       把 exportmod 的产物组装成预览器格式（npz + PNG + texmap）
  project_map.py      从工程脚本解析「源材质名 → 贴图」与丢弃材质清单
  build_anim_index.py 用 AnimationClip.duration 算出动画的真实播放速率
  anims/              原版动画 JSON + 时长索引（与工程无关，跟着工具走）
  README.md           ★ 用法 / 验收结论 / 踩坑清单（要看预览器就从这个文件进）
py/              Python 工具（独立实现，用于交叉验证 C# 结果）
  tpac.py              独立的 .tpac 读取器（可当库用）
  walk_mesh.py         逐字段解析网格元数据
  walk_texture.py      逐字段解析贴图元数据
  checksum_hunt.py     校验和算法搜寻
  hash_brute.py        xxh64 参数空间暴力搜索
  lz4_debug.py         LZ4 块级调试
  tpac_hdr.py          文件头速查
  strdump.py           二进制字符串提取
  qtangent_derive.py   Q-Tangent 四元数约定验证
  bcencode.py          BC1/BC3/BC4/BC5 编解码器
  bcencode_selftest.py 编解码器自测（PSNR 断言）
  dump_skeleton.py     Blender 脚本：从 FBX 导出引擎骨骼表
setup/
  patch_tpactool.py    给上游 TpacTool.Lib 打补丁（必须，见下）
win/
  ui.ps1               截图 / 点击游戏窗口（不抢焦点，可用于自动化验证）
  shot.ps1             简单截图
docs/
  tpac-format.md       .tpac 格式规范（逆向结果，含校验和公式与字段布局）
```

---

## 依赖

- **.NET SDK 9 或 10**
- **Python 3.10+**，`pip install numpy pillow lz4 xxhash`
- **Blender 4.x / 5.x**（仅 `py/dump_skeleton.py` 需要，可无头运行）
- [TpacTool](https://github.com/szszss/TpacTool)（MIT）的 `TpacTool.Lib` 源码 —— `mbtool` 建立在它之上

---

## 准备 `mbtool`

上游 `TpacTool.Lib` **只有读取器**，且写盘逻辑有若干缺陷（会导致产出的包在游戏里显示错乱）。
必须先打补丁：

```bash
# 1) 下载上游源码（放在与本目录同级的 TpacTool-master/，或改 mbtool.csproj 里的路径）
curl -L -o TpacTool.zip https://codeload.github.com/szszss/TpacTool/zip/refs/heads/master
python -c "import zipfile;zipfile.ZipFile('TpacTool.zip').extractall('.')"

# 2) 打补丁（幂等，重复执行安全）
python setup/patch_tpactool.py ./TpacTool-master

# 3) 编译
cd mbtool && dotnet build -c Release
# 产物：mbtool/bin/Release/net9.0/mbtool.exe
```

`mbtool.csproj` 默认引用 `../TpacTool-master/TpacTool.Lib/**/*.cs`，按需修改。

补丁清单（脚本会逐条应用并打印结果）：

| # | 修补内容 | 影响 |
|---|---|---|
| 1 | 资产 metadata 保留原始字节并写入正确的 **xxh64 校验和** | 校验和写 0 会被引擎拒绝 |
| 2 | 段数据写盘时计算 **xxh64 数据哈希** | 同上 |
| 3 | **顶点流尺寸表的偏移基准**（首个数组偏移必须是表自身大小，不是 0） | 写错会让引擎把每个数组错读 224 字节，模型扭曲/炸开 |
| 4 | 数组写入**不要带长度前缀** | 多写前缀会让后续所有数组错位 |
| 5 | 补全 `Material` / `Texture` / `Mesh` / `Metamesh` / `Skeleton` 的元数据版本号与序列化器 | 版本硬编码会导致元数据长度不符 |
| 6 | 让 `Metamesh` / `Mesh` 的集合可写，暴露段加载器字段 | 便于按需构造资产 |

> 判断补丁是否生效：拿任意原版包跑 `mbtool segcheck`，所有数据段都应是 `identical`。

---

## `mbtool` 用法

```
mbtool <命令> [参数...]
```

### 查看

```bash
mbtool info   <pack.tpac>                  # 资产数量与类型分布
mbtool list   <pack.tpac>                  # 列出全部资产（类型 GUID / 名称 / GUID）
mbtool mesh   <pack.tpac> <网格名>          # 子网格结构、包围盒、骨骼使用、标志
mbtool mat    <pack.tpac> <材质名>          # shader、混合模式、标志、贴图槽位
mbtool tex    <pack.tpac> <贴图名>          # 尺寸、mip 数、格式、标志
mbtool skel   <pack.tpac> [骨骼名]          # 骨骼层级与静置矩阵
```

### 检索

```bash
mbtool find      <目录> <名字片段>          # 在目录下所有包里按名字找
mbtool findguid  <目录> <guid...>          # 按 GUID 找（解析跨包依赖用）
mbtool guidindex <目录> [输出.tsv]          # 建立 名称/GUID → 包 的索引表
```

### 校验（改包前后都该跑）

```bash
mbtool metacheck <pack.tpac>
#   每个资产的 metadata 重新序列化后与原始字节比对 + 校验和比对
#   期望：checksum ok=N bad=0 | metadata identical=N differ=0

mbtool segcheck  <pack.tpac> <资产名>
#   ★ 最有用的检查：把每个数据段用写入器重新序列化，与文件里的原始字节逐段比对
#   期望：全部 identical。出现 "first diff at byte N" 就说明写入器有偏差

mbtool roundtrip <pack.tpac> <out.tpac>
#   整包读入再写出，用于验证读写器对称性（拷贝路径下应与原文件字节一致）

mbtool mataudit  <pack.tpac>
#   审计材质引用的贴图槽位是否齐全、是否有悬空 GUID
```

### 读游戏原版动画 / 从任意 tpac 导出整套资产

```bash
MB=mbtool/bin/Release/net9.0/mbtool.exe
GAME="<游戏>/Modules/Native/AssetPackages"

# 4052 个骨骼动画 / 6170 个动画剪辑
$MB animlist "$GAME/animations.tpac" idle          # 按名字找动画（附带 dur）
$MB cliplist "$GAME/animation_clips.tpac" idle     # 列出剪辑（dur/flags/priority + 它引用的动画 guid）
$MB clip     "$GAME/animation_clips.tpac" inventory_cloth_equip

# dump 成 JSON（给离线预览器用；GUI 会自动扫 preview/anims/ 目录）
$MB anim     "$GAME/animations.tpac" anim_inventory_idle preview/anims/inventory_idle.json \
             "$GAME/skeletons.tpac"
$MB skeljson "$GAME/skeletons.tpac" human_skeleton preview/bl_skeleton.json

# 从**任意 .tpac** 导出网格 + 材质 + 贴图原始数据（自包含目录）
$MB exportmod <mod>/AssetPackages/pack0.tpac out/exportmod
# 几何是自描述的二进制（顶点/法线/UV/顶点色/骨骼索引/骨骼权重/索引），
# 贴图是原始 BC 字节 + mip 表；组装与解码见 preview/import_mod.py
```

> `exportmod` 的用途不只是"方便"：预览器原先只能吃工程中间产物 `work/posed/*.npz`，
> 于是**离线验证的不是最终交付的那个文件**。这条命令让预览器改成从最终 `.tpac` 倒推
> （打包环节的权重量化、`.mgeo` 同名覆盖这类问题只有这样才看得见）。

### 构建资产包

```bash
mbtool build <spec.json>
```

`spec.json` 描述要生成的包。**所有资产都从已有包里的模板资产克隆**（模板提供 shader、布局等难以凭空构造的字段），
只替换数据、名称与 GUID：

```jsonc
{
  "output": "build/pack0.tpac",
  "packageGuid": "00000000-0000-0000-0000-000000000000",   // 省略则自动生成
  "templates": {                       // 名字 -> 模板资产来源
    "mesh":  { "tpac": "<游戏>/Modules/Native/.../armor555.tpac", "name": "empire_legion_a" },
    "matOpaque": { "tpac": "<游戏>/Modules/Native/AssetPackages/materials.tpac", "name": "plain_white_skinned" }
  },
  "textures": [
    { "name": "my_albedo", "template": "texBC1", "blob": "build/tex/my_albedo.bc",
      "width": 1024, "height": 1024, "mips": 11, "format": "DXT1" }
  ],
  "materials": [
    { "name": "my_mat", "template": "matOpaque",
      "textures": { "0": "my_albedo", "1": null, "2": "my_normal" },
      "blendMode": "no_alpha_blend", "vertexLayoutFlags": ["bumpmap", "skinning"] }
  ],
  "meshes": [
    { "name": "my_mesh", "bodyPart": "", "template": "mesh",
      "groups": [ { "geometry": "build/my_part.mgeo", "material": "my_mat", "name": "my_mesh.0" } ] },
    // 或者把已有网格原样克隆、只换名字（做 A/B 对照时很有用）：
    { "name": "control_mesh", "template": "mesh", "cloneFrom": "mesh" }
  ]
}
```

`.mgeo` 是简单的中间格式（小端）：

```
i32 magic('MGEO'=0x4F45474D), i32 顶点数 n, i32 索引数 m
n×3 f32 位置 | n×3 f32 法线 | n×4 f32 切线(xyzw)
n×2 f32 UV | n×2 f32 UV2 | n×4 u8 颜色
n×4 u8  骨骼索引 | n×4 u8 骨骼权重 | m×u32 索引
```

构建时若某子网格顶点数或索引数 ≥ 60000，会自动拆成多个子网格
（引擎的索引位宽判定与上游读取器的判定条件不同，两边都要 < 65535 才安全）。

> 管线里的坑（2026-09-11，把 RE:Resistance 的角色移植成骑砍2装备 mod 时实测；完整工程见
> `D:\dsh-mb-mod`，方法论已整理成 DSH skill `bannerlord-character-mod`）：
>
> 1. **★ 带 alpha 的贴图必须声明 `systemFlags=["has_alpha"]`**（最容易漏、最难查的一条）。
>    引擎判断"这张贴图有没有 alpha 通道"看的是**资产标志**，不是文件里有没有 alpha 像素。
>    没声明时所有贴图被当不透明：材质侧 `blendMode` / `alphaTest` / alpha 数值**怎么调都不生效**
>    （实测表现：深色镜片贴图→黑片、亮色→白片，颜色跟着贴图走）。
>    对照原版 `battania_dress_c_d`、参考 mod 的 `body_D` 都是 `[has_alpha]`；用 `mbtool tex` 一看便知。
> 2. **透明要"管线 + 通道"两件事一起对**：`blendMode=modulate`（modulator，透明管线，原版
>    真半透服饰用 `modulate`+`alphaTest=0.2745`+`alpha_test`）**且**贴图有 alpha。
>    另注意 `no_alpha_blend` = 强制不透明。
> 3. **UV 的 V 轴**：源模型若是 D3D 习惯（v=0 在贴图顶部），而 `.bc` 按 PNG 原始行序写盘，
>    引擎采样会整体上下读反 → 颜色错位、法线错位（凭空多褶皱）。写网格时把 UV 存成 `(u, 1−v)`，
>    且要在**算切线之前**翻，否则切线手性跟着错。
> 4. **自己生成的贴图不要留大片纯黑**：1024² 里只画两个小岛、其余全黑的话，
>    小尺寸/远处时引擎采样高 mip 会把内容与黑背景平均掉（实测"眼睛纯黑"就是这个原因）。
>    背景应填成该内容自身的平均色。
> 5. **`.bc` 必须带完整 mip 链**：只写顶层，打包器报 `blob too small for mip 1`。
> 6. **Bone heat 蒙皮**在流形不良的游戏网格上可能整体失败（权重全 0，只报
>    "failed to find solution"），别指望它，要自己算或用源模型原始权重。
>
> 移植时另一个高价值做法：**要判断某个渲染效果怎么做，先 dump 一个"已知能正常工作"的同类产物
> 做参数差集**（`mbtool matall` 就是为此加的）—— 参数空间靠推理试错会空转很久。
>
> 7. **★★ 资产 GUID 必须每个包都不同**（2026-09-13 修复）。原实现里
>    `public Random Rng = new Random(20260910);` 是**固定种子**，每个新资产的 GUID 都从它取，
>    于是**同一工具构建的每个 mod 都拿到完全相同的 GUID 序列**（连消耗顺序都一样：贴图→材质→网格）。
>    实测两个不同工程的包有 **31 个 GUID 全部撞车**；引擎按 GUID 索引资产，两个 mod 同时加载
>    就互相覆盖 —— 症状是"**只装一个正常、两个一起装就贴图紊乱**"，非常难查。
>    现在改为**先定包 GUID，再由它派生 RNG 种子**（`ctx.SeedRng(pkgGuid)`）：
>    同一个 spec 仍然可复现，不同包之间必然不同。
>    自查命令：把两个包的 `mbtool list` 输出第三列求交集，必须是 0。

---

## Python 工具用法

这些脚本是为**交叉验证** C# 实现而写的：用完全独立的代码路径解析同一个文件，两边一致才敢下结论。
多数脚本既是可执行程序也可当模块导入。

```bash
cd py

# 列出包内资产（独立读取器，可当库：from tpac import read_tpac）
python tpac.py <pack.tpac>

# 逐字段 dump 网格元数据（每一步都打印偏移量，用于和原版逐字段对比）
python walk_mesh.py <pack.tpac> <网格名>

# 逐字段 dump 贴图元数据
python walk_texture.py <pack.tpac> <贴图名>

# 文件头速查 / 二进制字符串
python tpac_hdr.py <pack.tpac>
python strdump.py <文件> [最小长度]

# LZ4 块级调试（解码/编码、与参考实现对比）
python lz4_debug.py <pack.tpac> <资产名>

# 校验和算法搜寻：在同一个包里找出"哪个字段是哪种哈希"
python checksum_hunt.py <pack.tpac>

# xxh64 参数暴力搜索（种子/长度前缀/字节序组合）
python hash_brute.py <pack.tpac>

# Q-Tangent 四元数约定验证（用原版网格逐顶点验证公式）
python qtangent_derive.py <pack.tpac> <网格名>

# BC 编解码器自测（断言 PSNR 下限；默认用内置生成的测试图）
python bcencode_selftest.py
#   也可指定真实贴图：TEST_ALBEDO_PNG=... TEST_NORMAL_PNG=... python bcencode_selftest.py
```

作为库使用：

```python
from bcencode import encode_bc1, encode_bc5, decode_bc5   # numpy (H,W,3/2) uint8
from tpac import read_tpac
t = read_tpac("pack0.tpac", read_meta=True)
for a in t["assets"]:
    print(a["type_guid"], a["name"], a["meta_size"], len(a["segs"]))
```

### 骨骼表导出（Blender 无头）

```bash
blender --background --factory-startup --python py/dump_skeleton.py -- <human_skeleton.fbx> <out.json>
```

从骨架 FBX 里导出每根骨骼的 head/tail（引擎网格空间）。
注意：**Blender 导入 FBX 时对 bone tail 是猜测的，不可直接使用**；脚本会额外按"子骨骼位置"重建骨轴。

---

## Windows 辅助脚本

`win/ui.ps1` 用于在**不抢焦点**的前提下截取游戏窗口，以及发送真实点击（自动化验证游戏内效果）：

```powershell
# 仅截图（用 PrintWindow，窗口被遮挡也能抓到，不会打扰用户）
.\win\ui.ps1 -out shot.png

# 截图 + 在 (x,y) 真实点击（会切到前台；已处理 Windows 前台锁）
.\win\ui.ps1 -x 261 -y 533 -out after.png -wait 3000 -foreground 1

# 抓其它进程的窗口
$env:CAP_PROC = "blender"; .\win\ui.ps1 -out blender.png
```

> 说明：合成点击必须配合 `SetForegroundWindow`（脚本内部会先发一次 ALT 解除前台锁）；
> 只发 `PostMessage` 的点击会被游戏忽略。

---

## 参考资料

- **[LVBU and DIAOCHAN](https://steamcommunity.com/sharedfiles/filedetails/?id=2863411168)** ——
  一个用官方 Modding Kit 做出来的、能正常使用的角色装备 mod。
  它的 `Modules/LVBU and DIAOCHAN/AssetPackages/pack0.tpac` 是**非常好的对照样本**：
  拿 `mbtool segcheck` 跑它、再用 `mbtool mesh` / `mbtool mat` 看它的字段，
  就能知道"编辑器到底写了什么"，比自己猜快得多。本工具集里的很多结论都是这样对照出来的。
- **[TpacTool](https://github.com/szszss/TpacTool)**（MIT, © szszss）—— 最早公开的 `.tpac` 解析器，
  `mbtool` 的读取层建立在它之上（写盘部分需要 `setup/patch_tpactool.py` 打补丁）。
- **[Bannerlord API 文档](https://apidoc.bannerlord.com/)** —— 查 `ItemObject` / `ArmorComponent`
  这类类的真实属性（例如 `covers_*` 在 XML 里是属性、在代码里是 `MeshesMask` 位掩码）。
- **[Bannerlord Modding CN](https://yigu-studio.gitbook.io/bannerlord-modding-cn)** —— 中文 XML 文档，
  查物品/防具各字段含义很方便。
- 游戏自带资源里值得对照的包：
  `Modules/Native/AssetPackages/materials.tpac`（全套材质模板）、
  `Modules/Native/EmAssetPackages/*.tpac`（角色装备）、
  `Modules/Native/AssetPackages/meshes_shared_*.tpac`（共享网格）。

## 格式说明

见 **[docs/tpac-format.md](docs/tpac-format.md)**：文件结构、两级 xxh64 校验和公式、
顶点流的尺寸表布局、Q-Tangent 四元数约定、骨骼索引含义、贴图格式与 mip 布局等。

---

## 许可与声明

- 本仓库只包含工具与格式文档，**不包含任何游戏素材**。
- `setup/patch_tpactool.py` 用于给 [TpacTool](https://github.com/szszss/TpacTool)（MIT，© szszss）打补丁，
  请自行获取上游源码；本仓库不重复分发其代码。
- 工具仅用于个人学习与模组制作，请遵守相关游戏的使用条款。
