# -*- coding: utf-8 -*-
"""一次性穷举 24 个 COORD × {不累积 / 沿链累积}，用"待机时脚不动"打分。
（换基准已排除、索引错位已排除、单换 COORD 或单换累积都不够，所以做组合。）"""
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
ts = np.arange(1, t_end + 1, max(1, t_end // 100), dtype=float)
mats = []
for perm in itertools.permutations(range(3)):
    for signs in itertools.product((1, -1), repeat=3):
        M = np.zeros((3, 3))
        for i, (p, s) in enumerate(zip(perm, signs)):
            M[i, p] = s
        if abs(np.linalg.det(M) - 1) < 1e-9:
            mats.append(M)

def ranges(COORD, acc):
    J = []
    for t in ts:
        W, joint = {}, {}
        for i in order:
            q = AP.sample_rot(d["boneAnims"][i]["rot"], float(t))
            D = S.qmat(q, conj=False) @ S.qmat(R0[i], conj=True)
            D = COORD @ D @ COORD.T
            p = parent[i]
            if acc and p is not None and p in W:
                D = W[p] @ D
            W[i] = D
            joint[i] = (rest[i].copy() if p is None or p not in joint
                        else joint[p] + W[p] @ (Rrest[p].T @ (rest[i] - rest[p])))
        J.append([joint[i] for i in order])
    J = np.stack(J) @ AP.C_ARM_FROM_ENG
    return (J.max(0) - J.min(0)) * 1000

rows = []
for M in mats:
    for acc in (False, True):
        r = ranges(M, acc)
        foot = max(r[i].max() for i in (3, 7, 4, 8))
        rows.append((foot, max(r[i].max() for i in (19, 26)), r[13].max(), acc, M))
rows.sort(key=lambda x: x[0])
print(f"  {'脚(最差)':>9} {'手(最差)':>9} {'头':>7}  {'累积':>4}  COORD")
for foot, hand, head, acc, M in rows[:10]:
    tag = "  ← skill 现用" if (np.allclose(M, AP.COORD) and not acc) else ""
    print(f"  {foot:9.1f} {hand:9.1f} {head:7.1f}  {'是' if acc else '否':>4}  "
          f"[[{M[0,0]:+.0f},{M[0,1]:+.0f},{M[0,2]:+.0f}],"
          f"[{M[1,0]:+.0f},{M[1,1]:+.0f},{M[1,2]:+.0f}],"
          f"[{M[2,0]:+.0f},{M[2,1]:+.0f},{M[2,2]:+.0f}]]{tag}")
print(f"\n（脚 184.5mm 是当前组合；出现远小于它的组合才说明找对了方向）")
