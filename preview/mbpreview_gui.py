# -*- coding: utf-8 -*-
"""mb-preview GUI —— 带动画的皮套离线预览器（人用）。

它和命令行版（mb-preview.py）共用同一套「骨架 + 游戏动画 + 网格」，
区别是这里**实时播放**：鼠标旋转、滚轮缩放、空格暂停、数字键切动画、Tab 换角色。

三种打开方式
------------
1. 工程目录（最省事）::

       python mbpreview_gui.py --project <工程目录>          # 用 <工程>/work/posed/*.npz

2. **任意 .tpac**（不依赖任何工程目录 —— 会自动调 mbtool exportmod + import_mod）::

       python mbpreview_gui.py --pack <mod>/AssetPackages/pack0.tpac

   这条路径的价值不只是"方便"：它预览的是**最终交付的那个文件**，
   而不是 work/posed 那个中间产物 —— 打包环节出的问题（权重量化、
   .mgeo 同名覆盖）只有这样才看得见。

3. 细粒度（脚本/CI 用）::

       python mbpreview_gui.py --posed-dir ... --skeleton ... --anim-dir ...

无头自检（不需要人看窗口，用于自动化验收）
------------------------------------------
    --selftest         只加载数据 + 预计算，不开窗口
    --shot out.png     开窗渲染一帧、存图、退出  ← 真正验证 GL 管线

操作
----
    拖拽=旋转   滚轮=缩放   Tab=换角色   1..9=切动画
    空格=暂停   ,/.=单帧步进  T=贴图开关   R=复位   S=截图   ESC=退出
    M=选一个 .tpac 打开（GUI 内换 mod）   Shift+M=选工程目录
"""
import argparse
import ctypes
import glob as _glob
import json
import os
import subprocess
import sys
import time
from pathlib import Path

# ★ 双击 .bat 启动时控制台是中文 GBK(936)，而本脚本要 print 中文
#   ⇒ 不钉死编码会直接 UnicodeEncodeError 崩掉（命令行里设 PYTHONUTF8=1 时看不出来）。
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import anim_pose as AP                          # noqa: E402
from sketch_anim_frames import load_skeleton    # noqa: E402

# 动画名 -> 中文按钮名（没命中的回退成截断的原文）
ANIM_CN = {
    "inventory_idle": "物品栏待机", "inventory_idle_start": "进物品栏",
    "inventory_cloth_equip": "换衣", "inventory_glove_equip": "换手套",
    "inv_movements": "换装动作", "inventory_movements": "换装动作",
    "walk_barmaid": "走路", "barmaid_walk_forward": "走路",
    "walk": "走路", "walk_forward": "走路", "run": "跑步",
    "stand_idle": "站立待机", "idle": "待机",
}


def anim_label(name):
    if name in ANIM_CN:
        return ANIM_CN[name]
    low = name.lower()
    for k, v in ANIM_CN.items():
        if k in low:
            return v
    return name.replace("anim_", "").replace("_", " ")[:10]


# 材质名关键词 -> 贴图后缀名。只在**没有 texmap.json** 时兜底用
# （从 tpac 导入的工程有精确映射，那才是首选）。
TEX_KEYWORDS = ["cloth1", "cloth2", "cloth3", "macrame", "tassel", "mouth",
                "brow", "lash", "hair", "head", "body", "eye", "flower"]

DEFAULT_SKELETON = HERE / "bl_skeleton.json"

HAIR_ALPHA_TEST = 0.2745   # 骑砍发丝 alphaTest 阈值（与 render.py 保持一致）
ALPHA_TEST_OVERRIDE = None  # --alpha-test 命令行覆盖（None = 用材质自带值）


# ==========================================================================
#  数据层
# ==========================================================================
def anim_start_offset(anim, order, thresh_deg=20.0):
    """动画的第 0 帧是不是"骨骼 rest 朝向"？是就返回 1（采样时跳过它）。

    ★ 为什么必须跳过：游戏动画的 `t=0` 存的是**所有动画共有的骨骼 rest 朝向**
      （pelvis 恒为 ~90° 绕 -Y），不是动画内容。此时 Δ=I，LBS 退化成绑定姿势；
      而 t=1 才是动画真正的第一帧。实测相邻帧跳变：
        inventory_idle 的 l_finger0 在 t=0→1 转了 **162°**
        walk_barmaid   的 l_hand    在 t=0→1 转了 **91°**
      前三名**全落在 t=0**，而 t>0 的部分是平滑的。
      采样里带上这一帧的直接后果：**每循环一次就抽一下**（帧间顶点位移
      204~414mm，而正常帧只有 1~10mm）。

    判据是数据驱动的（换动画/换骨架也成立），不写死"跳过第 0 帧"。
    """
    mx = 0.0
    ba = anim.get("boneAnims") or []
    for i in order:
        rot = ba[i]["rot"] if i < len(ba) else []
        if len(rot) < 2:
            continue
        q0 = np.asarray(rot[0]["q"], float)
        q1 = np.asarray(rot[1]["q"], float)
        d = abs(float(np.dot(q0, q1)))          # |cos(θ/2)|
        ang = np.degrees(2.0 * np.arccos(min(1.0, d)))
        mx = max(mx, ang)
    return 1 if mx > thresh_deg else 0


def load_mesh(path):
    d = np.load(path, allow_pickle=True)
    m = {
        "verts": np.asarray(d["verts"], np.float32),
        "uv": np.asarray(d["uv"], np.float32),
        "faces": np.asarray(d["faces"], np.int64).ravel(),
        "face_group": np.asarray(d["face_group"], np.int64).ravel(),
        "materials": [str(x) for x in d["materials"]],
        "group_names": [str(x) for x in d["group_names"]],
    }
    m["normals"] = (np.asarray(d["normals"], np.float32) if "normals" in d.files
                    else None)
    if "bone_idx" in d.files:
        m["bone_idx"] = np.asarray(d["bone_idx"], np.int64)
        m["bone_wt"] = np.asarray(d["bone_wt"], np.float64)
    return m


def find_mbtool(explicit=None):
    """探测 mbtool.exe —— 不写死盘符。"""
    cands = []
    if explicit:
        cands.append(Path(explicit))
    if os.environ.get("MB_TOOL"):
        cands.append(Path(os.environ["MB_TOOL"]))
    cands += [
        HERE.parent / "mbtool" / "bin" / "Release" / "net9.0" / "mbtool.exe",
        HERE.parent.parent / "mb-tools" / "mbtool" / "bin" / "Release" / "net9.0" / "mbtool.exe",
    ]
    for c in cands:
        if c and Path(c).exists():
            return str(c)
    return None


