# -*- coding: utf-8 -*-
"""在"复合 q"的方向上细化：复合顺序、COORD，用脚底贴地+脚不动打分。"""
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

P = Path("D:/dsh-mod/mb-xianjian7/work/imported")
rest, Rrest, parent, names, order = load_skeleton("bl_skeleton.json")
Mrest = {}
for i in order:
    m = np.eye(4); m[:3, :3] = Rrest[i]; m[:3, 3] = rest[i]; Mrest[i] = m
Minv = {i: np.linalg.inv(Mrest[i]) for i in order}
z = np.load(P / "yue.npz", allow_pickle=True)
V = z["verts"].astype(np.float64); bi = z["bone_idx"]; bw = z["bone_wt"]
Varm = V @ AP.C_ARM_FROM_ENG.T
d = json.load(open("anims/inventory_idle.json", encoding="utf-8"))
t_end = max(b["rot"][-1]["t"] for b in d["boneAnims"] if b["rot"])
ts = np.linspace(1, t_end, 30, endpoint=False)

mats = []
for perm in itertools.permutations(range(3)):
    for signs in itertools.product((1, -1), repeat=3):
        M = np.zeros((3, 3))
        for i, (p, s) in enumerate(zip(perm, signs)):
            M[i, p] = s
        if abs(np.linalg.det(M) - 1) < 1e-9:
            mats.append(M)


def world_q(t, order_mode):
    Q = {}
    for i in order:
        qm = S.qmat(AP.sample_rot(d["boneAnims"][i]["rot"], float(t)), conj=False)
        p = parent[i]
        if p is None or p not in Q:
            Q[i] = qm
        elif order_mode == "parent*local":
            Q[i] = Q[p] @ qm
        else:
            Q[i] = qm @ Q[p]
    return Q


def score(order_mode, COORD):
    Q0 = world_q(0, order_mode)
    lows, feet = [], []
    for t in ts:
        Q = world_q(t, order_mode)
        W, joint = {}, {}
        for i in order:
            D = Q[i] @ Q0[i].T
            D = COORD @ D @ COORD.T
            W[i] = D @ Rrest[i]
            p = parent[i]
            joint[i] = (rest[i].copy() if p is None or p not in joint
                        else joint[p] + W[p] @ (Rrest[p].T @ (rest[i] - rest[p])))
        Ms = {i: np.block([[W[i], joint[i][:, None]],
                           [np.zeros((1, 3)), np.ones((1, 1))]]) for i in order}
        Pp = AP.lbs(Varm, bi, bw, Ms, Mrest,
                    mats=AP.pose_matrices(Ms, Mrest, Minv)) @ AP.C_ARM_FROM_ENG
        lows.append(Pp[:, 2].min() * 1000)
        feet.append(np.array([joint[i] for i in (3, 7, 4, 8)]) @ AP.C_ARM_FROM_ENG)
    lows = np.array(lows); feet = np.stack(feet)
    rng = (feet.max(0) - feet.min(0)) * 1000
    return lows.max() - lows.min(), max(lows.max(), -lows.min()), rng.max()


rows = []
for om in ("parent*local", "local*parent"):
    for M in mats:
        g, off, foot = score(om, M)
        rows.append((foot, g, off, om, M))
rows.sort()
print(f"  {'脚范围':>8} {'脚底起伏':>9} {'离地':>7}  {'复合顺序':>13}  COORD")
for foot, g, off, om, M in rows[:8]:
    print(f"  {foot:8.1f} {g:9.1f} {off:7.1f}  {om:>13}  "
          f"[[{M[0,0]:+.0f},{M[0,1]:+.0f},{M[0,2]:+.0f}],"
          f"[{M[1,0]:+.0f},{M[1,1]:+.0f},{M[1,2]:+.0f}],"
          f"[{M[2,0]:+.0f},{M[2,1]:+.0f},{M[2,2]:+.0f}]]")
print("\n（脚范围越小越好；世界朝向假设的基线是 178mm / 脚底 39mm）")
