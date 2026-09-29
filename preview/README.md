# mb-preview —— 骑砍2 皮套装备的「带动画」离线预览器

把**游戏原版真正在播的骨骼动画**套到皮套网格上，不开游戏就能看动起来的效果。

以前离线只能套手写的合成姿势（走过去、屈膝），手的角度、裙摆摆动、肩胯关系全是猜的，
所以"预览图跟游戏内表现对不上"，只能反复进游戏。现在直接套 `inventory_idle` 这类原版动画。

---

## 1. 三个入口

| 入口 | 文件 | 说明 |
|---|---|---|
| GUI（给人） | `mbpreview_gui.py` | 双击 `preview-gui.bat` 启动 |
| CLI（给脚本） | `mb-preview.py` | 一条命令出序列图 + GIF（复用工程 `render.py`） |
| 数据工具 | `mbtool.exe`（`D:\mb-tools`） | 读游戏动画 / 从任意 tpac 导出整套资产 |

GUI 操作 —— **底部就是一条播放器式的按钮条**，不记快捷键也能用：

```
[< char] [yue] [char >] | [|<] [play/pause] [>|] | 各动画按钮 | front 3/4 side back
| tex | reset | shot | rec | open
└ 上面一条是时间轴：点击跳帧、按住拖动
```

| 按钮 | 作用 |
|---|---|
| `上一角色` / `下一角色` | 切换角色（多角色工程里就是几个人） |
| `上一帧` / `播放`·`暂停` / `下一帧` | 逐帧步进与播放控制 |
| 动画名按钮 | 切动画（高亮当前项） |
| `正面` `斜 3/4` `侧面` `背面` | 视角预设 |
| `贴图` | 贴图开关（关掉只看几何） |
| **`骨骼`** | ★ 叠加显示骨架：**橙色线 = 骨链，青色点 = 关节**（等于按 `B`）。骨骼本来在网格内部，所以叠加时**关掉深度测试**，否则几乎全被挡住 |
| `复位` | 复位视角 |
| `截图` | 存一张当前帧 PNG |
| `录制` | 把整段录成 PNG 序列 + GIF（**任意 mod 都能录**） |
| `打开` | 选一个 `.tpac` 打开（等于 Shift+M 选工程目录） |

鼠标落在 UI 上时不会旋转模型；悬停有提示、当前项用绿色标出。
键盘操作**全部保留**，习惯快捷键的照旧：

```
拖拽=旋转   滚轮=缩放   Tab=换角色   1..9=切动画
空格=暂停   ,/.=单帧步进  T=贴图开关   B=骨骼显示   R=复位   S=截图   ESC=退出
M=选一个 .tpac 打开（GUI 内换 mod）   Shift+M=选工程目录
```

## 2. 快速开始

```bash
# ① 双击（自动找工程，优先用"从最终 tpac 读回"的产物）
preview-gui.bat

# ② 打开任意 mod 的资产包 —— 不需要那个 mod 的工程目录
python mbpreview_gui.py --pack <mod>/AssetPackages/pack0.tpac --anim-dir anims

# ③ 打开某个工程
python mbpreview_gui.py --project <工程目录> [--source posed|packed|auto]

# ④ 无头自检 / 出单帧 / 出整段 GIF
python mbpreview_gui.py --project <工程> --selftest
python mbpreview_gui.py --project <工程> --shot out.png --shot-char 1 --shot-anim 1
python mbpreview_gui.py --project <工程> --record outdir --seconds 4 --nframes 48

# ⑤ 命令行出图（复用工程自己的 render.py）
python mb-preview.py --skeleton <工程>/work/bl_skeleton.json \
  --anim anims/inventory_idle.json --posed-dir <工程>/work/posed \
  --work-dir <工程>/work --render-script <工程>/pipeline/render.py \
  --out <工程>/renders/anim_idle --chars yue --views front,q34 --nframes 8
```

## 3. 数据的三个来源

| 来源 | 怎么来 | 特点 |
|---|---|---|
| **最终 `.tpac`**（推荐） | `--pack`，内部走 `mbtool exportmod` → `import_mod.py` | 预览的是**真正交出去的那个文件**；材质→贴图映射精确 |
| 工程中间产物 | `--project --source posed`（`work/posed/*.npz`） | 能看还没打包的状态；材质映射靠解析工程脚本 |
| 手写姿势 | 工程 `pose_test.py` | 老路子，只用来对比 |

