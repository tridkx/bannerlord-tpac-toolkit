# -*- coding: utf-8 -*-
"""穷举 24 种"列置换"（立方体旋转），把骨架 rest 的约定对齐到动画的约定。
判据：走路/待机时手高必须明显低于头高（自然摆臂），且水平距离 150~350mm。"""
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
COORD = AP.COORD
g = json.load(open("game_skeleton_rest.json", encoding="utf-8"))
B = g["bones"]; par = {x["i"]: x["parent"] for x in B}
Mloc = {x["i"]: np.array(x["local"], float) for x in B}
Abs = {x["i"]: np.array(x["absolute"], float) for x in B}
sn = [x["name"] for x in B]
Qsk = {}
for i in order:
    base = names.get(i, "").rsplit("_", 1)[0]
    Qsk[i] = Abs[sn.index(base)][:3, :3] if base in sn else None

perms = []
for pm in itertools.permutations(range(3)):
    for sg in itertools.product((1, -1), repeat=3):
        M = np.zeros((3, 3))
        for r, (c, s) in enumerate(zip(pm, sg)):
            M[r, c] = s
        if abs(np.linalg.det(M) - 1) < 1e-9:
            perms.append(M)

def score(P, fn):
    d = json.load(open(f"anims/{fn}.json", encoding="utf-8"))
    R0q = {i: d["boneAnims"][i]["rot"][0]["q"] for i in order}
    t_end = max(b["rot"][-1]["t"] for b in d["boneAnims"] if b["rot"])
    ts = np.linspace(1, t_end, 12, endpoint=False)
    xs, hz, th = [], [], []
    for t in ts:
        W, joint = {}, {}
        for i in order:
            qm = S.qmat(AP.sample_rot(d["boneAnims"][i]["rot"], float(t)), conj=False)
            Bs = Qsk[i] if Qsk[i] is not None else S.qmat(R0q[i])
            D = COORD @ (qm @ (Bs @ P).T) @ COORD.T
            W[i] = D @ Rrest[i]
            p = parent[i]
            joint[i] = (rest[i].copy() if p is None or p not in joint
                        else joint[p] + W[p] @ (Rrest[p].T @ (rest[i] - rest[p])))
        ph = np.array([joint[i] for i in (13, 19, 26)]) @ AP.C_ARM_FROM_ENG
        xs.append((abs(ph[1][0]) + abs(ph[2][0])) / 2 * 1000)
        hz.append((ph[1][2] + ph[2][2]) / 2 * 1000)
        th.append(ph[0][2] * 1000)
    return np.median(xs), np.median(hz), np.median(th)

rows = []
for P in perms:
    try:
        x1, h1, t1 = score(P, "walk_barmaid")
        x2, h2, t2 = score(P, "inventory_idle")
    except Exception:
        continue
    # 评分：手应低于头 300mm 以上；水平距离落在 150~350
    pen = 0.0
    for x, h, t in ((x1, h1, t1), (x2, h2, t2)):
        pen += max(0.0, (t - 300) - h)                 # 手太高的惩罚
        pen += max(0.0, x - 350) + max(0.0, 150 - x)   # 水平距离偏离
    rows.append((pen, x1, h1, t1, x2, h2, t2, P))
rows.sort(key=lambda r: r[0])
print(f"  {'惩罚':>8} | {'走路 水平/手高/头高':>26} | {'待机 水平/手高/头高':>26} | 置换")
for pen, x1, h1, t1, x2, h2, t2, P in rows[:6]:
    print(f"  {pen:8.0f} | {x1:8.0f}/{h1:7.0f}/{t1:6.0f} | {x2:8.0f}/{h2:7.0f}/{t2:6.0f} | "
          f"{np.round(P,0).astype(int).tolist()}")
print("\n（惩罚 0 = 完全满足判据；单位 mm）")
