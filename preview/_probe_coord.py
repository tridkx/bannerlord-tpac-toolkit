# -*- coding: utf-8 -*-
"""用**物理判据**重新穷举 COORD（24 个立方体旋转）。

skill 当初靠"网格边长拉伸"选 COORD —— 但边长是**相似不变量**：
任何全局坐标变换都不会改变它，所以那个判据只能排除"形变爆炸"的选项，
**区分不出旋转轴的正误**（多个 COORD 会并列同名次）。

这里换个判据：站立待机时**脚不该动**（人站着不动），
取"脚部运动范围最小"的那个 COORD。
"""
import sys, json, itertools
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass
import numpy as np
import anim_pose as AP
import solve_anim_convention as S
from sketch_anim_frames import load_skeleton

rest, Rrest, parent, names, order = load_skeleton("bl_skeleton.json")
d = json.load(open("anims/inventory_idle.json", encoding="utf-8"))
R0 = {i: d["boneAnims"][i]["rot"][0]["q"] for i in order}
t_end = max(b["rot"][-1]["t"] for b in d["boneAnims"] if b["rot"])
ts = np.arange(1, t_end + 1, max(1, t_end // 120), dtype=float)

def pose_ranges(COORD):
    J = []
    for t in ts:
        W, joint = {}, {}
        for i in order:
            q = AP.sample_rot(d["boneAnims"][i]["rot"], float(t))
            D = S.qmat(q, conj=False) @ S.qmat(R0[i], conj=True)
            D = COORD @ D @ COORD.T
            Rb = D @ Rrest[i]
            W[i] = Rb
            p = parent[i]
            joint[i] = (rest[i].copy() if p is None or p not in joint
                        else joint[p] + W[p] @ (Rrest[p].T @ (rest[i] - rest[p])))
        J.append([joint[i] for i in order])
    J = np.stack(J) @ AP.C_ARM_FROM_ENG
    rng = (J.max(0) - J.min(0)) * 1000
    return rng

# 24 个立方体旋转（置换 + 符号，det=+1）
mats = []
for perm in itertools.permutations(range(3)):
    for signs in itertools.product((1, -1), repeat=3):
        M = np.zeros((3, 3))
        for i, (p, s) in enumerate(zip(perm, signs)):
            M[i, p] = s
        if abs(np.linalg.det(M) - 1) < 1e-9:
            mats.append(M)
print(f"共 {len(mats)} 个立方体旋转。判据：待机时脚/趾的运动范围越小越好\n")
feets = [3, 7, 4, 8]
rows = []
for M in mats:
    rng = pose_ranges(M)
    foot = max(rng[i].max() for i in feets)
    hand = max(rng[i].max() for i in (19, 26))
    head = rng[13].max()
    rows.append((foot, hand, head, M))
rows.sort(key=lambda x: x[0])
print(f"  {'脚(最差)':>9} {'手(最差)':>9} {'头':>7}   COORD 矩阵（行）")
for foot, hand, head, M in rows[:8]:
    tag = "  ← skill 现在用的" if np.allclose(M, AP.COORD) else ""
    print(f"  {foot:9.1f} {hand:9.1f} {head:7.1f}   "
          f"[[{M[0,0]:+.0f},{M[0,1]:+.0f},{M[0,2]:+.0f}],"
          f"[{M[1,0]:+.0f},{M[1,1]:+.0f},{M[1,2]:+.0f}],"
          f"[{M[2,0]:+.0f},{M[2,1]:+.0f},{M[2,2]:+.0f}]]{tag}")
