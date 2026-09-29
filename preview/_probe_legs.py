# -*- coding: utf-8 -*-
"""待机时两脚应该**并排**（前后差很小、左右分开），而不是一前一后。
这是上一轮"手高/水平/脚底"三条判据都漏掉的一维。"""
import sys, json
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
COORD = AP.COORD
g = json.load(open("game_skeleton_rest.json", encoding="utf-8"))
B = g["bones"]; sn = [x["name"] for x in B]
Qabs = {x["i"]: np.array(x["absolute"], float)[:3, :3] for x in B}
Qsk = {}
for i in order:
    base = names.get(i, "").rsplit("_", 1)[0]
    Qsk[i] = Qabs[sn.index(base)] if base in sn else None

# bl_skeleton 自己的 rest 里，两脚前后差 = 0（并排）
print("bl_skeleton 的 rest（A-pose）：l_foot y=%.3f  r_foot y=%.3f  前后差 %.1fmm"
      % (rest[3][2], rest[7][2], abs(rest[3][2]-rest[7][2])*1000))

def measure(fn, compose, basis, n=16):
    d = json.load(open(f"anims/{fn}.json", encoding="utf-8"))
    ba = d["boneAnims"]
    R0q = {i: ba[i]["rot"][0]["q"] for i in order}
    t_end = max(b["rot"][-1]["t"] for b in ba if b["rot"])
    ts = np.linspace(1, t_end, n, endpoint=False)
    out = []
    for t in ts:
        def wq(tt):
            Q = {}
            for i in order:
                qm = S.qmat(AP.sample_rot(ba[i]["rot"], float(tt)), conj=False)
                p = parent[i]
                Q[i] = (Q[p] @ qm) if (compose and p is not None and p in Q) else qm
            return Q
        Q, Q0 = wq(t), wq(0)
        W, joint = {}, {}
        for i in order:
            Bs = Q0[i] if basis == "anim_q0" else (Qsk[i] if Qsk[i] is not None else Q0[i])
            D = COORD @ (Q[i] @ Bs.T) @ COORD.T
            W[i] = D @ Rrest[i]
            p = parent[i]
            joint[i] = (rest[i].copy() if p is None or p not in joint
                        else joint[p] + W[p] @ (Rrest[p].T @ (rest[i] - rest[p])))
        # 引擎空间：脚的前后=y、左右=x、上下=z
        f = np.array([joint[i] for i in (3, 7, 4, 8)]) @ AP.C_ARM_FROM_ENG
        out.append((abs(f[0][1]-f[1][1]) * 1000,      # 两脚前后差
                    abs(f[0][0]-f[1][0]) * 1000,      # 左右间距
                    min(f[0][1], f[1][1]) * 1000))    # 是否都在身后
    a = np.array(out)
    return a[:, 0].mean(), a[:, 1].mean(), a[:, 2].mean()

print("\n待机两脚的前后差（mm）；并排站立应该很小（<80mm），一前一后会 >150\n")
print(f"  {'组合':26s} {'前后差':>8} {'左右间距':>9} {'最小y':>8}")
for basis in ("anim_q0", "skel"):
    for compose in (False, True):
        dy, dx, my = measure("inventory_idle", compose, basis)
        tag = "✓ 并排" if dy < 80 else ("✗ 一前一后" if dy > 150 else "? 略分开")
        print(f"  compose={compose!s:5s} basis={basis:12s} {dy:8.0f} {dx:9.0f} {my:8.0f}   {tag}")
