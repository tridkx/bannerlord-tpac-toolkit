# -*- coding: utf-8 -*-
"""import_mod —— 把 `mbtool exportmod` 掏出来的东西组装成**离线预览器能直接吃的格式**。

它在整条链里的位置
------------------
    pack0.tpac ──mbtool exportmod──> geo/*.bin + tex/*.bin + pack.json
                                          │
                                    import_mod.py          ← 本脚本
                                          │
                     <out>/<char>.npz  +  <png>/<tex>.png  +  texmap.json
                                          │
                        mbpreview_gui.py / mb-preview.py / render.py

为什么要有这一步（而不是直接用 work/posed/*.npz）
-------------------------------------------------
`work/posed/*.npz` 是**中间产物**，离线全绿也可能进游戏少一半衣服
（`.mgeo` 同名覆盖、权重没量化成 0..255 这两个坑都是这么来的）。
从**最终交付的 .tpac** 读回来预览，验证的才是真正交出去的那个文件。
另外它让预览器不再依赖某个具体工程的目录结构 —— 别人的 mod 也能直接打开。

贴图
----
tpac 里存的是 BC 压缩的原始字节，解码用 `py/bcencode.py`（已实测的 BC1/3/4/5 解码器）。
解出来的 PNG **行序与打包前的 tex_png 一致**（编码时是按 PNG 行序写块的，这里原路反解）。
UV 也原样搬运，不做任何翻转 —— 翻转是渲染侧的约定，不属于导入的职责。

用法
----
  python import_mod.py --export <exportmod 目录> --out <输出目录> [选项]

  --only GLOB        只导入名字匹配的 metamesh（可重复）
  --group A=B        把 metamesh 名字匹配 A（glob）的合成角色 B（可重复）
  --part-words W,W   判定"部件后缀"的词表（默认 body,head,feet,... 见 PART_WORDS）
  --tex-out DIR      贴图 PNG 输出目录（默认 <out>/../tex_png）
  --no-tex           跳过贴图解码
  --check NPZ        与参考 npz 比对顶点（验证"从 tpac 读回"是否忠实）
"""
import argparse
import fnmatch
import json
import os
import struct
import sys
from pathlib import Path

import numpy as np

# ★ Windows 控制台默认 GBK：本脚本 print 中文，不钉死编码会 UnicodeEncodeError。
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "py"))

GEO_MAGIC = 0x424D4447

# 判定 metamesh 名的"部件后缀"—— `xj7_yue_body` / `xj7_yue_head` 属于同一个角色。
PART_WORDS = ["body", "head", "feet", "foot", "legs", "leg", "hands", "hand",
              "hair", "face", "armor", "cloth", "cape", "boots", "boot"]


# --------------------------------------------------------------------------
# geo bin
# --------------------------------------------------------------------------
class Reader:
    def __init__(self, data: bytes):
        self.d = data
        self.o = 0

    def u32(self):
        v = struct.unpack_from("<I", self.d, self.o)[0]
        self.o += 4
        return v

    def i32(self):
        v = struct.unpack_from("<i", self.d, self.o)[0]
        self.o += 4
        return v

    def f32(self, n):
        v = np.frombuffer(self.d, dtype="<f4", count=n, offset=self.o)
        self.o += 4 * n
        return np.array(v, dtype=np.float64)

    def u8(self, n):
        v = np.frombuffer(self.d, dtype=np.uint8, count=n, offset=self.o)
        self.o += n
        return np.array(v)

    def u32arr(self, n):
        v = np.frombuffer(self.d, dtype="<u4", count=n, offset=self.o)
        self.o += 4 * n
        return np.array(v, dtype=np.int64)

    def ustr(self):
        n = self.u32()
        s = self.d[self.o:self.o + n].decode("utf-8", "replace")
        self.o += n
        return s