def open_pack(pack, workroot, mbtool=None, verbose=True):
    """把任意 .tpac 变成预览器能吃的 <char>.npz + PNG（exportmod + import_mod）。

    返回 (posed_dir, tex_dir, skeleton_path)。
    """
    mb = find_mbtool(mbtool)
    if not mb:
        raise SystemExit("要用 --pack 打开 .tpac 需要 mbtool.exe —— "
                         "用 --mbtool 指定，或设 MB_TOOL 环境变量")
    pack = Path(pack)
    exp = Path(workroot) / (pack.stem + "_export")
    imp = Path(workroot) / (pack.stem + "_imported")
    tex = imp / "tex_png"

    if verbose:
        print(f"[pack] {pack.name} -> {exp}")
    r = subprocess.run([mb, "exportmod", str(pack), str(exp)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise SystemExit(f"exportmod 失败：\n{(r.stdout or '') + (r.stderr or '')}")
    if verbose:
        for line in (r.stdout or "").strip().splitlines():
            print("   " + line)

    cmd = [sys.executable, str(HERE / "import_mod.py"),
           "--export", str(exp), "--out", str(imp), "--tex-out", str(tex)]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise SystemExit(f"import_mod 失败：\n{(r.stdout or '') + (r.stderr or '')}")
    if verbose:
        for line in (r.stdout or "").strip().splitlines():
            print("   " + line)

    skel = Path(workroot) / "bl_skeleton.json"
    if not skel.exists() and DEFAULT_SKELETON.exists():
        skel = DEFAULT_SKELETON
    return imp, tex, skel


class DataSet:
    """角色 / 动画 / 网格 / 逐帧缓存的管理者（惰性构建，LRU 淘汰）。"""

    def __init__(self, posed_dir, skeleton, anims, tex_map, nframes, start,
                 anim_index=None, cache_slots=2, drop_mats=None, max_seconds=None,
                 min_fps=15.0):
        self.posed_dir = Path(posed_dir)
        self.skeleton = skeleton
        self.anims = list(anims)                  # [(name, path), ...]
        self.nframes = max(1, nframes)
        self.start = start
        self.cache_slots = max(1, cache_slots)
        self.anim_index = anim_index or {}

        self.chars = sorted(
            Path(p).stem for p in _glob.glob(str(self.posed_dir / "*.npz"))
            if not os.path.basename(p).startswith("_"))
        if not self.chars:
            raise SystemExit(f"{self.posed_dir} 下没有 <角色>.npz")

        self.tex_map = tex_map or {}
        self.tex_dir = tex_map.get("__dir__") if tex_map else None
        # ★ 工程有意丢弃的材质（走光保护片 / 眼遮挡 / 泪线）：最终 mod 里没有它们，
        #   但中间产物还带着 —— 不跳过的话保护片会直接挡在身体前面。
        self.drop_mats = set(drop_mats or ())
        self.max_seconds = max_seconds
        self.min_fps = min_fps

        rest, Rrest, parent, names, order = load_skeleton(skeleton)
        self.rest, self.Rrest, self.parent, self.names, self.order = \
            rest, Rrest, parent, names, order
        self.Mrest = {}
        for i in order:
            m = np.eye(4)
            m[:3, :3] = Rrest[i]
            m[:3, 3] = rest[i]
            self.Mrest[i] = m
        # rest 的逆只依赖骨架，预计算一次（原来每帧每骨都求一遍）
        self.Mrest_inv = {i: np.linalg.inv(self.Mrest[i]) for i in order}

        self._meshes = {}
        self._frames = {}       # key -> frames dict
        self._order_keys = []   # LRU 顺序
        self._anim_cache = {}

    # ---------- 动画 ----------
    def anim_json(self, idx):
        name, path = self.anims[idx]
        if name not in self._anim_cache:
            self._anim_cache[name] = json.load(open(path, encoding="utf-8"))
        return self._anim_cache[name]

    def anim_meta(self, idx):
        """动画的时长信息：优先用 clip 的 duration（游戏自己的数据）。"""
        name, path = self.anims[idx]
        meta = dict(self.anim_index.get(Path(path).stem, {}))
        if "tEnd" not in meta:
            a = self.anim_json(idx)
            meta["tEnd"] = max(b["rot"][-1]["t"] for b in a["boneAnims"] if b["rot"])
        if "seconds" not in meta:
            sec = meta.get("clipDuration")
            if sec:
                meta["seconds"] = sec
                meta["fps"] = meta["tEnd"] / sec if sec > 0 else None
        return meta

    # ---------- 网格 ----------
    def mesh(self, char):
        if char not in self._meshes:
            m = load_mesh(self.posed_dir / (char + ".npz"))
            if "bone_idx" not in m:
                raise SystemExit(f"{char}.npz 没有 bone_idx/bone_wt —— "
                                 f"需要带蒙皮权重的产物")
            mx = int(np.asarray(m["bone_idx"]).max()) if m["bone_idx"].size else -1
            if mx > 27:
                # BL 人形骨架是 28 个引擎索引（0..27）。索引更大说明这个网格
                # 绑的是**别的骨架**（原生静态件/生物等），套 BL 动画必然错位。
                print(f"  [!!] {char}: 骨骼索引最大 {mx} > 27 —— "
                      f"这个网格不是 BL 27 骨骨架，套 BL 动画会错位/炸开")
            self._meshes[char] = m
        return self._meshes[char]

    # ---------- 帧 ----------
    def frames(self, char, anim_idx):
        key = (char, anim_idx)
        if key in self._frames:
            self._order_keys.remove(key)
            self._order_keys.append(key)
            return self._frames[key]

        mesh = self.mesh(char)
        anim = self.anim_json(anim_idx)
        meta = self.anim_meta(anim_idx)
        t_end = float(meta["tEnd"])
        # 跳过 rest 帧（见 anim_start_offset 的说明）
        t0_off = anim_start_offset(anim, self.order) if self.start == 0 else 0
        if t0_off:
            meta = dict(meta, restFrameSkipped=True)
        # ★ 长动画（装备页待机 15 秒）整段均匀采 N 帧 = 每秒只有几帧，看着卡。
        #   --seconds 只取前几秒：idle 这类循环动画看 3~4 秒足够判断姿势，
        #   同样的帧数下流畅度提高好几倍。
        t_per_sec = (meta["tEnd"] / float(meta["seconds"])) if meta.get("seconds") else None
        t_beg = self.start + t0_off
        if self.max_seconds and t_per_sec:
            t_end = min(t_end, t_beg + self.max_seconds * t_per_sec)
        elif t_per_sec and self.min_fps > 0:
            # 整段采样但帧数不够 ⇒ 播放帧率会低到"一顿一顿"（15 秒的待机
            # 用 48 帧只有 3.2 fps）。这时默认只取前几秒，保证播放顺得起来。
            keep = self.nframes / self.min_fps
            if keep < meta["seconds"] - 1e-6:
                t_end = min(t_end, t_beg + keep * t_per_sec)
        n = self.nframes
        # 循环动画不要重复首尾（endpoint=False），否则循环处会卡一下
        cyclic = bool(meta.get("cyclic")) or ("clipFlags" in meta and
                                              "cyclic" in (meta.get("clipFlags") or []))
        ts = (np.linspace(t_beg, t_end, n, endpoint=not cyclic) if n > 1
              else np.array([float(t_beg)]))

        R0 = {i: anim["boneAnims"][i]["rot"][0]["q"] for i in self.order}
        V_arm = np.asarray(mesh["verts"], np.float64) @ AP.C_ARM_FROM_ENG.T
        idx, wt = mesh["bone_idx"], mesh["bone_wt"]
        N_eng = mesh["normals"]
        N_arm = (N_eng @ AP.C_ARM_FROM_ENG.T).astype(np.float64) if N_eng is not None else None

        t0 = time.time()
        pos, nrm, joints = [], [], []
        for t in ts:
            Ms = AP.build_pose(self.rest, self.Rrest, self.parent, self.order,
                               anim, float(t), R0)
            # 位置和法线共用同一套蒙皮矩阵（原来各算一遍，还各自求逆）
            mats = AP.pose_matrices(Ms, self.Mrest, self.Mrest_inv)
            pos.append((AP.lbs(V_arm, idx, wt, Ms, self.Mrest, mats=mats)
                        @ AP.C_ARM_FROM_ENG).astype(np.float32))
            if N_arm is not None:
                nrm.append((AP.transform_normals(N_arm, idx, wt, Ms, self.Mrest,
                                                 mats=mats)
                            @ AP.C_ARM_FROM_ENG).astype(np.float32))
            # 关节位置也一起存下来（只有 28×3 个数，可以忽略不计）：
            # 这样"显示骨骼"不用另算一遍 LBS 的姿势。
            # ★ 必须按 **engine id** 索引，不能按 order 里的位置 —— draw_bones
            #   拿 parent[i]/i（engine id）来取，两者不一致时骨架就是错的
            #   （现在没炸只因为 bl_skeleton 的 engine_index 恰好是连续的 0..27，
            #    换成有空洞的骨架就会 IndexError 或连错骨）。
            nid = (max(self.order) + 1) if self.order else 0
            Jmap = np.zeros((nid, 3))
            for i in self.order:
                Jmap[i] = Ms[i][:3, 3]
            joints.append(Jmap @ AP.C_ARM_FROM_ENG)
        # ★ 实际采样覆盖了多少**秒** —— 播放帧率必须按它算，不能按整段动画的
        #   秒数算：只取前 3.2 秒（48 帧）却按 15 秒算，会得到 3.2 fps ⇒ 慢放 4.7 倍。
        sec_cov = ((t_end - t_beg) / t_per_sec) if t_per_sec else None
        fr = {"name": self.anims[anim_idx][0], "pos": np.stack(pos),
              "nrm": np.stack(nrm) if nrm else None, "t": ts, "meta": meta,
              "seconds_covered": sec_cov,
              "joints": np.stack(joints).astype(np.float32)}
        print(f"  [frames] {char}/{fr['name']}: {len(ts)} 帧, "
              f"t={ts[0]:.0f}..{ts[-1]:.0f}"
              + ("（已跳过 rest 帧 t=0）" if t0_off else "")
              + f", {time.time()-t0:.1f}s"
              + (f", clip 时长 {meta.get('seconds'):.2f}s" if meta.get("seconds") else ""))

        self._frames[key] = fr
        self._order_keys.append(key)
        while len(self._order_keys) > self.cache_slots:
            old = self._order_keys.pop(0)
            if old != key:
                self._frames.pop(old, None)
        return fr

    # ---------- 贴图 / 材质状态 ----------
    def tex_info(self, char, mat, gname):
        """组 -> {tex, alpha_test, blend}。

        有导入映射（texmap.json）就用**精确**的贴图槽与材质状态；
        没有就退回关键词猜贴图 + 按材质名猜镂空（工程 work/posed 那套走这条）。
        """
        alpha_test, blend = 0.0, False
        guessed = False
        # 查表顺序：组名 → 材质名 → __materials__[材质名]
        #   tpac 导入的映射按**组名**（xj7_yue_body.0）；
        #   工程映射表（project_map.py）按**材质名**（MI_MAJ02_01_hair）。
        ent = self.tex_map.get(gname)
        if not isinstance(ent, dict):
            ent = self.tex_map.get(mat)
        if not isinstance(ent, dict):
            byc = self.tex_map.get("__by_char__") or {}
            ent = (byc.get(char) or {}).get(mat)     # 工程映射表按角色分组
        if not isinstance(ent, dict):
            mats = self.tex_map.get("__materials__") or {}
            slots0 = mats.get(mat)
            if isinstance(slots0, dict):             # __materials__ 也可能是完整条目
                ent = dict(slots0)
                ent.setdefault("material", mat)
            elif slots0:
                ent = {"material": mat, "slots": slots0,
                       "alphaTest": None, "blendMode": None}
        if isinstance(ent, dict):
            slots = ent.get("slots") or {}
            at = ent.get("alphaTest")
            if isinstance(at, (int, float)) and at > 0:
                alpha_test = float(at)
            bm = (ent.get("blendMode") or "").lower()
            blend = bm in ("modulate", "alpha_blend", "transparent", "factor")
            # 基色槽：这个工程里 0 = _d；换成别的模板时按槽位里的名字兜底
            tex = None
            for k in ("0", "1"):
                tn = slots.get(k)
                if tn and self.tex_dir and (Path(self.tex_dir) / (tn + ".png")).exists():
                    tex = str(Path(self.tex_dir) / (tn + ".png"))
                    break
            if tex is None:
                for tn in slots.values():
                    if tn and self.tex_dir and (Path(self.tex_dir) / (tn + ".png")).exists():
                        tex = str(Path(self.tex_dir) / (tn + ".png"))
                        break
            if alpha_test <= 0 and self._looks_cutout(mat):
                alpha_test = HAIR_ALPHA_TEST
            return {"tex": tex, "alpha_test": self._override_at(alpha_test),
                    "blend": blend, "guessed": tex is None}

        # ---- 没有映射表时的兜底（工程 work/posed 那条路）----
        if self._looks_cutout(mat):
            alpha_test = HAIR_ALPHA_TEST
        return {"tex": self._guess_tex(char, mat),
                "alpha_test": self._override_at(alpha_test),
                "blend": blend, "guessed": True}

    def _override_at(self, at):
        """--alpha-test 覆盖（调试「发片看不见」时用）。"""
        return float(ALPHA_TEST_OVERRIDE) if ALPHA_TEST_OVERRIDE is not None else at

    def is_dropped(self, mat):
        """工程声明的丢弃材质（支持前缀写法）。"""
        if not self.drop_mats or not mat:
            return False
        if mat in self.drop_mats:
            return True
        return any(mat.startswith(d) or d in mat for d in self.drop_mats)

    @staticmethod
    def _looks_cutout(mat):
        """头发/睫毛/眉毛这类靠 alphaTest 镂空的材质。"""
        low = (mat or "").lower()
        return any(k in low for k in ("hair", "lash", "brow", "beard", "fur"))

    def _guess_tex(self, char, mat):
        """按材质名里的词去猜贴图。

        ★ 顺序很重要：先拿**材质名自己的词**（yue_face -> yue_face_d.png）去试，
        试不到再走关键词表。早先直接遍历关键词表，第一个词 cloth1 就命中，
        于是**所有组都被套上同一张 cloth1 贴图**（整模型发青）。
        """
        if not self.tex_dir:
            return None
        d = Path(self.tex_dir)
        words = [w for w in (mat or "").lower().replace(":", "_").split("_") if w]
        for w in reversed(words):
            p = d / f"{char}_{w}_d.png"
            if p.exists():
                return str(p)
        for k in TEX_KEYWORDS:
            p = d / f"{char}_{k}_d.png"
            if p.exists():
                return str(p)
        return None


def flatten_transparent(rgba):
    """把**完全透明**像素的 RGB 填成不透明像素的中位色。

    为什么必须做
    ------------
    头发/睫毛这类镂空贴图有一半以上像素 `alpha=0`（实测 yue_hair_d 的 alpha
    中位数就是 **0**），而它们在 RGB 上往往是白色或未定义值。开了 mipmap 之后，
    缩小时采样的低级别 mip 是"发丝 + 一片白"的平均 ⇒ 发丝从深棕变成**白灰色**，
    看上去还带噪点。
    先把透明区的颜色填成发丝自己的颜色，缩小后的平均值才是对的。
    （标准做法叫 alpha bleed / dilation；这里做全局填充版，够用且是 O(N)。）
    """
    a = rgba[:, :, 3]
    solid = a > 64
    if not solid.any() or solid.all():
        return rgba
    med = np.median(rgba[:, :, :3][solid], axis=0)
    out = rgba.copy()
    out[~solid, :3] = med
    return out


def load_texmap(imported_dir):
    """读 import_mod.py 产出的 texmap.json。

    结构：``{组名: {material, slots, alphaTest, blendMode}, "__materials__": {...},
    "__dir__": <png 目录>}``。键是**子网格组名**——预览器的 group_names 就是它。
    """
    imported_dir = Path(imported_dir)
    p = imported_dir / "texmap.json"
    if not p.exists():
        return None
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        d.setdefault("__dir__", str(imported_dir / "tex_png"))
        return d
    except Exception as e:
        print(f"  [texmap] 读取失败 {type(e).__name__}: {e}")
        return None


# ==========================================================================
#  渲染
# ==========================================================================
class Viewer:
    def __init__(self, data, args, tex_dir=None, window=None):
        self.data = data
        self.args = args
        self.window = window          # 帧变了要请求重绘，否则画面不刷新
        self._buf_size = 0
        self._tex_cache = {}          # (png 路径, 抠透明) -> GL 纹理名（跨角色/跨 mod 复用）
        self.ui_epoch = 0             # UI 层改过状态就 +1（按钮文案靠它重建）
        self.tex_dir = Path(tex_dir) if tex_dir else None
        self.ci, self.ai, self.fi = 0, 0, 0
        self._cur = 0                 # 当前帧下标（cur 属性带取模）
        self.playing = True
        self.show_tex = True
        self.show_bones = False       # 叠加显示骨架（关节 + 骨链）
        self.rot = [0.35, 0.0]
        self.dist = 3.4
        # ★★ 这是**帧推进的累积器**，必须从 0 开始，不能写 time.time()。
        #   写成 time.time() 的话它是 Unix 时间戳（≈1.7e9），而 tick 里是
        #       while self.last >= step:  self.last -= step     # step ≈ 1/84 s
        #   于是**第一次 tick 就进入要迭代 1.4e11 次的死循环**：
        #   窗口开得出来、首帧也画了（所以"能看见人物"），但事件循环再也回不来
        #   ⇒ 人物一动不动 + CPU 跑满 ⇒ Windows 提示"无响应"。
        self.last = 0.0
        self.only_mats = [x.strip().lower() for x in (args.only_mats or "").split(",") if x.strip()]
        self._group_cache = {}
        self._build_groups()

    # ---- 当前状态 ----
    @property
    def char(self):
        return self.data.chars[self.ci]

    @property
    def frames(self):
        return self.data.frames(self.char, self.ai)

    @property
    def cur(self):
        return self._cur % self.frames["pos"].shape[0]

    @cur.setter
    def cur(self, v):
        self._cur = v

    def _build_groups(self):
        """按材质组切三角索引（切角色时重建）。"""
        key = self.char
        if key in self._group_cache:
            self.groups = self._group_cache[key]
            self._upload_static()
            return
        mesh = self.data.mesh(self.char)
        F, FG = mesh["faces"].reshape(-1, 3), mesh["face_group"]
        groups = []
        dropped = 0
        for gi in np.unique(FG):
            sel = F[FG == gi]
            if not len(sel):
                continue
            gname = (mesh["group_names"][int(gi)] if int(gi) < len(mesh["group_names"])
                     else "")
            mat = mesh["materials"][int(gi)] if int(gi) < len(mesh["materials"]) else ""
            if self.data.is_dropped(mat):
                dropped += 1
                continue
            if self.only_mats and not any(w in (mat or "").lower() or w in gname.lower()
                                          for w in self.only_mats):
                continue
            info = self.data.tex_info(self.char, mat, gname)
            groups.append({
                "idx": sel.astype(np.uint32).ravel(),
                "mat": mat, "gname": gname,
                "tex": info["tex"], "alpha_test": info["alpha_test"],
                "blend": info["blend"], "guessed": info.get("guessed"),
                "texid": None, "ntri": len(sel),
            })
        self._group_cache[key] = groups
        self.groups = groups
        if dropped:
            print(f"  [drop] {self.char}: 跳过 {dropped} 个工程声明丢弃的材质组")
        self._upload_static()

    # ---- GPU ----
    def _upload_static(self):
        from pyglet.gl import (glGenBuffers, glBindBuffer, glBufferData,
                               GL_ARRAY_BUFFER, GL_STATIC_DRAW,
                               glDeleteBuffers)
        mesh = self.data.mesh(self.char)
        if mesh["normals"] is None:
            mesh["normals"] = np.zeros_like(mesh["verts"])
        # 顶点/法线缓冲与角色无关（尺寸随 upload_dynamic 重新分配），只在首次建
        if getattr(self, "pos_buf", None) is None:
            self.pos_buf = ctypes.c_uint()
            self.nrm_buf = ctypes.c_uint()
            glGenBuffers(1, ctypes.byref(self.pos_buf))
            glGenBuffers(1, ctypes.byref(self.nrm_buf))
        else:
            # ★ 切角色要重建 UV / 索引缓冲：旧的要显式删除，
            #   否则反复切角色会一直泄漏 GL buffer。
            olds = [b for b in [getattr(self, "uv_buf", None)] if b]
            olds += [g.get("ibuf") for g in getattr(self, "groups", []) if g.get("ibuf")]
            if olds:
                arr = (ctypes.c_uint * len(olds))(*olds)
                glDeleteBuffers(len(olds), arr)

        UV = np.ascontiguousarray(mesh["uv"])
        self.uv_buf = ctypes.c_uint()
        glGenBuffers(1, ctypes.byref(self.uv_buf))
        glBindBuffer(GL_ARRAY_BUFFER, self.uv_buf)
        glBufferData(GL_ARRAY_BUFFER, UV.nbytes, UV.ctypes.data_as(ctypes.c_void_p),
                     GL_STATIC_DRAW)
        for g in self.groups:
            b = ctypes.c_uint()
            glGenBuffers(1, ctypes.byref(b))
            glBindBuffer(GL_ARRAY_BUFFER, b)
            glBufferData(GL_ARRAY_BUFFER, g["idx"].nbytes,
                         g["idx"].ctypes.data_as(ctypes.c_void_p), GL_STATIC_DRAW)
            g["ibuf"] = b
        self._buf_size = 0        # 顶点数可能变了，下一帧重新预分配

    def upload_dynamic(self):
        """把当前帧的顶点/法线推到 GPU。

        ★ 用**预分配 + glBufferSubData**，不要每帧 glBufferData：
          后者每次都让驱动重新分配显存（实测在集显上能把 UI 线程拖到
          "Windows 提示无响应"）。buffer 只在顶点数变化时重新分配一次。
        """
        from pyglet.gl import (glBindBuffer, glBufferData, glBufferSubData,
                               GL_ARRAY_BUFFER, GL_DYNAMIC_DRAW)
        fr = self.frames
        _t0 = time.time()
        P = np.ascontiguousarray(fr["pos"][self.cur])
        N = np.ascontiguousarray(fr["nrm"][self.cur] if fr["nrm"] is not None
                                 else self.data.mesh(self.char)["normals"])
        need = max(P.nbytes, N.nbytes)
        if self._buf_size < need:
            glBindBuffer(GL_ARRAY_BUFFER, self.pos_buf)
            glBufferData(GL_ARRAY_BUFFER, need, None, GL_DYNAMIC_DRAW)
            glBindBuffer(GL_ARRAY_BUFFER, self.nrm_buf)
            glBufferData(GL_ARRAY_BUFFER, need, None, GL_DYNAMIC_DRAW)
            self._buf_size = need
        glBindBuffer(GL_ARRAY_BUFFER, self.pos_buf)
        glBufferSubData(GL_ARRAY_BUFFER, 0, P.nbytes,
                        P.ctypes.data_as(ctypes.c_void_p))
        glBindBuffer(GL_ARRAY_BUFFER, self.nrm_buf)
        glBufferSubData(GL_ARRAY_BUFFER, 0, N.nbytes,
                        N.ctypes.data_as(ctypes.c_void_p))
        if getattr(self, "stats", None) is not None:
            self.stats["upload_ms"] += (time.time() - _t0) * 1000.0
            self.stats["upload_n"] += 1

    def load_textures(self):
        from pyglet.gl import (glGenTextures, glBindTexture, glTexParameteri,
                               GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR,
                               GL_LINEAR_MIPMAP_LINEAR,
                               GL_TEXTURE_MAG_FILTER, GL_TEXTURE_WRAP_S,
                               GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE, glTexImage2D,
                               GL_RGBA, GL_UNSIGNED_BYTE, glPixelStorei,
                               GL_UNPACK_ALIGNMENT, glGenerateMipmap)
        from PIL import Image
        n = new = 0
        cache = self._tex_cache
        for g in self.groups:
            if not g["tex"]:
                continue
            n += 1
            # ★ 按 (png 路径, 是否要抠透明) 缓存 GPU 纹理。
            #   早先的判重键是"每个组自己的 texid"，于是 28 个组就上传 28 张
            #   2048² 纹理 —— 实测 RSS 1.46 GB（核显吃的是系统内存），而按路径
            #   去重只需要 11 张。换 mod 时更惨：旧纹理从不 glDeleteTextures。
            key = (g["tex"], bool((g.get("alpha_test") or 0) > 0))
            if key in cache:
                g["texid"] = cache[key]
                continue
            if g["texid"]:
                continue
            try:
                im = Image.open(g["tex"]).convert("RGBA")
                # ★ V 轴方向：**默认不翻**。
                #   npz 里的 uv 是 top-origin（v=0 = 贴图**顶行**，见工程
                #   build_assets.py 的实测：脸的 v 随高度递减，下巴 0.83 / 颅顶 0.32），
                #   而 glTexImage2D 的**第一行数据落在 t=0**。所以把 PNG 原样上传，
                #   v=0 才正好对上图片顶行。
                #   早先按"OpenGL 的 v=0 在底行"把图上下翻转上传 —— 那是对
                #   bottom-origin 的 uv 才成立，结果五官整体上下错位、裙摆花纹错乱。
                #   换源模型时必须重新实测（另一个工程 mb2mod-ada 的约定正好相反），
                #   拿不准就用 --flip-tex 出 A/B 图。
                if self.args.flip_tex:
                    im = im.transpose(Image.FLIP_TOP_BOTTOM)
                # 镂空件（alphaTest>0）：先把透明区的颜色抹平，否则 mipmap 一平均
                # 发丝就发白（见 flatten_transparent 的说明）
                if (g.get("alpha_test") or 0) > 0:
                    im = Image.fromarray(flatten_transparent(np.array(im)))
                data = im.tobytes()
                tid = ctypes.c_uint()
                glGenTextures(1, ctypes.byref(tid))
                glBindTexture(GL_TEXTURE_2D, tid)
                glPixelStorei(GL_UNPACK_ALIGNMENT, 1)
                glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, im.width, im.height, 0,
                             GL_RGBA, GL_UNSIGNED_BYTE, data)
                # ★ 生成 mip 链并把缩小过滤设成三线性：只上传 mip0 的话，
                #   头发这种高频细节贴图在缩小时会剧烈走样 —— 看上去就是
                #   "头发上全是噪点"。2048² 的图缩到 800px 窗口正踩这个坑。
                try:
                    glGenerateMipmap(GL_TEXTURE_2D)
                    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER,
                                    GL_LINEAR_MIPMAP_LINEAR)
                except Exception:
                    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
                glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
                glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
                glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
                g["texid"] = tid
                cache[key] = tid
                new += 1
            except Exception as e:
                print(f"  [tex] {g['mat']}: {type(e).__name__} {e}")
        print(f"  [tex] {self.char}: {n}/{len(self.groups)} 组有贴图"
              f"（GPU 纹理新增 {new}，去重缓存共 {len(cache)} 张）")
        if new:
            gs = [g for g in self.groups if g.get("guessed")]
            if gs:
                # ★ 猜出来的映射**不可信**：猜不中时会静默退到关键词表的第一个词，
                #   结果是十几个组共用同一张贴图（看上去"贴图紊乱"）。
                #   与其让人对着乱图猜原因，不如直接把话说清楚。
                print(f"  [tex] !! {len(gs)}/{len(self.groups)} 组的贴图是**猜**出来的"
                      f"（没有精确映射表），可能对不上：")
                for g in gs[:4]:
                    print(f"         {g['gname']}  材质={g['mat']}")
                if len(gs) > 4:
                    print(f"         … 其余 {len(gs)-4} 组")
                print(f"       建议改用 --pack <pack0.tpac>（从最终产物读回，映射精确）"
                      f"或给工程补一份 work/texmap_project.json")

    def draw(self, w, h):
        from pyglet.gl import (
            glClearColor, glClear, GL_COLOR_BUFFER_BIT, GL_DEPTH_BUFFER_BIT,
            glEnable, GL_DEPTH_TEST, glMatrixMode, GL_PROJECTION, glLoadIdentity,
            GL_MODELVIEW, GL_LIGHTING, GL_LIGHT0, GL_LIGHT1, glLightfv, GL_POSITION,
            GL_DIFFUSE, GL_AMBIENT, GL_COLOR_MATERIAL, glColorMaterial,
            GL_FRONT_AND_BACK, GL_AMBIENT_AND_DIFFUSE, glColor3f,
            glEnableClientState, GL_VERTEX_ARRAY, GL_NORMAL_ARRAY,
            GL_TEXTURE_COORD_ARRAY, glBindBuffer, GL_ARRAY_BUFFER,
            glVertexPointer, GL_FLOAT, glNormalPointer, glTexCoordPointer,
            GL_TEXTURE_2D, glBindTexture, glDisable, GL_TRIANGLES,
            glDrawElements, GL_UNSIGNED_INT, GL_ELEMENT_ARRAY_BUFFER,
            glDisableClientState, GL_ALPHA_TEST, glAlphaFunc, GL_GREATER,
            glLightModeli, GL_LIGHT_MODEL_TWO_SIDE,
            GL_BLEND, glBlendFunc, GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA, glDepthMask,
            glColor4f)
        from pyglet.gl.glu import gluPerspective, gluLookAt
        glClearColor(0.10, 0.11, 0.13, 1.0)
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        glEnable(GL_DEPTH_TEST)

        glMatrixMode(GL_PROJECTION); glLoadIdentity()
        gluPerspective(38.0, max(1, w) / max(1, h), 0.05, 60.0)
        glMatrixMode(GL_MODELVIEW); glLoadIdentity()

        # ★ 光照在**世界空间**设置（此刻 modelview 还是单位阵），否则光会跟着相机转，
        #   一转视角明暗就漂移，看不出皮肤/布料真实的明暗关系。
        if self.args.unlit:
            glDisable(GL_LIGHTING)         # 直接看贴图原色（验收用）
        else:
            glEnable(GL_LIGHTING)
        glEnable(GL_LIGHT0)
        glEnable(GL_LIGHT1)
        # ★ 光量要**配平到 ≈1.0**（ambient + diffuse）。
        #   早先是 0.55 + 0.95 = 迎光面被放大 1.5 倍：深棕头发 [74,60,49]
        #   被抬到 ~[111,90,74]，看上去就是"白灰色头发"—— 而用 --unlit
        #   一看，贴图本身明明是深棕。固定管线里颜色 = 贴图 ×(ambient+diffuse·N·L)，
        #   配平之后贴图原色才被还原，同时保留明暗关系。
        glLightfv(GL_LIGHT0, GL_POSITION, (ctypes.c_float * 4)(0.45, 0.75, 0.9, 0.0))
        glLightfv(GL_LIGHT0, GL_DIFFUSE, (ctypes.c_float * 4)(0.60, 0.60, 0.60, 1.0))
        glLightfv(GL_LIGHT0, GL_AMBIENT, (ctypes.c_float * 4)(0.40, 0.40, 0.42, 1.0))
        # 反向补光：否则背面发片/裙内侧死黑，看不出接缝
        glLightfv(GL_LIGHT1, GL_POSITION, (ctypes.c_float * 4)(-0.5, -0.7, -0.2, 0.0))
        glLightfv(GL_LIGHT1, GL_DIFFUSE, (ctypes.c_float * 4)(0.22, 0.22, 0.24, 1.0))
        glLightfv(GL_LIGHT1, GL_AMBIENT, (ctypes.c_float * 4)(0.0, 0.0, 0.0, 1.0))
        # ★★ 双面光照：骑砍的发丝/裙摆是 `two_sided` 材质，**两面都要照亮**。
        #   GL 默认 GL_LIGHT_MODEL_TWO_SIDE=FALSE —— 背面会拿"正面的法线"去算光照，
        #   结果恒为背光。深棕发丝 [74,60,49] 乘上只剩环境光就变成 [30,24,20]，
        #   而预览器背景是 [26,28,33]：**发片直接融进背景，看上去就是"消失了"**，
        #   而且表现为"从哪个视角看就看不到哪个方向的头发"（那个方向的法线背光）。
        #   只做 glDisable(GL_CULL_FACE)（两面都画）是不够的，必须同时开双面光照。
        glLightModeli(GL_LIGHT_MODEL_TWO_SIDE, 1)
        glEnable(GL_COLOR_MATERIAL)
        glColorMaterial(GL_FRONT_AND_BACK, GL_AMBIENT_AND_DIFFUSE)

        import math
        yaw, pitch = self.rot
        pivot = np.array([0.0, 0.0, 0.92], np.float32)
        # ★ 相机放在 **+Y** 侧：BL 引擎空间里 +Y 是角色的正前方
        #   （与工程 render.py 的 front 视角 (cx, cy+dist, cz) 一致）。
        #   写成 -Y 会从背后看 —— 当初就是这么把默认视角搞反的。
        eye = pivot + self.dist * np.array([
            math.sin(yaw) * math.cos(pitch),
            math.cos(yaw) * math.cos(pitch),
            math.sin(pitch)])
        gluLookAt(float(eye[0]), float(eye[1]), float(eye[2]),
                  float(pivot[0]), float(pivot[1]), float(pivot[2]),
                  0.0, 0.0, 1.0)

        glEnableClientState(GL_VERTEX_ARRAY)
        glEnableClientState(GL_NORMAL_ARRAY)
        glEnableClientState(GL_TEXTURE_COORD_ARRAY)
        glBindBuffer(GL_ARRAY_BUFFER, self.pos_buf)
        glVertexPointer(3, GL_FLOAT, 0, None)
        glBindBuffer(GL_ARRAY_BUFFER, self.nrm_buf)
        glNormalPointer(GL_FLOAT, 0, None)
        glBindBuffer(GL_ARRAY_BUFFER, self.uv_buf)
        glTexCoordPointer(2, GL_FLOAT, 0, None)

        for g in self.groups:
            if g["texid"] and self.show_tex:
                glEnable(GL_TEXTURE_2D)
                glBindTexture(GL_TEXTURE_2D, g["texid"])
                # ★ 镂空件（头发/睫毛/眉毛）靠 alphaTest 剪出来。不剪的话
                #   整张发片会显示成一块实心色 —— 实测"头发变一整片亮绿"。
                #   同时必须把材质色复位成白色，否则会带上上一组的灰色调制。
                at = g.get("alpha_test") or 0.0
                if at > 0:
                    glEnable(GL_ALPHA_TEST)
                    glAlphaFunc(GL_GREATER, float(at))
                else:
                    glDisable(GL_ALPHA_TEST)
                if g.get("blend"):
                    glEnable(GL_BLEND)
                    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
                    glDepthMask(0)
                else:
                    glDisable(GL_BLEND)
                glColor3f(1.0, 1.0, 1.0)
            else:
                glDisable(GL_TEXTURE_2D)
                glDisable(GL_ALPHA_TEST)
                glDisable(GL_BLEND)
                glColor3f(0.72, 0.74, 0.78)
            glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, g["ibuf"])
            glDrawElements(GL_TRIANGLES, len(g["idx"]), GL_UNSIGNED_INT, None)
            glDepthMask(1)
        glDisableClientState(GL_VERTEX_ARRAY)
        glDisableClientState(GL_NORMAL_ARRAY)
        glDisableClientState(GL_TEXTURE_COORD_ARRAY)
        if self.show_bones:
            self.draw_bones()
        # 收尾复位：别把"某个材质组的状态"留给后面的绘制者
        # （UI 层已经因为这类残留吃过一次亏：按钮底色被贴图调制、被 alphaTest 剪掉）
        glDisable(GL_ALPHA_TEST)
        glDisable(GL_BLEND)
        glDisable(GL_TEXTURE_2D)
        glDepthMask(1)
        glColor4f(1.0, 1.0, 1.0, 1.0)

    # ---- 骨骼叠加 ----
    def draw_bones(self):
        """把当前帧的骨架画出来：骨链用线、关节用点。

        关节位置在 `frames()["joints"]` 里（engine 空间，和顶点同一坐标系）。
        画的时候**关掉深度测试**：骨骼本来就在网格内部，开深度的话几乎全被挡住，
        而"预览骨骼"的用途恰恰是看清骨架结构（要看遮挡关系就把 show_tex 关掉，
        模型变灰色线框感更强）。
        """
        from pyglet.gl import (glDisable, glEnable, GL_DEPTH_TEST, glLineWidth,
                               glPointSize, GL_LINES, GL_POINTS,
                               GL_ALPHA_TEST, GL_TEXTURE_2D, GL_BLEND,
                               GL_LIGHTING, GL_CULL_FACE, GL_COLOR_ARRAY,
                               glEnableClientState, glDisableClientState,
                               glColor4f)
        from pyglet.graphics import vertex_list
        # ★★ 画骨骼前必须把三维那边留下的状态清干净。
        #   紧挨着骨骼绘制的，是**最后一个材质组的渲染状态** —— 它可能是
        #   发丝/睫毛那种 `alphaTest=0.2745` 的镂空材质，于是骨骼线被当成
        #   "低 alpha 像素"整条剪掉；光照也会把顶点色压暗。
        #   而 `groups` 的顺序来自 `np.unique(face_group)`，**不同角色不一样** ⇒
        #   出现"月清疏能看见骨骼、白茉晴完全看不见"这种跟着角色变的怪现象
        #   （实测：bai 的骨骼开/关差异像素 = 0，即一根线都没画出来）。
        glDisable(GL_ALPHA_TEST)
        glDisable(GL_TEXTURE_2D)
        glDisable(GL_BLEND)
        glDisable(GL_LIGHTING)
        glDisable(GL_CULL_FACE)
        glColor4f(1.0, 1.0, 1.0, 1.0)
        fr = self.frames
        J = fr["joints"][self.cur]
        pairs = [(self.data.parent[i], i) for i in self.data.order
                 if self.data.parent[i] is not None]
        if not pairs:
            return
        lv = []
        for a, b in pairs:
            lv.extend(J[a]); lv.extend(J[b])
        glDisable(GL_DEPTH_TEST)
        glLineWidth(2.0)
        vl = vertex_list(len(pairs) * 2, ("v3f", tuple(lv)),
                         ("c3B", (255, 170, 60) * (len(pairs) * 2)))
        vl.draw(GL_LINES)
        vl.delete()
        glPointSize(6.0)
        pv = vertex_list(len(J), ("v3f", tuple(J.ravel())),
                         ("c3B", (120, 240, 255) * len(J)))
        pv.draw(GL_POINTS)
        pv.delete()
        glLineWidth(1.0)
        glPointSize(1.0)
        glDisableClientState(GL_COLOR_ARRAY)
        glEnable(GL_DEPTH_TEST)
        glEnable(GL_LIGHTING)          # 交还给后续绘制（UI 层自己会再清一遍）

    # ---- HUD ----
    def hud_text(self):
        fr = self.frames
        meta = fr["meta"]
        sec = meta.get("seconds")
        t = fr["t"][self.cur]
        s = (f"{self.char}  |  动画 {self.ai+1}/{len(self.data.anims)}: {fr['name']}"
             f"  |  帧 {self.cur+1}/{fr['pos'].shape[0]}  t={t:.0f}")
        if sec:
            s += f"/{meta['tEnd']:.0f}  ~{t/meta['tEnd']*sec:.2f}s/{sec:.2f}s"
        s += f"  |  {self.play_fps():.1f} fps"
        cov = fr.get("seconds_covered")
        if cov and sec and cov < sec - 0.05:
            s += f"（采样前 {cov:.1f}s）"
        if self.show_bones:
            s += "  |  骨骼开"
        if not self.playing:
            s += "  [已暂停]"
        return s

    def play_fps(self):
        """真正该用的**播放帧率** = 预计算帧数 ÷ 动画秒数。

        ★★ 千万别把 `meta["fps"]`（= t_end / clip 时长，单位是 **t 单位/秒**，
        实测 inventory_idle 是 84.5）当成帧率用：我们的"帧"是**采样帧**
        （48 帧代表 1267 个 t 单位，每帧 ≈ 26 t）。拿 84.5 当帧率 ⇒
        每秒推进 84.5 帧 = 每秒掠过 2230 个 t 单位 ⇒ **15 秒的循环 0.57 秒播完**，
        屏幕上就是"动画飞快 + 抽搐"。
        """
        fr = self.frames
        n = fr["pos"].shape[0]
        sec = fr.get("seconds_covered") or fr["meta"].get("seconds")
        return (n / sec) if sec else self.args.fps

    def tick(self, dt):
        if getattr(self, "stats", None) is not None:
            self.stats["tick"] += 1
        if not self.playing:
            return
        self.last += dt
        step = 1.0 / max(0.1, self.play_fps())
        n = self.frames["pos"].shape[0]
        moved = False
        # 一帧最多补 MAX_CATCHUP 步：窗口被拖动/系统卡了一下之后 dt 会很大，
        # 不设上限的话会在这里补几百帧（同样是"卡住"的来源）。
        steps = 0
        while self.last >= step and steps < 4:
            self.last -= step
            self._cur = (self._cur + 1) % n
            moved = True
            steps += 1
        if self.last >= step:
            self.last = 0.0            # 落后太多就丢弃，不做追赶
        if moved:
            try:
                self.upload_dynamic()
            except Exception as e:
                # 事件回调里绝不能把异常抛出去：pyglet 的 clock 是在 EventLoop
                # 内部调回调的，异常会把整个 idle 打断 ⇒ 窗口再也刷不动 =
                # "Windows 提示无响应"。出错就停下来并说清楚。
                self.playing = False
                print(f"[gui] !! 上传帧数据失败，已暂停：{type(e).__name__}: {e}")
                return
            # ★ 请求重绘要写 `win.invalid = True`。
            #   pyglet 1.5.31 的 Win32Window **没有 invalidate() 方法**（只有 invalid
            #   属性），写成 invalidate() 会在每帧抛 AttributeError ⇒
            #   窗口能开、模型也在，但**人物一动不动**，同时高频异常把 UI 拖死。
            #   实测（_probe_pyglet.py，三种写法对照）：
            #     invalid=True       -> tick 88 / on_draw 89   ✅
            #     手动 dispatch+flip -> tick 89 / on_draw 179  （双倍绘制，浪费）
            #     完全不请求          -> tick 89 / on_draw 90   （1.5 靠 redraw_all 兜住，
            #                                                    但语义不保证，别依赖）
            if self.window is not None:
                self.window.invalid = True

    def switch_anim(self, i):
        if 0 <= i < len(self.data.anims):
            self.ai = i
            self._cur = 0
            # 预计算是在主线程里同步跑的（1~2 秒），窗口这段会短暂无响应 ——
            # 至少先把话说出来，别让人以为程序死了。
            print(f"[gui] 正在计算 {self.data.anims[i][0]} 的 {self.data.nframes} 帧…",
                  flush=True)
            self.frames            # 触发构建
            self.upload_dynamic()
            print(f"[gui] 动画 -> {self.data.anims[i][0]}")

    def switch_char(self, d=1):
        self.ci = (self.ci + d) % len(self.data.chars)
        self._cur = 0
        print(f"[gui] 切到角色 {self.char}（载入贴图与网格，请稍候）…", flush=True)
        self._build_groups()
        self.load_textures()
        self.upload_dynamic()
        print(f"[gui] 角色 -> {self.char}")

    def release_textures(self):
        """换数据源前把旧纹理真正删掉（GL 纹理不受 Python GC 管）。"""
        from pyglet.gl import glDeleteTextures
        ids = list(self._tex_cache.values())
        if ids:
            arr = (ctypes.c_uint * len(ids))(*ids)
            glDeleteTextures(len(ids), arr)
        self._tex_cache.clear()
        for g in getattr(self, "groups", []):
            g["texid"] = None

    # ---- 换数据源（GUI 里选 mod）----
    def load_source(self, posed_dir, skeleton, tex_dir=None):
        """就地换成另一套数据（换 mod / 换工程），不用重启。

        ★ 要区分两种布局：
          * `<proj>/work/posed` —— 工程中间产物，材质名是**源材质名**
            （`MI_MAJ02_01_hair`），映射和"要丢弃的材质"都只存在于工程脚本里，
            必须走 project_map；
          * 其它（exportmod 导入的产物）—— 有 texmap.json，映射是精确的。
        早先这里一律只读 texmap.json，于是 GUI 里 Shift+M 打开工程目录后
        37/37 组贴图退化为主观猜测、DROP_MATS 全丢（走光保护片挡在身前）。
        """
        posed_dir = Path(posed_dir)
        proj = None
        if posed_dir.name == "posed" and posed_dir.parent.name == "work":
            proj = posed_dir.parent.parent
        tm, drop = {}, None
        if proj is not None and (proj / "pipeline").exists():
            import project_map
            drop = project_map.load_project_drop_mats(proj)
            tm = project_map.load_project_texmap(proj, tex_dir) or {}
            print(f"[gui] 识别为工程中间产物：用 project_map 取映射"
                  f"（{len(tm.get('__materials__') or {})} 条）与 DROP_MATS（{len(drop)} 项）")
        else:
            tm = load_texmap(posed_dir) or {}
        if tex_dir:
            tm["__dir__"] = str(tex_dir)      # 调用方给的目录优先（别被缓存里的旧值盖掉）
        self.data = DataSet(posed_dir, skeleton, self.data.anims, tm,
                            self.data.nframes, self.data.start,
                            self.data.anim_index, self.data.cache_slots,
                            drop_mats=drop if drop is not None
                            else getattr(self.data, "drop_mats", None))
        self.tex_dir = Path(tex_dir) if tex_dir else self.tex_dir
        self.ci = self.ai = self._cur = 0
        self._group_cache.clear()
        self.release_textures()       # 旧 mod 的纹理先删掉，否则换一次涨几百 MB
        self.groups = []
        self._build_groups()
        self.load_textures()
        self.upload_dynamic()
        print(f"[gui] 数据源 -> {posed_dir}（角色 {self.data.chars}）")