**为什么"从 tpac 读回"重要**：离线验证长期只看中间产物 `work/posed/*.npz`，
而打包环节的两个坑（`.mgeo` 同名覆盖、权重没量化成 0..255）只在最终文件里才看得见 ——
"离线全绿、进游戏少一半衣服"就是这么来的。现在有了一条从最终产物倒推的路径。

骨架与动画是**原版游戏数据，与工程无关**，所以和工具放在一起：

```
preview/bl_skeleton.json    官方 human_skeleton.fbx 导出（缺省骨架）
preview/anims/*.json        mbtool anim dump 出来的原版动画
preview/anims/index.json    每个动画对应的 clip 时长（见 §5）
preview/anims/clips.txt     mbtool cliplist 的输出（生成 index 的原料）
```

> 上面这几个文件（骨架表 + 三个动画 + clip 清单）**已随仓库提供**，clone 下来
> 双击 `preview-gui.bat` 就能用；要加别的动画按 §4 的命令自己 dump 一次即可。
> 不进仓库的只有本地跑出来的临时产物（`_verify/`、`record_*/`、截图等）。

界面与验证截图见 [`docs/`](docs/)：`gui_open_btn.png`（按钮条总览）、
`gui_final.png`（骨骼叠加）、`head_zoom.png`（贴图正确性）。

## 4. 补一次动画 / 重建索引

```bash
GAME="/d/SteamLibrary/steamapps/common/Mount & Blade II Bannerlord"
MB=/d/mb-tools/mbtool/bin/Release/net9.0/mbtool.exe

# 找动画名与它对应的 clip
$MB animlist "$GAME/Modules/Native/AssetPackages/animations.tpac" inventory
$MB clip     "$GAME/Modules/Native/AssetPackages/animation_clips.tpac" inventory_cloth_equip

# dump 成一个 JSON 丢进 preview/anims/（GUI 会自动扫这个目录）
$MB anim "$GAME/Modules/Native/AssetPackages/animations.tpac" \
    anim_inventory_idle anims/inventory_idle.json \
    "$GAME/Modules/Native/AssetPackages/skeletons.tpac"

# 重建时长索引（clips.txt + anims/*.json → index.json）
$MB cliplist "$GAME/Modules/Native/AssetPackages/animation_clips.tpac" > anims/clips.txt
python build_anim_index.py --anims anims --clips anims/clips.txt
```

**物品栏/装备页的 4 个动作已经全覆盖**（`action_sets.xml` → `as_human_warrior`）：

| 动作类型 | 动画 | 本目录里的文件 |
|---|---|---|
| `act_inventory_idle_start` | `inventory_idle_start` | `inventory_idle.json`（同一个动画 guid） |
| `act_inventory_idle` | `inventory_idle` | `inventory_idle.json` |
| `act_inventory_cloth_equip` | `inventory_cloth_equip` | `inv_movements.json`（= `anim_inventory_movements`） |
| `act_inventory_glove_equip` | `inventory_glove_equip` | `inv_movements.json`（同上） |

> 早先以为"cloth_equip 还没 dump"，其实 `anim_inventory_movements` 就是它 ——
> 用 `mbtool clip` 看 guid 即可确认（`bb0014b7-…`）。

## 5. 播放速度：时间轴怎么换算成秒

动画 JSON 里的 `t`（0..1267 这种）**没有写在数据里的秒换算**。唯一有据可查的是
`AnimationClip` 自己声明的 `duration`（秒），而它引用的正好是同一个动画 guid：

```
AnimationClip  inventory_idle  dur=15.000  anim=ff08c5be-…  flags=[cyclic]
```

于是 `播放速率 = t_end / dur`（t 单位/秒）。实测三个点：

| 动画 | t_end | clip | dur | 速率 |
|---|---|---|---|---|
| `walk_barmaid` | 40 | `anim_barmaid_walk_forward` | 1.30 s | 30.8 t/s |
| `inv_movements` | 300 | `inventory_cloth_equip` | 5.00 s | 60.0 t/s |
| `inventory_idle` | 1267 | `inventory_idle` | 15.00 s | 84.5 t/s |

