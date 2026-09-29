# -*- coding: utf-8 -*-
"""假设 q 是"相对父骨的局部朝向"：先沿链**复合 q 本身**得到世界朝向，
再求增量 —— 这与之前试的"复合增量 D"是两回事。

判据仍是物理常识：站立待机时脚底要贴地、脚不该移动。"""
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

P = Path("D:/dsh-mod/mb-xianjian7/work/imported")
rest, Rrest, parent, names, order = load_skeleton("bl_skeleton.json")
Mrest = {}
for i in order:
    m = np.eye(4); m[:3, :3] = Rrest[i]; m[:3, 3] = rest[i]; Mrest[i] = m
Minv = {i: np.linalg.inv(Mrest[i]) for i in order}
z = np.load(P / "yue.npz", allow_pickle=True)
V = z["verts"].astype(np.float64); bi = z["bone_idx"]; bw = z["bone_wt"]
Varm = V @ AP.C_ARM_FROM_ENG.T
COORD = AP.COORD

d = json.load(open("anims/inventory_idle.json", encoding="utf-8"))
t_end = max(b["rot"][-1]["t"] for b in d["boneAnims"] if b["rot"])


def world_q(t, compose):
    """compose=True：沿链复合 q（局部朝向假设）；False：直接用 q（世界朝向假设）"""
    Q = {}
    for i in order:
        qm = S.qmat(AP.sample_rot(d["boneAnims"][i]["rot"], float(t)), conj=False)
        p = parent[i]
        Q[i] = qm if (not compose or p is None or p not in Q) else Q[p] @ qm
    return Q


def run(compose):
    Q0 = world_q(0, compose)
    ts = np.linspace(1, t_end, 36, endpoint=False)
    lows, feet = [], []
    for t in ts:
        Q = world_q(t, compose)
        W, joint = {}, {}
        for i in order:
            D = Q[i] @ Q0[i].T
            D = COORD @ D @ COORD.T
            W[i] = D @ Rrest[i]
            p = parent[i]
            joint[i] = (rest[i].copy() if p is None or p not in joint
                        else joint[p] + W[p] @ (Rrest[p].T @ (rest[i] - rest[p])))
        Ms = {i: np.block([[W[i], joint[i][:, None]], [np.zeros((1, 3)), np.ones((1, 1))]])
              for i in order}
        Pp = AP.lbs(Varm, bi, bw, Ms, Mrest,
                    mats=AP.pose_matrices(Ms, Mrest, Minv)) @ AP.C_ARM_FROM_ENG
        lows.append(Pp[:, 2].min() * 1000)
        feet.append(np.array([joint[i] for i in (3, 7, 4, 8)]) @ AP.C_ARM_FROM_ENG)
    lows = np.array(lows); feet = np.stack(feet)
    rng = (feet.max(0) - feet.min(0)) * 1000
    return lows, rng


for compose in (False, True):
    lows, rng = run(compose)
    nm = "复合 q（局部朝向假设）" if compose else "直接用 q（世界朝向假设）"
    print(f"\n===== {nm}")
    print(f"  脚底 z：min {lows.min():+7.1f}  max {lows.max():+7.1f}  范围 {lows.max()-lows.min():6.1f}mm")
    print(f"  脚关节运动范围：左{ rng[0].max():6.1f}  右{rng[1].max():6.1f}  "
          f"左趾{rng[2].max():6.1f}  右趾{rng[3].max():6.1f} mm")
