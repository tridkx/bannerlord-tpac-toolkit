# -*- coding: utf-8 -*-
"""对任意 .tpac 做一次"体检"，回答"这个包能不能正常预览、哪几项会退化"。

用法：
  python check_pack.py <mod>/AssetPackages/pack0.tpac [...]
  python check_pack.py --export <已导出的目录>          # 复用 exportmod 的产物
  python check_pack.py --scan <Modules 目录>            # 批量扫所有 mod

检查项都对应 preview/README.md §9 里踩过的坑，逐条给"会不会退化 + 影响多少"：
  1 镂空(alphaTest) 与 混合(blend) 共存的材质   -> 影响刘海类发片（已修，仅统计）
  2 two_sided 材质                              -> 双面光照（已修，仅统计）
  3 不支持的贴图格式（BC7/BC6H/DXT2/DXT3...）   -> 用到它的材质会退回"猜贴图"
  4 骨骼索引 > 27                               -> 不是 BL 27 骨，套 BL 动画会错位
  5 材质没有关联贴图                            -> 会退回按名字猜
  6 角色分组是否可识别（有无部件后缀）           -> 是否会被合成一个角色
"""
import sys, os, json, subprocess, argparse, tempfile, shutil
from pathlib import Path
from collections import Counter

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass

HERE = Path(__file__).resolve().parent
SUPPORTED_TEX = {"DXT1", "DXT5", "BC5", "BC4", "A8R8G8B8", "R8G8B8A8", "B8G8R8A8"}
KNOW_BAD_TEX = {"BC7", "BC6H", "DXT2", "DXT3", "DXT4", "BC6", "R16G16B16A16"}


def find_mbtool():
    """按候选列表探测 mbtool（不写死盘符，见 AGENTS.md 路径可移植性）。"""
    env = os.environ.get("MBTOOL")
    cands = []
    if env:
        cands.append(Path(env))
    root = HERE.parent
    for cfg in ("Release", "Debug"):
        cands.append(root / "mbtool" / "bin" / cfg / "net9.0" / "mbtool.exe")
        cands.append(root / "mbtool" / "bin" / cfg / "net9.0" / "mbtool")
    for c in cands:
        if c.exists():
            return c
    which = shutil.which("mbtool")
    return Path(which) if which else None