# ==========================================================================
#  入口
# ==========================================================================
# 文件对话框的起始位置：环境变量 → 上次打开过的目录 → 常见 Steam 库。
# ★ 这是"探测候选"，不是写死某个盘符（换机器/换盘符时前面的分支会兜住）。
_STEAM_MODULES = [
    "D:/SteamLibrary/steamapps/common/Mount & Blade II Bannerlord/Modules",
    "E:/SteamLibrary/steamapps/common/Mount & Blade II Bannerlord/Modules",
    "C:/SteamLibrary/steamapps/common/Mount & Blade II Bannerlord/Modules",
    "C:/Program Files (x86)/Steam/steamapps/common/Mount & Blade II Bannerlord/Modules",
    "C:/Program Files/Steam/steamapps/common/Mount & Blade II Bannerlord/Modules",
]
_LAST_DIR = []


def find_game_modules():
    env = os.environ.get("MB_GAME")
    if env:
        p = Path(env)
        if p.name.lower() != "modules":
            p = p / "Modules"
        if p.is_dir():
            return str(p)
    for c in _STEAM_MODULES:
        if Path(c).is_dir():
            return c
    return None


def pick_mod(v, a, want_dir=False):
    """GUI 内选 mod：M = 选 .tpac，Shift+M = 选工程目录。就地换数据源。"""
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception as e:
        print(f"[gui] 没有 tkinter（{type(e).__name__}: {e}）—— "
              f"改用命令行 --pack <tpac> 或 --project <工程目录>")
        return
    root = tk.Tk()
    root.withdraw()
    root.update()
    # 起始目录：上次用过的 → 当前数据源所在位置 → 游戏 Modules
    init = None
    if _LAST_DIR:
        init = _LAST_DIR[0]
    elif getattr(a, "pack", None):
        init = str(Path(a.pack).parent)
    elif getattr(a, "project", None):
        init = str(Path(a.project))
    else:
        init = find_game_modules()
    if init and not Path(init).is_dir():
        init = None
    try:
        if want_dir:
            p = filedialog.askdirectory(title="选一个工程目录（含 work/posed）",
                                        initialdir=init)
            if not p:
                return
            proj = Path(p)
            _LAST_DIR[:] = [str(proj)]
            posed = proj / "work" / "posed"
            if not posed.is_dir():
                print(f"[gui] {proj} 里没有 work/posed —— 这不是一个工程目录")
                return
            v.load_source(posed, proj / "work" / "bl_skeleton.json",
                          proj / "build" / "tex_png")
        else:
            p = filedialog.askopenfilename(
                title="选一个 .tpac（在 Modules/<mod>/AssetPackages/ 下）",
                initialdir=init,
                filetypes=[("Bannerlord 资产包", "*.tpac"), ("所有文件", "*.*")])
            if not p:
                return
            _LAST_DIR[:] = [str(Path(p).parent)]
            workroot = a.work_root or (Path(p).parent.parent / "preview_work")
            print(f"[gui] 正在从 tpac 导入（exportmod + import_mod，可能要几十秒）…")
            posed, texdir, skel = open_pack(p, workroot, a.mbtool)
            v.load_source(posed, skel, texdir)
    except Exception as e:
        print(f"[gui] 打开失败 {type(e).__name__}: {e}")
    finally:
        try:
            root.destroy()
        except Exception:
            pass