⚠️ 这个速率**不是引擎帧率**，只是"把这段动画铺满 clip 时长"的比例。
它保证预览的**节奏**和游戏一致（走路 GIF 不会放成慢动作）。
没有 clip 的动画回退到 `--fps`（默认 24）。

### 5.1 ★★ 播放帧率 = **帧数 ÷ 采样覆盖的秒数**（不是 t/秒）

这里有个把动画播成"飞快 + 抽搐"的经典错误：上面算出来的 `84.5` 是 **t 单位/秒**，
而画面里的"帧"是**采样帧**（48 帧代表 1267 个 t，每帧 ≈ 26 t）。拿 84.5 当帧率用，
屏幕每秒推进 84.5 帧 = 每秒掠过 2230 个 t 单位 ⇒ **15 秒的循环 0.57 秒播完**。

```
正确帧率 = 预计算帧数 ÷ 这段采样实际覆盖的秒数
  整段采 48 帧覆盖 15 秒  -> 3.2 fps（一顿一顿）
  只采前 3.2 秒 48 帧     -> 15 fps  ← 默认走这条
  走路动画 1.3 秒 48 帧   -> 37 fps（本来就流畅，不截断）
```

所以默认有 `--min-fps 15`：帧数铺不满整段时**自动只取前几秒**，保证播得顺；
想看整段就 `--min-fps 0`，想指定区间就用 `--seconds`。HUD 会显示
`15.0 fps（采样前 3.2s）`，一眼能看出当前是按哪段在播。

## 6. 验收用的开关（排查时最省时间）

| 开关 | 用途 |
|---|---|
| `--selftest` | 只加载 + 预计算，不开窗口（自动化用） |
| `--run-seconds N` | 连跑 N 秒后打印帧率/上传耗时/帧号 —— **把"窗口卡死"变成可测量的数字**（`--shot` 只画两帧就退，测不出持续运行的问题）。正常值参考：yue 11.2 万顶点时 ≈58 fps、上传 0.33 ms/次（占 2% 时间） |
| `--shot out.png` | 渲染一帧存图后退出 —— **真正验证 GL 管线**，也能验证任意 mod |
| `--record outdir` | 整段渲染成 PNG 序列 + GIF + 序列图（**不经过工程 render.py**） |
| `--bones` | 启动就叠加显示骨架（等于按 B） |
| `--unlit` | 关光照，直接看**贴图原色** —— 判断"颜色不对"到底是贴图问题还是光照问题 |
| `--only-mats hair,lash` | 只渲染指定材质组（看头发/眼睛这类小件） |
| `--flip-tex` | 上传前翻 V，用来和默认做 A/B（换源模型时确认 UV 约定） |
| `--drop-mats a,b` | 跳过指定材质（工程 `DROP_MATS` 会自动读） |

`render.py` 侧也有对应的：`--plain`（不加载贴图）、`--noflip`（A/B 测 V 轴）。

## 7. 本次实测的结论

对 `mb-xianjian7` 的 `build/pack0.tpac`（61 个资产）做了从最终产物倒推的验证：

| 检查 | 结果 |
|---|---|
| 几何 | 6 metamesh / 52 子网格 / 182500 顶点 / 246837 三角（lod0） |
| **权重** | 每顶点 4 个 u8 之和 == 255 的占比 **100.00%**，非零占比 100% |
| 骨骼索引 | max 26（≤27 ✓） |
| **与工程中间产物对比** | 逐材质面数**完全一致**（body 9406 / cloth1 13088 / hair 47398 …），差值 4821 面恰好 = 工程 `DROP_MATS` 有意剔除的 4 类隐藏片 |
| 贴图 | 33 张全部解出；与打包前的 `build/tex_png` **逐像素平均差 0.81/255**（BC1 有损，属正常） |
| 两条渲染路径 | `--pack`（tpac 读回）与 `--project`（中间产物）出图一致 |