def read_geo(path):
    r = Reader(Path(path).read_bytes())
    magic = r.u32()
    if magic != GEO_MAGIC:
        raise ValueError(f"{path}: 不是 exportmod 的几何文件（magic={magic:#x}）")
    ver = r.u32()
    if ver != 1:
        raise ValueError(f"{path}: 几何格式版本 {ver} 不认识（本脚本支持 1）")
    nsub = r.u32()
    subs = []
    for _ in range(nsub):
        s = {"name": r.ustr(), "lod": r.i32(), "material": r.ustr(), "materialGuid": r.ustr()}
        n, ni = r.u32(), r.u32()
        s["nverts"], s["nidx"] = n, ni
        s["bboxMin"] = r.f32(3).tolist()
        s["bboxMax"] = r.f32(3).tolist()
        f = r.u32()
        pos = r.f32(n * 3).reshape(n, 3)
        nrm = r.f32(n * 3).reshape(n, 3) if (f & 1) else None
        uv = r.f32(n * 2).reshape(n, 2)
        uv2 = r.f32(n * 2).reshape(n, 2) if (f & 2) else None
        col1 = r.u8(n * 4).reshape(n, 4) if (f & 4) else None
        col2 = r.u8(n * 4).reshape(n, 4) if (f & 8) else None
        tan = r.f32(n * 4).reshape(n, 4) if (f & 16) else None
        bi = r.u8(n * 4).reshape(n, 4) if (f & 32) else None
        bw = r.u8(n * 4).reshape(n, 4)          # 权重没有 flag 保护：总是写
        idx = r.u32arr(ni)
        s.update(pos=pos, nrm=nrm, uv=uv, uv2=uv2, col1=col1, col2=col2,
                 tan=tan, bi=bi, bw=bw, idx=idx, flags=f)
        subs.append(s)
    return subs


# --------------------------------------------------------------------------
# 分组：哪些 metamesh 拼成一个角色
# --------------------------------------------------------------------------
def strip_part(name, part_words):
    """`xj7_yue_body` -> `xj7_yue`；没有可识别的部件后缀就返回原名。"""
    low = name.lower()
    for w in part_words:
        for sep in ("_", "-", "."):
            if low.endswith(sep + w):
                return name[:-(len(w) + 1)]
    return name


def longest_common_prefix(names):
    """按 `_` 分词求最长公共前缀（xj7_yue_body/head/feet -> xj7_yue）。"""
    parts = [n.split("_") for n in names]
    common = []
    for i in range(min(len(p) for p in parts)):
        w = parts[0][i]
        if all(p[i] == w for p in parts):
            common.append(w)
        else:
            break
    return "_".join(common)


def char_name(group, explicit, members):
    """组 -> 角色名。

    ★ 早先的兜底是 `group.rsplit("_",1)[-1]`（取最后一段），对 `xj7_yue_body`
      恰好凑出 `yue`，看起来很灵 —— 但 BL 资产里 `_a/_b/_c` 是最常见的后缀，
      于是 `wooden_platform_a` -> `a`、`mat_fur_b` -> `b`、`chicken_mesh` -> `mesh`，
      一堆互不相关的道具被塞进同一个 `a.npz`（实测 `_shared.tpac` 42 个 metamesh
      被并成 19 个假角色、`a.npz` 里 11 个无关道具）。
      现在：多件组用"成员名的公共前缀"，单件组用**完整名**。
    """
    if explicit and group in explicit:
        return explicit[group]
    if len(members) > 1:
        lcp = longest_common_prefix([m["name"] for m in members])
        if lcp:
            tail = lcp.rsplit("_", 1)[-1]
            return tail or lcp
    return members[0]["name"]


# --------------------------------------------------------------------------
# 贴图
# --------------------------------------------------------------------------
def decode_texture(entry, blob):
    """BC 字节 -> (H,W,C) uint8 或 (H,W,4)。返回 None 表示格式不支持。"""
    import bcencode as BC
    w, h = int(entry["width"]), int(entry["height"])
    fmt = entry["format"].upper()
    n = int(entry["mipSize"][0]) if entry.get("mipSize") else len(blob)

    if fmt == "DXT1":
        return BC.decode_bc1(blob[:n], w, h)
    if fmt in ("DXT5",):
        return BC.decode_bc3(blob[:n], w, h)
    if fmt in ("DXT3", "DXT2", "DXT4"):
        # DXT3/DXT2 的 alpha 是 4bit 显式；这里没有专用解码器，
        # 退化成 BC1 的 RGB + 全 255 alpha，并明确告知调用者。
        rgba = BC.decode_bc1(blob[:n], w, h)
        return rgba
    if fmt == "BC4":
        g = BC.decode_bc4(blob[:n], w, h)
        return np.stack([g, g, g, np.full_like(g, 255)], axis=2)
    if fmt == "BC5":
        rg = BC.decode_bc5(blob[:n], w, h)
        return np.concatenate([rg, np.zeros_like(rg[:, :, :1]),
                               np.full_like(rg[:, :, :1], 255)], axis=2)
    if fmt in ("B8G8R8A8_UNORM", "B8G8R8X8_UNORM"):
        a = np.frombuffer(blob[:w * h * 4], np.uint8).reshape(h, w, 4)
        return a[:, :, [2, 1, 0, 3]].copy()
    if fmt in ("R8G8B8A8_UNORM", "R8G8B8A8_UINT"):
        return np.frombuffer(blob[:w * h * 4], np.uint8).reshape(h, w, 4).copy()
    if fmt in ("R8_UNORM", "A8_UNORM", "L8_UNORM"):
        g = np.frombuffer(blob[:w * h], np.uint8).reshape(h, w)
        return np.stack([g, g, g, np.full_like(g, 255)], axis=2)
    return None