def export(tpac, outdir, mbtool):
    outdir = Path(outdir)
    r = subprocess.run([str(mbtool), "exportmod", str(tpac), str(outdir)],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    if r.returncode != 0:
        return None, (r.stdout or "") + (r.stderr or "")
    pj = outdir / "pack.json"
    return (json.loads(pj.read_text(encoding="utf-8")) if pj.exists() else None), ""


def check(pack, tpac_name):
    mats = pack.get("materials", []) or []
    texs = pack.get("textures", []) or []
    meshes = pack.get("meshes", []) or []
    out = {"name": tpac_name, "materials": len(mats), "textures": len(texs),
           "meshes": len(meshes), "issues": [], "stats": {}}

    def opaque(m):
        return (m.get("blendMode") or "opaque").lower() in ("opaque", "")

    at = [m for m in mats if float(m.get("alphaTest") or 0) > 0]
    bl = [m for m in mats if not opaque(m)]
    both = [m for m in at if not opaque(m)]
    ts = [m for m in mats if "two_sided" in (m.get("flags") or [])]
    out["stats"]["alphaTest 镂空材质"] = len(at)
    out["stats"]["非 opaque 混合材质"] = len(bl)
    out["stats"]["两者共存（刘海类）"] = len(both)
    out["stats"]["two_sided"] = len(ts)

    fmts = Counter(t.get("format") for t in texs)
    out["stats"]["贴图格式"] = dict(fmts)
    bad = [t for t in texs if t.get("format") in KNOW_BAD_TEX]
    if bad:
        out["issues"].append(
            f"★ {len(bad)}/{len(texs)} 张贴图格式不被支持（{sorted({t['format'] for t in bad})}）"
            f" —— 用到它们的材质会退回「按名字猜贴图」，可能贴错或看不见")

    noTex = [m for m in mats if not (m.get("textures") or [])
             and not m.get("secondMaterialGuid")]
    if noTex:
        out["issues"].append(f"{len(noTex)}/{len(mats)} 个材质没有关联贴图（会退回按名字猜）")

    # 骨架：从 pack 的网格统计骨骼索引
    mx = 0
    used = set()
    for m in meshes:
        for sm in (m.get("submeshes") or m.get("subMeshes") or []):
            bu = sm.get("bonesUsed")
            if isinstance(bu, (list, tuple)) and bu:
                mx = max(mx, max(int(x) for x in bu))
                used.update(int(x) for x in bu)
    if not mx:
        for sl in (pack.get("skeletons") or []):
            n = sl.get("boneCount") or sl.get("bones")
            if isinstance(n, int):
                mx = max(mx, n - 1)
    out["stats"]["用到的骨骼数"] = len(used)
    out["stats"]["骨骼索引 max"] = mx
    if mx > 27:
        out["issues"].append(
            f"★ 骨骼索引最大 {mx} > 27 —— 不是 BL 27 骨骨架，套 BL 动画会错位/炸开")

    names = [m.get("name", "") for m in meshes]
    if names:
        tail = Counter(n.rsplit("_", 1)[-1].lower() for n in names if "_" in n)
        known = sum(v for k, v in tail.items()
                    if k in ("body", "head", "feet", "hand", "hair", "leg",
                             "arm", "torso", "cloth", "cap", "boot"))
        out["stats"]["可识别部件后缀的网格"] = f"{known}/{len(names)}"
        if known * 3 < len(names):
            out["issues"].append(
                f"名字里几乎没有可识别的部件后缀（{known}/{len(names)}）"
                f" —— 角色分组会兜底成「全部合成一个角色」")
    return out


def report(o):
    print(f"\n=== {o['name']}")
    print(f"  网格 {o['meshes']}  材质 {o['materials']}  贴图 {o['textures']}")
    for k, v in o["stats"].items():
        print(f"    {k:26s} {v}")
    if o["issues"]:
        print("  体检结论：")
        for it in o["issues"]:
            print(f"    - {it}")
    else:
        print("  体检结论：未发现已知会退化的项 ✓")
    return len(o["issues"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tpacs", nargs="*")
    ap.add_argument("--export", help="已导出的目录（含 pack.json），跳过 exportmod")
    ap.add_argument("--scan", help="扫描该目录下所有 *.tpac")
    ap.add_argument("--keep", action="store_true", help="保留临时导出目录")
    a = ap.parse_args()

    mbtool = find_mbtool()
    if not mbtool:
        print("找不到 mbtool：设 MBTOOL 环境变量，或先 build（mbtool/bin/Release/net9.0/mbtool）")
        return 2

    jobs = []
    if a.export:
        jobs.append((None, Path(a.export)))
    if a.scan:
        for f in sorted(Path(a.scan).rglob("*.tpac")):
            jobs.append((f, None))
    for t in a.tpacs:
        jobs.append((Path(t), None))
    if not jobs:
        print(__doc__)
        return 1

    bad_total = 0
    for tpac, pre in jobs:
        tmp = None
        try:
            if pre is not None:
                pack = json.loads((Path(pre) / "pack.json").read_text(encoding="utf-8"))
                name = str(pre)
            else:
                tmp = Path(tempfile.mkdtemp(prefix="mbcheck_"))
                pack, err = export(tpac, tmp, mbtool)
                name = str(tpac)
                if pack is None:
                    print(f"\n=== {name}\n  !! exportmod 失败：{err.strip()[:300]}")
                    bad_total += 1
                    continue
            bad_total += report(check(pack, name))
        except Exception as e:
            print(f"\n=== {tpac}\n  !! 体检异常：{type(e).__name__}: {e}")
            bad_total += 1
        finally:
            if tmp and not a.keep:
                shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n共 {len(jobs)} 个包，累计 {bad_total} 条需要注意的项")
    return 1 if bad_total else 0


if __name__ == "__main__":
    sys.exit(main())