> 结论：这个包的**打包链路是忠实的** —— skill 里那两个"离线全绿、进游戏出问题"的坑
> （权重截断、`.mgeo` 同名覆盖）在本工程**不存在**。

## 8. 已知局限

1. **骨架必须是 BL 骨架**：只对"已重定向到 BL 27 骨"的皮套 mod 有效。
   原版资产或别的骨架的 mod 能导入几何，但套动画会炸（`--pack` 会打印骨骼索引上限，
   >27 就说明不是 BL 骨架）。
2. **材质模板层面判断不了**：渲染是简化材质（固定管线 + 贴图），透明管线 /
   shader 标志 / systemFlags 这些仍需进游戏。
3. **`mb-preview.py`（CLI）复用工程 `render.py`，因此只认该工程的材质命名** ——
   从任意 tpac 导入的网格会被 `render.py` 全部过滤掉（`过滤后没有任何材质组可渲染`）。
   要看任意 mod 的序列图/GIF，用 GUI 的 `--record`。
4. 一次渲染一个 mod；GUI 里可以 Tab 换角色，但两个 mod 之间要重开（或按 M 再选）。
5. 光照是固定管线单主光 + 补光，比不上工程 Blender 渲染的观感；
   **判断颜色请用 `--unlit`**（贴图原色）。

## 9. 踩过的坑（都是本次修掉的）