def import_textures(man, export_dir, tex_dir, verbose=True):
    """解出 PNG，返回 {贴图名: 相对 png 路径}。"""
    from PIL import Image
    tex_dir.mkdir(parents=True, exist_ok=True)
    out = {}
    written = set()
    ok = skipped = failed = 0
    for t in man["textures"]:
        rel = t.get("file")
        if not rel:
            failed += 1
            continue
        blob = (export_dir / rel).read_bytes()
        arr = decode_texture(t, blob)
        if arr is None:
            skipped += 1
            if verbose:
                print(f"  [tex] {t['name']}: 格式 {t['format']} 暂不支持解码，跳过")
            continue
        # ★ 用**导出侧已经唯一化**的文件名（tex/Gen_Hair_N_1.bin -> Gen_Hair_N_1.png）。
        #   按原始贴图名命名会让同名不同 GUID 的资产（实测 LVBU 里有 4 张
        #   不同 GUID 的 Gen_Hair_N）互相覆盖：日志说解出 192 张、磁盘只有 188 个。
        stem = Path(rel).stem
        p = tex_dir / (stem + ".png")
        try:
            Image.fromarray(arr).save(p)
            out.setdefault(t["name"], p.name)
            if p.name not in written:
                written.add(p.name)
                ok += 1
        except Exception as e:
            failed += 1
            if verbose:
                print(f"  [tex] {t['name']}: 写 PNG 失败 {type(e).__name__}: {e}")
    if verbose:
        print(f"  贴图：解出 {ok} 张（按唯一文件名计），格式不支持 {skipped}，"
              f"无数据/失败 {failed}")
        if skipped:
            print(f"        ⚠ 有 {skipped} 张因格式不支持被跳过（BC7/BC6H 等）——"
                  "用到它们的材质会退回「按名字猜贴图」")
    return out


