# -*- coding: utf-8 -*-
"""穷举坐标变换，用「边长拉伸」判据找出正确的动画约定。

背景
----
前面的判据各有盲区，一路踩过来：
  · `solve_anim_convention.py`：只看几根骨的**位置**，既被 abs() 掩盖左右翻转，
    又完全不看旋转 ⇒ 放过了一组会让袖子成尖刺的错误约定。
  · `solve_anim_coord.py`：用「父子骨相对旋转偏差」，但**旋转角是相似不变量**，
    对坐标变换完全不敏感 ⇒ 24 个 coord 并列同名次，等于没筛。
  · 顶点**位移**大小也不能当判据：角色真转身 32° 本来就会产生几百 mm 位移。
唯一真正硬的判据是 **「网格不能被拉长」** —— LBS 是刚体变换的凸组合，
正确约定下三角形/边长只会平滑变化，不会出现 90 倍的尖刺。

本脚本：24 个立方体旋转 × 增量方向 × 累积公式 × 关节偏移公式 × 根骨处理，
      全部用边长拉伸的 p999 排序。

用法
----
  python solve_anim_coord2.py <bl_skeleton.json> <anim.json> <mesh.npz> [t]
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
    out = []
    for perm in itertools.permutations(range(3)):
        for signs in itertools.product([1, -1], repeat=3):
            M = np.zeros((3, 3))
            for i, (p, s) in enumerate(zip(perm, signs)):
                M[i, p] = s
            if np.linalg.det(M) > 0.5:
                out.append(M)
    return out


def build(rest, Rrest, parent, order, anim, t, R0, coord, dmod, acc, posmode, rootmode):
    ba = anim["boneAnims"]
    W, joint = {}, {}
    for i in order:
        q = A.sample_rot(ba[i]["rot"], t)
        D = A.S.qmat(q, conj=False) @ A.S.qmat(R0[i], conj=True)
        D = coord @ D @ coord.T
        if dmod == "A_T":
            D = D.T
        Rb = D @ Rrest[i]
        p = parent[i]
        if p is None or p not in joint:
            W[i] = Rrest[i] @ Rb if rootmode == "rest_then" else Rb
            joint[i] = rest[i].copy()
            continue
        Wp = W[p]
        W[i] = (Wp @ Rb) if acc == "local" else Rb
        d = rest[i] - rest[p]
        if posmode == "restT":
            d = Rrest[p].T @ d
        joint[i] = joint[p] + Wp @ d
    M = {}
    for i in order:
        m = np.eye(4)
        m[:3, :3] = W[i]
        m[:3, 3] = joint[i]
        M[i] = m
    return M


def main():
    skel_path, anim_path, mesh_path = sys.argv[1], sys.argv[2], sys.argv[3]
    rest, Rrest, parent, names, order = load_skeleton(skel_path)
    anim = json.load(open(anim_path, encoding="utf-8"))
    R0 = {i: anim["boneAnims"][i]["rot"][0]["q"] for i in order}
    Mrest = {}
    for i in order:
        m = np.eye(4)
        m[:3, :3] = Rrest[i]
        m[:3, 3] = rest[i]
        Mrest[i] = m

    d = np.load(mesh_path, allow_pickle=True)
    V = np.asarray(d["verts"], dtype=np.float64)
    idx = np.asarray(d["bone_idx"], dtype=np.int64)
    wt = np.asarray(d["bone_wt"], dtype=np.float64)
    F = np.asarray(d["faces"], dtype=np.int64)

    # 顶点采样 + 只保留两端都被采样的边（把 LBS 成本砍到 1/4）
    step = 2
    keep = np.zeros(len(V), bool)
    keep[::step] = True
    E = np.unique(np.sort(np.vstack([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]]), axis=1), axis=0)
    E = E[keep[E[:, 0]] & keep[E[:, 1]]]
    vsel = np.unique(E)
    remap = -np.ones(len(V), np.int64)
    remap[vsel] = np.arange(len(vsel))
    E2 = remap[E]
    Vs, idxs, wts = V[vsel], idx[vsel], wt[vsel]
    V_arm = Vs @ A.C_ARM_FROM_ENG.T
    L0 = np.linalg.norm(Vs[E2[:, 0]] - Vs[E2[:, 1]], axis=1)
    big = L0 > 0.002

    t_end = max(b["rot"][-1]["t"] for b in anim["boneAnims"] if b["rot"])
    t = float(sys.argv[4]) if len(sys.argv) > 4 else t_end / 2.0

    coords = rot_group()
    grid = list(itertools.product(range(len(coords)), ["A", "A_T"], ["abs", "local"],
                                  ["restT"], ["raw"]))
    print(f"anim={anim['name']} t={t:.0f}  顶点采样 {len(vsel)}/{len(V)}  边 {len(E2)}  "
          f"候选={len(grid)}")
    print("判据：边长拉伸 p999（只看 rest 边长 >2mm 的边，排除退化）")
    print()
    print(f"{'p999':>7} {'p99':>7} {'max':>9}  {'coord#':>6} {'dmod':<5} {'acc':<6}")
    print("-" * 60)

    rows = []
    for ci, dmod, acc, posmode, rootmode in grid:
        Ms = build(rest, Rrest, parent, order, anim, t, R0, coords[ci], dmod, acc,
                   posmode, rootmode)
        V2 = A.lbs(V_arm, idxs, wts, Ms, Mrest) @ A.C_ARM_FROM_ENG
        L1 = np.linalg.norm(V2[E2[:, 0]] - V2[E2[:, 1]], axis=1)
        st = L1[big] / L0[big]
        rows.append((np.percentile(st, 99.9), np.percentile(st, 99), st.max(),
                     ci, dmod, acc))

    rows.sort(key=lambda r: r[0])
    for p999, p99, mx, ci, dmod, acc in rows[:16]:
        ident = "  <== 不换坐标" if np.allclose(coords[ci], np.eye(3)) else ""
        print(f"{p999:7.2f} {p99:7.2f} {mx:9.2f}  {ci:>6} {dmod:<5} {acc:<6}{ident}")

    print()
    p999, p99, mx, ci, dmod, acc = rows[0]
    print(f"=> 最优：coord#{ci} dmod={dmod} acc={acc}  p999={p999:.2f} p99={p99:.2f} max={mx:.2f}")
    print(np.array2string(coords[ci], precision=0, separator=",", suppress_small=True))
    if p999 > 3.0:
        print("   ⚠ p999 仍 > 3 —— 说明「Δ = R(q_t)·R(q_0)ᵀ 再右乘 Rrest」这个模型本身不对，")
        print("      不是坐标系问题。需要考虑 q 是「局部朝向、需沿链累积」的模型。")
    return 0


if __name__ == "__main__":
    sys.exit(main())