| 现象 | 根因 |
|---|---|
| **整个模型贴图紊乱、五官上下错位** | GUI 按"OpenGL v=0 在底行"把贴图**上下翻转**上传了。本源 UV 是 **top-origin（v=0 = 贴图顶行）**，`glTexImage2D` 第一行数据落在 t=0 ⇒ **必须原样上传**。判据：`--unlit` 一看就分晓 |
| **头发是白灰色**（贴图明明是深棕） | ① 光照没配平：ambient 0.55 + diffuse 0.95 = 迎光面放大 1.5 倍，把 [74,60,49] 抬成 [111,90,74]。改成 **ambient+diffuse ≈ 1.0** 还原贴图原色。② 镂空贴图 alpha 中位是 0，透明区 RGB 是白的，一开 mipmap 平均进来 ⇒ 顺手做了 `flatten_transparent`（把透明区填成发丝中位色） |
| **头发/发饰上全是噪点** | 只上传 mip0（2048² 缩到 800px 窗口严重走样）⇒ 生成 mip 链 + 三线性过滤 |
| **十几个组共用同一张贴图** | `import_mod` 写 `texmap.json` 时用的键空间是**材质名**，预览器按**组名**查 ⇒ 全部落空后静默退到关键词表的第一个词（`cloth1`）。**键必须是子网格组名** |
| 工程路径下贴图仍然对不上 | 源材质名（`MI_MAJ02_01_hair`）→ 贴图（`yue_hair_d`）的映射只存在于工程脚本里。`project_map.py` 用 `ast` 解析 `render.py` 的 `MAT_TABLE`（**表是嵌套的**，按角色分组，不能只取"最大的那个字典"），解析结果缓存到 `work/texmap_project.json` |
| **"从哪个视角看就看不到哪个方向的头发"**（白茉晴没刘海、俯视没头顶，月清疏正常） | `two_sided` 材质只做了"不剔除"，**漏了双面光照**。GL 默认 `GL_LIGHT_MODEL_TWO_SIDE=FALSE` ⇒ 背面拿正面法线算光照，恒为背光；深棕发丝 `[74,60,49]` 乘上只剩环境光变成 `[30,24,20]`，而背景正是 `[26,28,33]` ⇒ **发片融进背景，看着就是"消失"**。修：`glLightModeli(GL_LIGHT_MODEL_TWO_SIDE, 1)`。判据用 `--unlit` 对照（无光照时刘海像素 6058、有光照只剩 1425，修后恢复到 4157）。★ 这类"忽隐忽现"还会加重动画的"抽"感 |
| **骨骼在一个角色上能显示、换个人一根线都没有** | 骨骼是**材质组渲染之后**追加画的，继承了最后一个材质组的状态 —— 发丝材质开着 `alphaTest=0.2745`，骨骼线被当低 alpha 像素整条剪掉。而 `groups` 顺序来自 `np.unique(face_group)`，**每个角色不一样** ⇒ 表现成"跟角色绑定的怪 bug"。修法：追加绘制前显式清 `ALPHA_TEST/TEXTURE_2D/BLEND/LIGHTING/CULL_FACE`，收尾复位。验证用 **开/关骨骼的 A/B 差异像素**（`selftest_bones.py`），别数颜色 —— 按"橙色像素"统计会把粉色腰带算进去，实测得出过相反结论 |
| 走光保护片挡在身体前面 | 中间产物带着 `M_ProxyHide` 等 4 类被工程丢弃的材质，预览器应同样跳过（自动读 `DROP_MATS`） |
| `render.py` 拒绝渲染导入的网格 | `faces` 必须是 `(M,3)` 二维，`import_mod` 写成了展平一维 |
| 自检打印出"位移 67 米" | `np.linalg.norm(X)` 漏了 `axis=2`，返回的是**整个数组的标量范数**。函数没写错、单测也过，但打印出来像模型炸了 |
| `preview-gui.bat` 报 `drag was unexpected` | cmd.exe 对**深层嵌套的 `( )` 块**（且块内含带引号的 `set`）解析错乱。改成扁平 `if/goto` 结构 |
| **待机动作"抽"、幅度比游戏里大** | 两个独立原因：① **播放帧率不足导致混叠** —— 动画含高频成分（脚/小腿微动），15fps 采样时逐帧最大位移 38mm、30fps 23mm、**60fps 只 9.5mm**；所以默认帧率是 60（`--min-fps`），帧数默认 96。② 一度怀疑是"q 是世界朝向还是局部朝向"，实测**并排渲染**后发现复合 q 会让骨盆歪斜/脚踝翻转（更差），**保持世界朝向**。⚠️ 顺带证伪了一条判据："站立待机时脚不动"会被"姿势整体缩起来"满足 —— 物理判据能证伪、不能单独证真，最终要并排渲染对着看 |
| **动画快得离谱、像在抽搐** | `tick` 里拿 `meta["fps"]`（= t_end / clip 时长，单位是 **t 单位/秒**，实测 84.5）当**帧率**用了。采样帧每帧代表 ≈26 个 t，于是每秒掠过 2230 个 t 单位 ⇒ 15 秒的循环 0.57 秒播完。正确帧率 = **帧数 ÷ 采样覆盖秒数**（`play_fps()`）。同理 `--record` 的 GIF 帧延时也要按"覆盖秒数"算 |
| **GUI 开得出来、看得见人物，但人物一动不动，随后 Windows 提示"无响应"** | 两个叠在一起的错：① `self.last`（帧推进累积器）被初始化成 `time.time()` = Unix 时间戳 ≈1.7e9，而 `tick` 里是 `while self.last >= step: self.last -= step`（step ≈ 1/84 s）⇒ **第一次 tick 就进入要迭代 1.4e11 次的死循环**，事件循环再也回不来；② `pyglet 1.5.31` 的 `Win32Window` **没有 `invalidate()` 方法**（只有 `invalid` 属性），请求重绘写成 `invalidate()` 会每帧抛 AttributeError。修法：累积器从 `0.0` 起，重绘写 `win.invalid = True`。**判据：`--run-seconds 8` 必须打印出 draw 次数与帧号在动**（改之前它每次都跑到被超时杀掉） |
| 在 `%TEMP%` 下跑的 Python 脚本莫名报 `No module named 'bpy'` | `%TEMP%` 里堆着历史 Blender 脚本，其中 `inspect.py` **撞了标准库名**，脚本放在该目录运行时 `sys.path[0]` 会遮蔽标准库。临时脚本别放 `%TEMP%` |

## 9.5 已知问题（已定位、未修完）

两轮独立代码审查的完整报告与可复跑探针在：

- `_review/REVIEW.md` —— GUI / pyglet 兼容性（贴图显存、事件回调阻塞、hover 重建开销、`draw_bones` 下标空间等）
- `_review2/`（`repro.py` 一条命令跑完 9 组复现）—— `exportmod` → `import_mod` 数据链路