def build_argparser():
    ap = argparse.ArgumentParser()
    g = ap.add_argument_group("打开方式（三选一）")
    g.add_argument("--project", default=None, help="工程目录（用它的 work/posed）")
    g.add_argument("--pack", default=None, help="任意 .tpac（自动 exportmod + import）")
    g.add_argument("--posed-dir", default=None)
    ap.add_argument("--source", choices=["auto", "posed", "packed"], default="auto",
                    help="--project 时用哪套数据：auto=有 tpac 导入产物就用它（推荐），"
                         "posed=工程中间产物，packed=强制用导入产物")

    ap.add_argument("--skeleton", default=None)
    ap.add_argument("--anim", action="append", default=None, help="name=path.json，可重复")
    ap.add_argument("--anim-dir", default=None, help="扫该目录下所有 *.json 当动画")
    ap.add_argument("--anim-index", default=None, help="anims/index.json（含 clip 时长）")
    ap.add_argument("--tex-dir", default=None)
    ap.add_argument("--texmap", default=None, help="import_mod.py 产出的 texmap.json")
    ap.add_argument("--chars", default=None, help="逗号分隔，默认全部")
    ap.add_argument("--work-root", default=None, help="--pack 时的中间产物目录")
    ap.add_argument("--mbtool", default=None)
    ap.add_argument("--nframes", type=int, default=96,
                    help="预计算多少帧。同样的帧数下，动画越长每帧跨度越大、越卡；"
                         "长动画配合 --seconds 用")
    ap.add_argument("--min-fps", type=float, default=60.0,
                    help="默认播放帧率下限：帧数不够铺满整段时，自动只取前几秒"
                         "不足会被**混叠成抖动**：实测待机动画逐帧最大位移 "
                         "15fps 时 38mm、30fps 时 23mm、60fps 时 9.5mm —— "
                         "所以默认 60。设 0 表示不截断、整段都采")
    ap.add_argument("--seconds", type=float, default=None,
                    help="只采动画的前 N 秒（秒数按 clip 声明的时长换算到 t 轴）。"
                         "装备页待机 15 秒，看前 3~4 秒足够，且流畅得多")
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--fps", type=float, default=24.0,
                    help="兜底播放帧率；有 clip 时长时以 clip 为准")
    ap.add_argument("--cache-slots", type=int, default=1,
                    help="逐帧缓存的角色×动画组合数。一份 96 帧 ≈ 265MB（11 万顶点），"
                         "默认只留 1 份")
    ap.add_argument("--no-compose-q", action="store_true",
                    help="把动画四元数当**世界朝向**（旧行为）而不是**相对父骨的局部朝向**。"
                         "两种解读差别很大：局部朝向（默认）让待机时脚底贴地、手臂自然下垂；"
                         "世界朝向会让手臂停在 A-pose、脚踝前后晃 18cm。"
                         "换别的动画/骨架若发现姿势不对，先拿这个开关做 A/B")
    ap.add_argument("--alpha-test", type=float, default=None,
                    help="覆盖材质的 alphaTest 阈值（0 = 完全不剪）。"
                         "调试「某些发片/刘海看不见」用：有些包的镂空贴图 alpha 偏低，"
                         "按 0.2745 剪会整片消失，需要看贴图实际分布再定阈值")
    ap.add_argument("--bones", action="store_true",
                    help="启动就叠加显示骨架（等于按 B）")
    ap.add_argument("--unlit", action="store_true",
                    help="关掉光照，直接看**贴图原色**（验收贴图/V 轴时最有用："
                         "光照会把深色压暗、把亮色洗白，容易误判）")
    ap.add_argument("--only-mats", default=None,
                    help="逗号分隔，只渲染材质名包含这些词的组（如 hair,lash）")
    ap.add_argument("--flip-tex", action="store_true",
                    help="上传贴图前上下翻转。默认不翻（本源 uv 是 top-origin）；"
                         "只用来跟默认做 A/B 对照，判断 V 轴约定是否变了")
    ap.add_argument("--drop-mats", default=None,
                    help="逗号分隔：渲染时跳过的材质（前缀匹配）。"
                         "--project 时会自动从工程里读 DROP_MATS")
    ap.add_argument("--run-seconds", type=float, default=None,
                    help="跑 N 秒后自动退出并打印帧率/上传耗时 —— 用来把"
                         "『窗口卡死』变成可测量的数字（--shot 只画两帧就退，"
                         "测不到持续运行的性能问题）")
    ap.add_argument("--no-vsync", action="store_true",
                    help="关垂直同步。某些驱动上 vsync 会让 flip 长时间阻塞")
    ap.add_argument("--selftest", action="store_true", help="只加载+预计算，不开窗口")
    ap.add_argument("--shot", default=None, help="开窗渲染一帧存图后退出（验证 GL）")
    ap.add_argument("--record", default=None,
                    help="把当前角色+动画整段渲染成 PNG 序列 + GIF + 序列图，"
                         "写到这个目录后退出。★ 这条路不经过工程的 render.py，"
                         "所以**任意 .tpac** 都能出图（工程的 render.py 只认它自己的"
                         "材质命名，导入的网格会被它全部过滤掉）")
    ap.add_argument("--shot-char", type=int, default=0)
    ap.add_argument("--shot-anim", type=int, default=0)
    ap.add_argument("--shot-frame", type=int, default=0)
    return ap


