# -*- coding: utf-8 -*-
"""脚应该在**骨盆正下方**（水平偏移小、z 低）。量脚相对骨盆的三轴偏移。"""
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
C = AP.C_ARM_FROM_ENG
print("bl_skeleton rest：脚相对骨盆（引擎空间 x左右 y前后 z上下）")
pv = rest[0] @ C.T
for nm, i in (("l_foot", 3), ("r_foot", 7), ("l_toe", 4)):
    d = (rest[i] @ C.T) - pv
    print(f"   {nm:8s} [{d[0]:+.3f} {d[1]:+.3f} {d[2]:+.3f}]")
print("   （脚应在 x≈±0.1、y≈0、z≈-0.9）\n")

def measure(fn, compose, basis, n=12):
    d = json.load(open(f"anims/{fn}.json", encoding="utf-8"))
    ba = d["boneAnims"]
    R0q = {i: ba[i]["rot"][0]["q"] for i in order}
    t_end = max(b["rot"][-1]["t"] for b in ba if b["rot"])
    ts = np.linspace(1, t_end, n, endpoint=False)
    rows = []
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
            Bs = Q0[i] if basis == "anim_q0" else S.qmat(R0q[i])
            D = C @ (Q[i] @ Bs.T) @ C.T
            W[i] = D @ Rrest[i]
            p = parent[i]
            joint[i] = (rest[i].copy() if p is None or p not in joint
                        else joint[p] + W[p] @ (Rrest[p].T @ (rest[i] - rest[p])))
        pv = joint[0] @ C
        f = np.array([joint[i] for i in (3, 7)]) @ C
        rel = f - pv
        rows.append([rel[:, 0].mean()*1000, rel[:, 1].mean()*1000, rel[:, 2].mean()*1000])
    return np.array(rows).mean(0)

print("待机时脚相对骨盆的偏移（mm），期望 y≈0 / z≈-900：")
print(f"  {'组合':24s} {'x左右':>8} {'y前后':>8} {'z上下':>8}")
for basis in ("anim_q0",):
    for compose in (False, True):
        r = measure("inventory_idle", compose, basis)
        print(f"  compose={compose!s:5s} basis={basis:8s} {r[0]:8.0f} {r[1]:8.0f} {r[2]:8.0f}")