已经修掉的（本轮）：官方 kit 包的 `SecondMaterial` 材质关联、角色分组的"尾段"兜底、
同名贴图互相覆盖、全零权重顶点、权重判据的误报文案、`project_map` 缓存不失效、
贴图按路径去重 + 换源释放、`lbs` 去掉重复求逆、`__dir__` 相对路径。

**仍未修**（按影响排序）：

| 问题 | 影响 |
|---|---|
| 预计算/贴图加载仍在**主线程**同步跑（切角色/动画 1.2~2.2 s，GUI 内录制 20 s 全程占住） | 窗口短暂无响应。目前只加了提示文字；彻底解决要改成分帧预算或后台线程 |
| `BC7` / `DXT2·3·4` 等格式不解码 | 用到它们的材质退回"猜贴图"。`DXT4` 应并入 `DXT5` 分支（写错了），`DXT2/3` 需实现或显式报不支持 |
| `project_map` 的扁平表只取"条目最多的内层字典" | 两个角色共用同名材质时会拿错图 |
| `exportmod` 的 `BoneWeights` / `Uv1` 没有长度校验 | 数组长度与顶点数不一致时后续字段整体错位（扫过 200+ 真实包都没触发，属防御性） |
| 同一包内不同 metamesh 可能取到不同 lod | 清单只报一个 `lodUsed`；`import_mod` 合并时不检查 |
| BC5 解出的 PNG 把 B 通道填 0 | 预览器只用槽 0/1 所以没爆，但导出的法线贴图是错的（应为 `sqrt(1-x²-y²)`） |

## 10. 文件清单

**工具（本目录）**

| 文件 | 作用 |
|---|---|
| `mbpreview_gui.py` | ★ GUI：实时播放，多角色/选 mod/截图/录制/验收开关 |
| `mbui.py` | GUI 的按钮条 + 时间轴（自绘，固定管线友好，见文件头的"为什么不用 pyglet.gui/shapes"） |
| `mb-preview.py` | ★ CLI：一条命令出序列图 + GIF（复用工程 render.py） |
| `anim_pose.py` | ★ 核心：套游戏动画 → 逐帧 npz（LBS） |
| `import_mod.py` | `exportmod` 的产物 → 预览器格式的 npz + PNG + texmap.json |
| `project_map.py` | 从工程脚本解析「源材质名 → 贴图」和丢弃材质清单 |
| `build_anim_index.py` | 生成 `anims/index.json`（clip 时长 → 播放速率） |
| `preview-gui.bat` | 双击启动（纯 ASCII，避开 bat 编码坑） |
| `selftest_anim.py` | 验证动画解包质量：四元数归一化 / 相邻关键帧跳变 / 采样帧间位移（"抽搐"就是靠它定位到 `t=0` 是 rest 帧的） |
| `selftest_gl_refresh.py` | 验证 pyglet 1.5 的刷新机制（`invalid=True` vs 手动 flip vs 不请求，三种写法实测对照） |
| `selftest_ui.py` / `selftest_buttons.py` | 无头点一遍按钮回调与命中测试（新写的交互路径无法交互测试，靠它们把关） |
| `selftest_bones.py` | 逐角色验证"骨骼叠加"真的画出来了（A/B 差异像素判据，见 §9 那一行） |
| `probe_anim_space.py` / `solve_anim_*.py` | 当初解"动画四元数约定"的探针（留档） |
| `diag_lbs.py` / `diag_anim_bones.py` | 按骨/按材质组定位"是哪根骨炸了" |
| `sketch_anim_frames.py` / `sketch_anim_hypotheses.py` | 骨架逐帧图 / 约定假设对比图 |

**mbtool 侧（`D:\mb-tools`）**

```
mbtool/src/Anim.cs        读游戏动画（animlist / cliplist / clip / anim / skeljson）
mbtool/src/ExportMod.cs   exportmod：从任意 .tpac 导出几何 + 材质 + 贴图原始数据
```

导出格式（`exportmod` 的输出，`import_mod.py` 消费）：

```
<out>/pack.json     清单：meshes / materials / textures
<out>/geo/*.bin     每个 metamesh 一个自描述二进制（顶点/法线/UV/色/骨索引/骨权重/索引）
<out>/tex/*.bin     贴图原始 BC 字节（含 mip 表）
```