def build_texmap(man, tex_files):
    """材质名 -> {槽位: png 名}（texmap.json 的 __materials__ 段）。"""
    out = {}
    for m in man["materials"]:
        slots = {}
        for k, tn in (m.get("textures") or {}).items():
            if tn in tex_files:
                slots[k] = tex_files[tn]
        if slots:
            out[m["name"]] = slots
    return out


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--export", required=True, help="mbtool exportmod 的输出目录")
    ap.add_argument("--out", required=True, help="输出目录（写 <char>.npz / texmap.json）")
    ap.add_argument("--only", action="append", default=None, help="只导入匹配的 metamesh（glob）")
    ap.add_argument("--group", action="append", default=None, help="metamesh_glob=角色名")
    ap.add_argument("--tex-out", default=None)
    ap.add_argument("--no-tex", action="store_true")
    ap.add_argument("--check", default=None, help="参考 npz，比对顶点以验证 "
                                                 "'从最终 tpac 读回'是否忠实")
    a = ap.parse_args()

    export_dir = Path(a.export)
    out_dir = Path(a.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    tex_dir = Path(a.tex_out) if a.tex_out else (out_dir.parent / "tex_png")

    man = json.loads((export_dir / "pack.json").read_text(encoding="utf-8"))
    print(f"[import] {man['pack']}")
    print(f"         包 guid {man['packGuid']}  lod={man['lodUsed']}  "
          f"统计 {man['stats']}")

    explicit = {}
    group_globs = []
    for g in (a.group or []):
        if "=" not in g:
            raise SystemExit(f"--group 要写成 metamesh_glob=角色名，收到 {g!r}")
        gl, nm = g.split("=", 1)
        group_globs.append((gl.strip(), nm.strip()))

    # ---- 收集要导入的 metamesh ----
    picked = []
    for m in man["meshes"]:
        if not m.get("submeshes"):
            continue
        if a.only and not any(fnmatch.fnmatch(m["name"], g) for g in a.only):
            continue
        picked.append(m)
    if not picked:
        raise SystemExit("没有匹配的 metamesh —— 用 --only 换个匹配、或看 pack.json 里的 meshes")

    # ---- 分组 ----
    groups = {}
    for m in picked:
        gname = None
        for gl, nm in group_globs:
            if fnmatch.fnmatch(m["name"], gl):
                gname = nm
                break
        if gname is None:
            gname = strip_part(m["name"], PART_WORDS)   # 先按"部件后缀"归组
        groups.setdefault(gname, []).append(m)

    # 组名 -> 最终角色名（此时才知道组里有几个成员）
    groups = {char_name(g, explicit, ms): ms for g, ms in groups.items()}

    # 分组完全没起作用（名字里没有可识别的部件后缀，比如全拼音命名或道具包）
    # ⇒ 硬分成几十个碎片毫无意义，索性合成一个角色
    if len(groups) > max(2, int(len(picked) * 0.6)):
        packname = Path(man["pack"]).stem or "pack"
        print(f"[import] 名字里没有可识别的部件后缀（{len(picked)} 个 metamesh "
              f"-> {len(groups)} 组），改为全部合成一个角色 '{packname}'")
        groups = {packname: picked}

    print(f"[import] 分成 {len(groups)} 个角色：" +
          "，".join(f"{k}({len(v)} mesh)" for k, v in groups.items())[:300])

    # ---- 贴图 ----
    tex_files = {}
    if not a.no_tex:
        tex_files = import_textures(man, export_dir, tex_dir)

    # ---- 每个角色合成一个 npz ----
    mats_by_name = {m["name"]: m for m in man["materials"]}
    all_texmap = {}          # ★ 键是**子网格组名**（预览器就是按组查贴图的）
    for gname, meshes in groups.items():
        V, N, UV, BI, BW = [], [], [], [], []
        F, FG = [], []
        group_names, materials = [], []
        voff = 0
        warn = []

        for m in meshes:
            subs = read_geo(export_dir / m["file"])
            for s in subs:
                n = s["nverts"]
                V.append(s["pos"])
                N.append(s["nrm"] if s["nrm"] is not None else np.zeros((n, 3)))
                UV.append(s["uv"])
                if s["bi"] is None:
                    warn.append(f"{s['name']} 没有骨骼索引 —— 预览时不会跟骨骼动")
                    BI.append(np.zeros((n, 4), np.uint8))
                    BW.append(np.zeros((n, 4), np.uint8))
                else:
                    bi_, bw_ = s["bi"], s["bw"]
                    # ★ 满长度全 0 的权重（原生静态件常见）不能原样透传：
                    #   LBS 里 `out = zeros` + `sel = w>0`，全 0 的顶点永远不被累加
                    #   ⇒ 直接停在原点。实测恒等姿势下最大偏移 **15 米**。
                    #   按 skill §7 的做法统一绑到单骨（pelvis=0）。
                    zero = bw_.sum(1) == 0
                    if zero.any():
                        bi_ = bi_.copy(); bw_ = bw_.copy()
                        bi_[zero] = 0
                        bw_[zero] = 0
                        bw_[zero, 0] = 255
                        if verbose:
                            print(f"       ! {s['name']}: {int(zero.sum())} 个顶点权重全 0，"
                                  f"已统一绑到 pelvis(0)")
                    BI.append(bi_)
                    BW.append(bw_)

                tri = s["idx"].reshape(-1, 3)
                F.append(tri + voff)
                gi = len(group_names)
                FG.append(np.full(len(tri), gi, np.int64))
                group_names.append(s["name"])
                materials.append(s["material"])
                if s["material"] in mats_by_name:
                    # 连渲染状态一起带上：预览器要用 alphaTest 剪镂空件
                    # （头发/睫毛/眉毛），否则发片会显示成一整块实心色。
                    mm = mats_by_name[s["material"]]
                    all_texmap[s["name"]] = {
                        "material": s["material"],
                        "slots": dict(mm.get("textures") or {}),
                        "alphaTest": mm.get("alphaTest"),
                        "blendMode": mm.get("blendMode"),
                        "flags": mm.get("flags") or [],
                        "shaderMatFlags": mm.get("shaderMatFlags") or [],
                    }
                voff += n

        verts = np.concatenate(V).astype(np.float32)
        normals = np.concatenate(N).astype(np.float32)
        uv = np.concatenate(UV).astype(np.float32)
        # ★ faces 必须是 (M,3) 二维：工程里的 render.py 按这个形状校验
        #   （展平成一维会被它判成"形状不对"直接拒渲）。
        faces = np.concatenate(F).astype(np.int64)
        face_group = np.concatenate(FG).astype(np.int64)
        bone_idx = np.concatenate(BI).astype(np.int64)
        bone_wt = np.concatenate(BW).astype(np.float64) / 255.0

        # ★ 从最终产物倒推的自检（skill §10.8）：权重量化没做对时，
        #   绝大多数顶点会是全零权重向量 ⇒ 实机"整块模型跟着骨盆一起摇晃"。
        wsum = np.concatenate(BW).astype(np.int32).sum(1)
        exact = float((np.abs(wsum - 255) <= 1).mean())
        nz = float((wsum > 0).mean())
        bi_max = int(bone_idx.max()) if bone_idx.size else -1
        nz_idx = bone_idx[bone_idx > 0].max() if (bone_idx > 0).any() else 0

        print(f"\n[char] {gname}: {len(verts)} 顶点, {len(faces)//3} 三角, "
              f"{len(group_names)} 组")
        print(f"       权重和==255 占比 {exact*100:.2f}%  非零占比 {nz*100:.2f}%  "
              f"骨骼索引 max {bi_max}（非零 max {nz_idx}）")
        # ★ 这条 100% 判据只对**我们自己 builder 强制量化成 255** 的包成立；
        #   官方 kit 产的包会有量化抖动（实测 LVBU 92.5%）、原生静态件是全 0。
        #   所以它只作"提示"，不再断言"对应实机变刚体那个坑"（方向也不对：
        #   全 0 权重的真实后果是顶点塌到原点，见上面 pelvis 兜底）。
        if exact < 0.999:
            hi = float((np.abs(wsum - 255) <= 8).mean())
            print(f"       注意：权重和==255 占比 {exact*100:.2f}%（±8 内 {hi*100:.2f}%）。"
                  f"本工具链自己 build 的包应接近 100%；")
            print(f"             官方 kit / 原生资产的量化抖动属正常，不必当故障。")
        for w in dict.fromkeys(warn):
            print(f"       !! {w}")

        npz = out_dir / f"{gname}.npz"
        np.savez_compressed(npz, verts=verts, normals=normals, uv=uv,
                            faces=faces, face_group=face_group,
                            group_names=np.array(group_names, dtype=object),
                            materials=np.array(materials, dtype=object),
                            bone_idx=bone_idx,
                            bone_wt=bone_wt.astype(np.float32))
        bb = (verts.min(0), verts.max(0))
        print(f"       -> {npz}")
        print(f"       bbox x[{bb[0][0]:+.3f},{bb[1][0]:+.3f}] "
              f"y[{bb[0][1]:+.3f},{bb[1][1]:+.3f}] z[{bb[0][2]:+.3f},{bb[1][2]:+.3f}]")

        # ---- 与参考 npz 比对 ----
        if a.check:
            ref = np.load(a.check, allow_pickle=True)
            rv = np.asarray(ref["verts"], np.float64)
            print(f"       [check] 参考 {Path(a.check).name}: {len(rv)} 顶点 "
                  f"（本 {len(verts)}）")
            if len(rv) == len(verts):
                d = np.linalg.norm(rv - verts, axis=1)
                print(f"       [check] 顶点最大偏差 {d.max()*1000:.4f}mm，"
                      f"中位 {np.median(d)*1000:.4f}mm  ← 应≈0")
            else:
                print(f"       [check] 顶点数不同，跳过逐点比对（可能是导出范围不同）")

    print(f"\n[import] 完成 -> {out_dir}")
    if not a.no_tex:
        # ★ 键空间必须是**子网格组名**：预览器拿到的是 npz 里的 group_names
        #   （`xj7_yue_body.0` 这种），按组查才对得上。
        #   早先这里按"材质名"写，预览器按组名查全部落空 ⇒ 静默退回关键词猜测
        #   ⇒ 24 个组全被套上同一张 yue_cloth1_d.png（整模型发青）。
        #   __materials__ 留一份材质级索引作回退。
        doc = dict(all_texmap)
        doc["__materials__"] = build_texmap(man, tex_files)
        doc["__dir__"] = str(Path(tex_dir).resolve())   # 绝对路径：预览器可能在别的 cwd 启动
        (out_dir / "texmap.json").write_text(
            json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[import] texmap.json：{len(all_texmap)} 个组 -> {out_dir / 'texmap.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())