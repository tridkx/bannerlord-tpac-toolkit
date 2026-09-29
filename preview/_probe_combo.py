# -*- coding: utf-8 -*-
"""二维组合：{q 直接当绝对朝向, 沿链复合 q} × {基准 q(0), 骨架绝对 rest}。
之前"复合 q"是在**旧基准**下试的（结论作废），现在换成骨架 rest 重试。
判据：手高应落在 900~1150mm（摆臂/自然下垂）、头高 ~1550、水平 150~350。"""
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

def measure(fn, compose, basis, n=16):
    d = json.load(open(f"anims/{fn}.json", encoding="utf-8"))
    ba = d["boneAnims"]
    R0q = {i: ba[i]["rot"][0]["q"] for i in order}
    t_end = max(b["rot"][-1]["t"] for b in ba if b["rot"])
    ts = np.linspace(1, t_end, n, endpoint=False)
    xs, hz, th, sh = [], [], [], []
    for t in ts:
        def worldq(tt):
            Q = {}
            for i in order:
                qm = S.qmat(AP.sample_rot(ba[i]["rot"], float(tt)), conj=False)
                p = parent[i]
                Q[i] = (Q[p] @ qm) if (compose and p is not None and p in Q) else qm
            return Q
        Q = worldq(t); Q0 = worldq(0)
        W, joint = {}, {}
        for i in order:
            if basis == "anim_q0":
                Bs = Q0[i]
            else:
                Bs = Qsk[i] if Qsk[i] is not None else Q0[i]
            D = COORD @ (Q[i] @ Bs.T) @ COORD.T
            W[i] = D @ Rrest[i]
            p = parent[i]
            joint[i] = (rest[i].copy() if p is None or p not in joint
                        else joint[p] + W[p] @ (Rrest[p].T @ (rest[i] - rest[p])))
        ph = np.array([joint[i] for i in (0, 13, 19, 26)]) @ AP.C_ARM_FROM_ENG
        xs.append((abs(ph[2][0]) + abs(ph[3][0])) / 2 * 1000)
        hz.append((ph[2][2] + ph[3][2]) / 2 * 1000)
        th.append(ph[1][2] * 1000)
        sh.append(ph[0][2] * 1000)
    return (np.median(xs), np.median(hz), np.median(th), np.median(sh))

print("水平/手高/头高/骨盆高（mm）。期望 手高 900~1150、头高 ~1550、骨盆 ~915\n")
for fn in ("inventory_idle", "walk_barmaid"):
    for compose in (False, True):
        for basis in ("anim_q0", "skel"):
            try:
                x, h, t, s = measure(fn, compose, basis)
            except Exception as e:
                print(f"  {fn:15s} compose={compose!s:5s} basis={basis:8s} err {type(e).__name__}")
                continue
            ok = (900 < h < 1200) and (1450 < t < 1650)
            print(f"  {fn:15s} compose={compose!s:5s} basis={basis:8s} "
                  f"水平{x:6.0f} 手高{h:6.0f} 头高{t:6.0f} 骨盆{s:5.0f}  {'✓' if ok else ''}")