def main():
    ap = build_argparser()
    a = ap.parse_args()

    # ---- 定位数据 ----
    texmap = None
    drop_mats = set()
    if a.pack:
        _LAST_DIR[:] = [str(Path(a.pack).parent)]
        workroot = a.work_root or (Path(a.pack).parent.parent / "preview_work")
        posed, texdir, skel = open_pack(a.pack, workroot, a.mbtool)
        a.posed_dir = str(posed)
        a.tex_dir = a.tex_dir or str(texdir)
        texmap = load_texmap(posed)
        a.skeleton = a.skeleton or str(skel)
    elif a.project:
        proj = Path(a.project)
        imported = proj / "work" / "imported"
        has_imported = ((imported / "texmap.json").exists()
                        and any(imported.glob("*.npz")))
        use_packed = (a.source in ("auto", "packed")) and has_imported
        if use_packed:
            # ★ 默认优先**从最终 .tpac 读回**的产物：贴图映射精确，
            #   而且预览的是真正交出去的那个文件（中间产物可能已经过时）。
            a.posed_dir = a.posed_dir or str(imported)
            a.tex_dir = a.tex_dir or str(imported / "tex_png")
            texmap = load_texmap(imported)
            print(f"[gui] 数据源 = work/imported（从 pack0.tpac 读回；"
                  f"想用中间产物加 --source posed）")
        else:
            a.posed_dir = a.posed_dir or str(proj / "work" / "posed")
            proj_tex = proj / "build" / "tex_png"
            a.tex_dir = a.tex_dir or str(proj_tex)
            a.skeleton = a.skeleton or str(proj / "work" / "bl_skeleton.json")
            import project_map
            drop_mats = project_map.load_project_drop_mats(proj)
            texmap = project_map.load_project_texmap(proj, proj_tex)
            if texmap is None:
                print("[gui] !! 找不到工程的材质→贴图映射，"
                      "贴图只能靠名字猜（可能对不上）")

    if not a.skeleton:
        if a.skeleton is None and a.project:
            a.skeleton = str(Path(a.project) / "work" / "bl_skeleton.json")

    if a.drop_mats:
        drop_mats |= {x.strip() for x in a.drop_mats.split(",") if x.strip()}

    if not a.posed_dir:
        raise SystemExit("要指定数据来源：--project <工程目录> / --pack <tpac> / --posed-dir ...")
    if not a.skeleton:
        if DEFAULT_SKELETON.exists():
            a.skeleton = str(DEFAULT_SKELETON)
            print(f"[gui] 骨架缺省用 {DEFAULT_SKELETON.name}")
        else:
            raise SystemExit("要指定 --skeleton <bl_skeleton.json>")
    if texmap is None and a.texmap:
        texmap = load_texmap(Path(a.texmap).parent)
    if texmap is None and a.posed_dir:
        texmap = load_texmap(Path(a.posed_dir))
    # `--posed-dir <proj>/work/posed` 也要能拿到工程的材质映射与 DROP_MATS ——
    # 只靠 texmap.json 的话，工程中间产物的源材质名一个都对不上，
    # 37 个组会全落到"按名字猜贴图"。
    if a.posed_dir:
        _pd = Path(a.posed_dir)
        if _pd.name == "posed" and _pd.parent.name == "work" and (_pd.parent.parent / "pipeline").exists():
            import project_map
            _proj = _pd.parent.parent
            if not drop_mats:
                drop_mats = project_map.load_project_drop_mats(_proj)
            if not texmap:
                texmap = project_map.load_project_texmap(_proj, a.tex_dir) or {}
    if texmap is None:
        texmap = {}
    if a.tex_dir:
        texmap.setdefault("__dir__", a.tex_dir)

    # ---- 动画清单 ----
    anims = []
    for spec in (a.anim or []):
        if "=" not in spec:
            raise SystemExit(f"--anim 要写成 name=path.json，收到 {spec!r}")
        n, p = spec.split("=", 1)
        anims.append((n.strip(), p.strip()))
    if a.anim_dir:
        for p in sorted(_glob.glob(os.path.join(a.anim_dir, "*.json"))):
            b = os.path.basename(p)
            if b in ("index.json",):
                continue
            anims.append((os.path.splitext(b)[0], p))
    if not anims:
        raise SystemExit("没有动画：用 --anim name=path.json 或 --anim-dir <目录>")

    # ---- 动画时长索引（clip 的真实时长） ----
    idx_path = a.anim_index
    if idx_path is None and a.anim_dir:
        cand = Path(a.anim_dir) / "index.json"
        if cand.exists():
            idx_path = str(cand)
    anim_index = {}
    if idx_path and Path(idx_path).exists():
        try:
            anim_index = json.loads(Path(idx_path).read_text(encoding="utf-8"))
            print(f"[gui] 动画时长索引 {Path(idx_path).name}：{len(anim_index)} 条")
        except Exception as e:
            print(f"[gui] 索引读取失败 {type(e).__name__}: {e}")

    print(f"[gui] posed={a.posed_dir}")
    print(f"[gui] anims={[n for n, _ in anims]}  nframes={a.nframes}")

    data = DataSet(a.posed_dir, a.skeleton, anims, texmap, a.nframes, a.start,
                   anim_index, a.cache_slots, drop_mats=drop_mats,
                   max_seconds=a.seconds, min_fps=a.min_fps)
    if drop_mats:
        print(f"[gui] 跳过材质：{sorted(drop_mats)}")
    for ch in data.chars:
        m = data.mesh(ch)
        print(f"[gui] 角色 {ch}: {len(m['verts'])} 顶点, {len(m['faces'])//3} 三角, "
              f"{len(m['materials'])} 材质组")
    chars = ([c.strip() for c in a.chars.split(",")] if a.chars else data.chars)
    data.chars = [c for c in chars if c in data.chars] or data.chars
    print(f"[gui] 可切换角色：{data.chars}")

    if a.selftest:
        print("[gui] selftest：数据、骨架、动画帧都可加载")
        for i, (n, _) in enumerate(anims):
            meta = data.anim_meta(i)
            fr = data.frames(data.chars[0], i)
            P = fr["pos"]
            # ★ 必须带 axis=2：不带的话 np.linalg.norm 会返回**整个数组的标量范数**
            #   （那样打印出来是几十米的假数字，看着像模型炸了，其实只是统计写错）
            drift = np.linalg.norm(P - data.mesh(data.chars[0])["verts"], axis=2)
            print(f"   {n}: {P.shape[0]} 帧, z[{P[:, :, 2].min():+.3f},{P[:, :, 2].max():+.3f}], "
                  f"位移 中位{np.median(drift)*1000:.1f}mm p99={np.percentile(drift, 99)*1000:.1f}mm "
                  f"max={drift.max()*1000:.1f}mm"
                  + (f", clip {meta['seconds']:.2f}s ({meta['fps']:.1f} t/s)"
                     if meta.get("seconds") else ""))
        return 0

    import pyglet
    from pyglet.window import key
    win = pyglet.window.Window(1100, 800, caption="mb-preview — Bannerlord 皮套动画预览",
                               vsync=not a.no_vsync)
    if a.alpha_test is not None:
        globals()["ALPHA_TEST_OVERRIDE"] = float(a.alpha_test)
        print(f"[gui] alphaTest 阈值被覆盖为 {a.alpha_test}（0 = 不剪）")
    import anim_pose as _AP
    if getattr(a, "no_compose_q", False):
        _AP.COMPOSE_LOCAL_Q = False
        print("[gui] 按旧行为：把 q 当世界朝向（--no-compose-q）")
    v = Viewer(data, a, a.tex_dir, window=win)
    v.show_bones = bool(getattr(a, "bones", False))
    v.cur = 0
    v.load_textures()
    v.upload_dynamic()

    import mbui          # 按钮/滑块层（只 import pyglet.gl / graphics，不会开窗）

    label = pyglet.text.Label("", font_name=mbui.FONT, font_size=10,
                              x=8, y=win.height - 16, color=(230, 230, 235, 255))

    # ---------------- 按钮/滑块层 ----------------
    #  给人用的入口：不用记快捷键。键盘操作全部保留（见 on_key_press）。
    def _step_frame(d):
        v.playing = False
        v.last = 0.0
        v._cur = (v.cur + d) % v.frames["pos"].shape[0]
        v.upload_dynamic()
        win.invalid = True

    def _toggle_play():
        v.playing = not v.playing
        v.last = 0.0

    def _reset_view():
        v.rot = [0.0, 0.0]
        v.dist = 3.4
        win.invalid = True

    def _toggle_bones():
        v.show_bones = not v.show_bones
        print(f"[gui] 骨骼显示 {'开' if v.show_bones else '关'}")
        win.invalid = True

    def _toggle_tex():
        v.show_tex = not v.show_tex
        print(f"[gui] 贴图 {'开' if v.show_tex else '关（看几何）'}")
        win.invalid = True

    def _set_view(name):
        yaw, pitch = mbui.VIEWS[name]
        v.rot = [yaw, pitch]
        v.dist = 3.4
        win.invalid = True

    def _shot_gui():
        out = f"shot_{v.char}_{v.frames['name']}_f{v.cur:03d}.png"
        try:
            pyglet.image.get_buffer_manager().get_color_buffer().save(out)
            print(f"[gui] 截图 -> {out}")
        except Exception as e:
            print(f"[gui] 截图失败 {type(e).__name__}: {e}")

    def _record_gui():
        """把整段动画录成 PNG 序列 + GIF（与 --record 同一条路，任意 mod 可用）。"""
        from PIL import Image
        from pyglet.gl import glFinish
        fr = v.frames
        outdir = Path(f"record_{v.char}_{fr['name']}")
        outdir.mkdir(parents=True, exist_ok=True)
        n = fr["pos"].shape[0]
        sec = fr.get("seconds_covered") or fr["meta"].get("seconds")
        delay = max(20, int(round(sec / n * 1000))) if sec else 100
        ui.enabled = False                 # 录制期间不画 UI，出图干净
        was = v.playing
        v.playing = False
        print(f"[gui] 录制 {v.char}/{fr['name']} {n} 帧 -> {outdir} …")
        imgs = []
        for i in range(n):
            v._cur = i
            v.upload_dynamic()
            v.draw(win.width, win.height)
            glFinish()
            png = outdir / f"f{i:03d}_{v.char}.png"
            pyglet.image.get_buffer_manager().get_color_buffer().save(str(png))
            imgs.append(Image.open(png).convert("RGB"))
        gif = outdir / f"_{v.char}_{fr['name']}.gif"
        imgs[0].save(gif, save_all=True, append_images=imgs[1:],
                     duration=delay, loop=0, optimize=True)
        w0, h0 = imgs[0].size
        cols = min(n, 4)
        rows = (n + cols - 1) // cols
        sheet = Image.new("RGB", (w0 * cols, h0 * rows), (20, 22, 26))
        for c, im in enumerate(imgs):
            sheet.paste(im, ((c % cols) * w0, (c // cols) * h0))
        sheet.save(outdir / f"_{v.char}_{fr['name']}_sequence.png")
        ui.enabled = True
        ui.refresh()
        v.playing = was
        print(f"[gui] 录制完成 -> {outdir}")

    def _ui_specs():
        """按钮清单。每次重建，所以文案/高亮跟着状态走。"""
        # ★ "打开 mod…" 放在**最左**并用强调色：文件操作放左首符合习惯，
        #   早先它排在 19 个按钮的最后，用户根本找不到入口。
        sp = [mbui.Button("打开 mod…", lambda: pick_mod(v, a), accent=True,
                          tip="选一个 .tpac 打开（快捷键 M）；按住 Shift 点 = 选工程目录"),
              mbui.Button("上一角色", lambda: v.switch_char(-1), tip="上一个角色（Tab）"),
              mbui.Button(v.char, None, active=True, tip="当前角色"),
              mbui.Button("下一角色", lambda: v.switch_char(1), tip="下一个角色（Tab）"),
              mbui.Button("上一帧", lambda: _step_frame(-1), tip="上一帧（,）"),
              mbui.Button("暂停" if v.playing else "播放", _toggle_play,
                          active=v.playing, tip="播放 / 暂停（空格）"),
              mbui.Button("下一帧", lambda: _step_frame(1), tip="下一帧（.）")]
        for i, (nm, _p) in enumerate(v.data.anims):
            sp.append(mbui.Button(anim_label(nm),
                                  (lambda k: (lambda: v.switch_anim(k)))(i),
                                  active=(i == v.ai),
                                  tip=f"{nm}（快捷键 {i+1}）"))
        for key, label in (("front", "正面"), ("3/4", "斜 3/4"),
                           ("side", "侧面"), ("back", "背面")):
            sp.append(mbui.Button(label, (lambda k: (lambda: _set_view(k)))(key),
                                  tip=f"视角：{label}"))
        sp.append(mbui.Button("贴图", _toggle_tex, active=v.show_tex,
                              tip="贴图开关（T）—— 关掉只看几何"))
        sp.append(mbui.Button("骨骼", _toggle_bones, active=v.show_bones,
                              tip="叠加显示骨架（B）—— 关节是亮点、骨链是橙线"))
        sp.append(mbui.Button("复位", _reset_view, tip="复位视角（R）"))
        sp.append(mbui.Button("截图", _shot_gui, tip="存一张当前帧（S）"))
        sp.append(mbui.Button("录制", _record_gui,
                              tip="把整段录成 PNG 序列 + GIF（任意 mod 都能录）"))
        return sp

    def _ui_seek(frac):
        fr = v.frames
        n = fr["pos"].shape[0]
        v.playing = False
        v._cur = min(n - 1, max(0, int(round(frac * (n - 1)))))
        v.upload_dynamic()
        win.invalid = True

    ui = mbui.UiBar(win, on_seek=_ui_seek, tooltip_getter=lambda: v.hud_text())
    ui.buttons = _ui_specs()
    _uisig = [None]
    tip_label = pyglet.text.Label("", font_name=mbui.FONT, font_size=10,
                                  x=10, y=60, color=(190, 196, 206, 255))

    stats = {"draw": 0, "tick": 0, "upload_ms": 0.0, "upload_n": 0,
             "start": time.time(), "draw_ms": 0.0}
    if a.run_seconds:
        v.stats = stats

    @win.event
    def on_draw():
        if stats["draw"] < 3:
            print(f"[dbg] on_draw #{stats['draw']+1} "
                  f"t={time.time()-stats['start']:.2f}s", flush=True)
        _d0 = time.time()
        v.draw(win.width, win.height)
        stats["draw"] += 1
        stats["draw_ms"] += (time.time() - _d0) * 1000.0
        if a.run_seconds and time.time() - stats["start"] > a.run_seconds:
            el = time.time() - stats["start"]
            print(f"\n[profile] 跑了 {el:.1f}s：draw {stats['draw']} 次"
                  f"（{stats['draw']/el:.1f} fps 实际重绘，"
                  f"平均 {stats['draw_ms']/max(1,stats['draw']):.2f}ms/帧）")
            print(f"[profile] tick {stats['tick']} 次；"
                  f"upload {stats['upload_n']} 次，"
                  f"平均 {stats['upload_ms']/max(1,stats['upload_n']):.2f}ms"
                  f"（合计 {stats['upload_ms']/1000:.2f}s = "
                  f"{stats['upload_ms']/el/10:.1f}% 的时间）")
            print(f"[profile] 当前停在 {v.frames['name']} 的第 {v.cur + 1}"
                  f"/{v.frames['pos'].shape[0]} 帧（帧号在动 = 播放正常）")
            pyglet.app.exit()
        label.text = v.hud_text()
        label.y = win.height - 16

        # 按钮的文案/高亮跟着状态走，但**别每帧重建对象**（60fps 下会成为垃圾场）
        sig = (v.char, v.ai, v.playing, v.show_tex, v.show_bones, v.ui_epoch)
        if sig != _uisig[0]:
            _uisig[0] = sig
            ui.buttons = _ui_specs()
            ui.refresh()
        n = v.frames["pos"].shape[0]
        if ui.track is None:            # 首帧还没 layout 过
            ui.layout(win.width, win.height)
        tip_label.text = ui.tooltip or ""
        tip_label.y = ui.track[1] + ui.track[3] + 10
        # HUD 与 tooltip 都交给 UI 层在正交投影里画（见 UiBar.draw 的说明）
        ui.draw(win.width, win.height, progress=(v.cur / max(1, n - 1)),
                overlay=(label, tip_label))

    @win.event
    def on_mouse_press(x, y, button, mod):
        if ui.on_mouse_press(x, y, button, mod):
            win.invalid = True
            return True

    @win.event
    def on_mouse_release(x, y, button, mod):
        if ui.on_mouse_release(x, y, button, mod):
            win.invalid = True       # 按钮回调可能改了状态，必须请求重绘
            return True

    @win.event
    def on_mouse_motion(x, y, dx, dy):
        if ui.on_mouse_motion(x, y, dx, dy):
            win.invalid = True

    @win.event
    def on_mouse_drag(x, y, dx, dy, buttons, mod):
        # 先让 UI 处理（拖时间轴）；没命中才旋转模型
        if ui.on_mouse_drag(x, y, dx, dy, buttons, mod):
            win.invalid = True
            return
        # 拖动方向（按使用习惯翻过一次）：
        #   向右拖 -> 视角绕模型向右走（模型看起来向右转），上下同理。
        #   相机位置是 [sin(yaw), cos(yaw), sin(pitch)]，所以 yaw 加、pitch 减
        #   才是这个手感；早先是减/加，正好是反的。
        #   习惯相反的话把这两行的符号换回来即可。
        v.rot[0] += dx * 0.01
        v.rot[1] = max(-1.4, min(1.4, v.rot[1] - dy * 0.01))

    @win.event
    def on_mouse_scroll(x, y, sx, sy):
        v.dist = max(1.0, min(12.0, v.dist * (0.9 if sy > 0 else 1.1)))

    @win.event
    def on_key_press(sym, mod):
        if sym == key.SPACE:
            v.playing = not v.playing
            v.last = 0.0               # 累积器，不是墙上时间（见 Viewer.__init__）
        elif sym == key.TAB:
            v.switch_char(-1 if (mod & key.MOD_SHIFT) else 1)
        elif sym == key.R:
            v.rot = [0.35, 0.0]; v.dist = 3.4
        elif sym == key.T:
            v.show_tex = not v.show_tex
            print(f"[gui] 贴图 {'开' if v.show_tex else '关（看几何）'}")
        elif sym == key.B:
            _toggle_bones()
        elif sym == key.M:
            pick_mod(v, a, want_dir=bool(mod & key.MOD_SHIFT))
        elif sym in (key.COMMA, key.LEFT):
            v.playing = False
            v._cur = (v.cur - 1) % v.frames["pos"].shape[0]
            v.upload_dynamic()
        elif sym in (key.PERIOD, key.RIGHT):
            v.playing = False
            v._cur = (v.cur + 1) % v.frames["pos"].shape[0]
            v.upload_dynamic()
        elif sym == key.S:
            out = f"shot_{v.char}_{v.frames['name']}_f{v.cur:03d}.png"
            try:
                pyglet.image.get_buffer_manager().get_color_buffer().save(out)
                print(f"[gui] 截图 -> {out}")
            except Exception as e:
                print(f"[gui] 截图失败 {type(e).__name__}: {e}")
        elif key._1 <= sym <= key._9:
            v.switch_anim(sym - key._1)
        elif sym == key.ESCAPE:
            win.close()

    if a.record:
        from PIL import Image
        from pyglet.gl import glFinish
        v.ci = max(0, min(a.shot_char, len(data.chars) - 1))
        v._build_groups(); v.load_textures()
        v.ai = max(0, min(a.shot_anim, len(anims) - 1))
        fr = v.frames
        v.playing = False
        outdir = Path(a.record)
        outdir.mkdir(parents=True, exist_ok=True)
        n = fr["pos"].shape[0]
        sec = fr.get("seconds_covered") or fr["meta"].get("seconds")
        delay = max(20, int(round(sec / n * 1000))) if sec else 100
        print(f"[gui] 录制 {v.char}/{fr['name']}：{n} 帧 -> {outdir}"
              + (f"（{sec:.2f}s，帧延时 {delay}ms ≈ {1000.0/delay:.1f} fps 等效）"
                 if sec else ""))
        win.switch_to()
        imgs = []
        for i in range(n):
            v._cur = i
            v.upload_dynamic()
            v.draw(win.width, win.height)
            glFinish()
            png = outdir / f"f{i:03d}_{v.char}.png"
            pyglet.image.get_buffer_manager().get_color_buffer().save(str(png))
            imgs.append(Image.open(png).convert("RGB"))
        gif = outdir / f"_{v.char}_{fr['name']}.gif"
        imgs[0].save(gif, save_all=True, append_images=imgs[1:],
                     duration=delay, loop=0, optimize=True)
        w, h = imgs[0].size
        cols = min(n, 6)
        rows = (n + cols - 1) // cols
        sheet = Image.new("RGB", (w * cols, h * rows), (20, 22, 26))
        for c, im in enumerate(imgs):
            sheet.paste(im, ((c % cols) * w, (c // cols) * h))
        seq = outdir / f"_{v.char}_{fr['name']}_sequence.png"
        sheet.save(seq)
        print(f"[gui] {gif.name} / {seq.name} / {n} 张 PNG -> {outdir}")
        return 0

    if a.shot:
        v.ci = max(0, min(a.shot_char, len(data.chars) - 1))
        v._build_groups(); v.load_textures()
        v.ai = max(0, min(a.shot_anim, len(anims) - 1))
        fr = v.frames
        v._cur = max(0, min(a.shot_frame, fr["pos"].shape[0] - 1))
        v.playing = False
        v.upload_dynamic()

        done = {"n": 0}

        @win.event
        def on_draw_shot():
            on_draw()
            done["n"] += 1
            if done["n"] >= 2:
                pyglet.image.get_buffer_manager().get_color_buffer().save(a.shot)
                print(f"[gui] shot -> {a.shot}  ({v.hud_text()})")
                pyglet.app.exit()

        win.remove_handler("on_draw", on_draw)
        win.push_handlers(on_draw=on_draw_shot)
        pyglet.clock.schedule_interval(lambda dt: None, 1 / 60.0)
        pyglet.app.run()
        return 0

    print("[gui] 操作：拖拽旋转 · 滚轮缩放 · Tab 换角色 · 1..9 切动画 · "
          "空格暂停 · ,/. 单帧 · T 贴图开关 · M 选 mod · Shift+M 选工程 · "
          "R 复位 · S 截图 · ESC 退出")
    pyglet.clock.schedule_interval(v.tick, 1 / 120.0)
    pyglet.app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())