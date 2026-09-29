# -*- coding: utf-8 -*-
"""用「父子骨的相对旋转」判据，穷举求出动画四元数所在的坐标系与累积方式。

为什么用这个判据
----------------
顶点/面积判据只能告诉你"炸了"，定位很慢。而这次真正的病灶已经被抓出来了：
head 材质上一条 2.5mm 的边被拉到 225mm（90 倍），两端权重是
`(13,0.64)/(12,0.34)` 与 `(12,0.56)/(13,0.39)` —— **几乎镜像**，本该几乎重合。
即 `head(13)` 与 `neck(12)` 的变换差了 0.87m：neck 转了 22.6°、head 只转 14.3°。
**头不跟随脖子** ⇒ 旋转没有沿骨链累积（或累积公式不对）。

所以用纯骨骼、不需要网格的判据：对每对父子骨 (p,i)，
    实际相对旋转 rel = Wₚᵀ·Wᵢ      期望 rel ≈ Lᵢ = Rrestₚᵀ·Rrestᵢ
偏差角的中位数越小，约定越对。这个判据**极快**，可以穷举。

搜索空间
    coord : 24 个立方体旋转（q 到底在哪个坐标系里表达）
    dmod  : A / A_T          （世界增量的方向）
    form  : abs / local_std / local_alt  （累积公式，三者都满足 t=0 还原）

用法
----
  python solve_anim_coord.py <bl_skeleton.json> <anim.json> [t]
"""
import itertools
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import anim_pose as A                      # noqa: E402
from sketch_anim_frames import load_skeleton   # noqa: E402


def rot_group():
    """24 个行列式为 +1 的置换-符号矩阵（立方体旋转群）。"""
    out = []
    for perm in itertools.permutations(range(3)):
        for signs in itertools.product([1, -1], repeat=3):
            M = np.zeros((3, 3))
            for i, (p, s) in enumerate(zip(perm, signs)):
                M[i, p] = s
            if np.linalg.det(M) > 0.5:
                out.append(M)
    return out


def ang(R):
    return np.degrees(np.arccos(np.clip((np.trace(R) - 1.0) / 2.0, -1.0, 1.0)))


def build(rest, Rrest, parent, order, anim, t, R0, coord, dmod, form):
    ba = anim["boneAnims"]
    W = {}
    for i in order:
        q = A.sample_rot(ba[i]["rot"], t)
        D = A.S.qmat(q, conj=False) @ A.S.qmat(R0[i], conj=True)
        D = coord @ D @ coord.T
        if dmod == "A_T":
            D = D.T
        p = parent[i]
        if p is None or p not in W:
            if form == "abs":
                W[i] = D @ Rrest[i]
            else:
                W[i] = Rrest[i] @ D
            continue
        if form == "abs":
            W[i] = D @ Rrest[i]
        elif form == "local_std":
            W[i] = W[p] @ np.linalg.inv(Rrest[p]) @ Rrest[i] @ D
        else:                                   # local_alt
            W[i] = W[p] @ np.linalg.inv(Rrest[p]) @ D @ Rrest[i]
    return W


def deviation(W, Rrest, parent, order):
    """父子相对旋转与 rest 相对旋转的偏差角（中位数 + 90 分位）。"""
    devs = []
    for i in order:
        p = parent[i]
        if p is None or p not in W:
            continue
        rel = W[p].T @ W[i]
        L = Rrest[p].T @ Rrest[i]
        devs.append(ang(rel @ L.T))
    devs = np.array(devs)
    return np.median(devs), np.percentile(devs, 90), devs.max()


def main():
    skel_path, anim_path = sys.argv[1], sys.argv[2]
    rest, Rrest, parent, names, order = load_skeleton(skel_path)
    anim = json.load(open(anim_path, encoding="utf-8"))
    R0 = {i: anim["boneAnims"][i]["rot"][0]["q"] for i in order}
    t_end = max(b["rot"][-1]["t"] for b in anim["boneAnims"] if b["rot"])
    t = float(sys.argv[3]) if len(sys.argv) > 3 else t_end / 2.0

    coords = rot_group()
    print(f"anim={anim['name']}  t={t:.0f}  coord 候选={len(coords)}")
    print("判据：父子骨相对旋转 vs rest 相对旋转的偏差角（度），越小越好")
    print()
    rows = []
    for ci, coord in enumerate(coords):
        for dmod in ("A", "A_T"):
            for form in ("abs", "local_std", "local_alt"):
                W = build(rest, Rrest, parent, order, anim, t, R0, coord, dmod, form)
                med, p90, mx = deviation(W, Rrest, parent, order)
                rows.append((med, p90, mx, ci, dmod, form, coord))
    rows.sort(key=lambda r: r[0])

    ident = np.eye(3)
    print(f"{'med':>7} {'p90':>7} {'max':>8}  {'coord#':>6} {'dmod':<5} {'form':<10} "
          f"{'coord matrix (rows)'}")
    print("-" * 118)
    for med, p90, mx, ci, dmod, form, coord in rows[:14]:
        tag = "  <== 单位阵(不换坐标)" if np.allclose(coord, ident) else ""
        c = np.array2string(coord, precision=0, separator=",", suppress_small=True)
        print(f"{med:7.2f} {p90:7.2f} {mx:8.2f}  {ci:>6} {dmod:<5} {form:<10} {c}{tag}")

    print()
    med, p90, mx, ci, dmod, form, coord = rows[0]
    print(f"=> 最优：coord#{ci} dmod={dmod} form={form}  偏差 med={med:.2f}° p90={p90:.2f}°")
    print(np.array2string(coord, precision=0, separator=",", suppress_small=True))
    if med > 15:
        print("   ⚠ 中位偏差仍偏大 —— 说明还有维度没覆盖（q 的语义可能不是「绝对朝向」）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())