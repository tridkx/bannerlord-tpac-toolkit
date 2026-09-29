# -*- coding: utf-8 -*-
"""用骨架资产的 rest 当 Δ 的基准（三种空间处理各试一遍），
判据：走路 / 待机时"手到身体中线的水平距离"应落到自然摆臂范围（150~300mm），
而不是停在 A-pose 的 650mm 附近。"""
import sys, json, glob
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
sk = json.load(open(sorted(glob.glob("_tmp/sk_*.json"))[0], encoding="utf-8"))
B = sk["bones"]; par = {x["i"]: x["parent"] for x in B}
Mloc = {x["i"]: np.array(x["rest"], float).reshape(4, 4).T for x in B}
Abs = {}
def absolute(i):
    if i in Abs: return Abs[i]
    p = par[i]
    Abs[i] = Mloc[i] if (p is None or p < 0) else absolute(p) @ Mloc[i]
    return Abs[i]
for i in range(len(B)): absolute(i)
skel_names = [x["name"] for x in B]
Q = {}
for i in order:
    base = names.get(i, "").rsplit("_", 1)[0]
    k = skel_names.index(base) if base in skel_names else None
    Q[i] = Abs[k][:3, :3] if k is not None else None

def run(fn, mode, n=20):
    d = json.load(open(f"anims/{fn}.json", encoding="utf-8"))
    R0q = {i: d["boneAnims"][i]["rot"][0]["q"] for i in order}
    t_end = max(b["rot"][-1]["t"] for b in d["boneAnims"] if b["rot"])
    ts = np.linspace(1, t_end, n, endpoint=False)
    xs, zs = [], []
    for t in ts:
        W, joint = {}, {}
        for i in order:
            qm = S.qmat(AP.sample_rot(d["boneAnims"][i]["rot"], float(t)), conj=False)
            if mode == "anim_q0":
                D = qm @ S.qmat(R0q[i], conj=True)
            else:
                Rs = Q[i] if Q[i] is not None else S.qmat(R0q[i])
                if mode == "skel":          # 直接用骨架 rest 旋转
                    D = qm @ Rs.T
                elif mode == "skel_conj":   # 骨架 rest 先做 COORD 共轭
                    D = qm @ (COORD @ Rs @ COORD.T).T
                elif mode == "skel_invconj":  # 反向共轭
                    D = qm @ (COORD.T @ Rs @ COORD).T
            D = COORD @ D @ COORD.T
            W[i] = D @ Rrest[i]
            p = parent[i]
            joint[i] = (rest[i].copy() if p is None or p not in joint
                        else joint[p] + W[p] @ (Rrest[p].T @ (rest[i] - rest[p])))
        p19 = joint[19] @ AP.C_ARM_FROM_ENG
        p26 = joint[26] @ AP.C_ARM_FROM_ENG
        xs.append((abs(p19[0]) + abs(p26[0])) / 2 * 1000)
        zs.append((p19[2] + p26[2]) / 2 * 1000)
    return np.median(xs), np.median(zs)

print("手到中线的水平距离（mm）。A-pose=650；自然下垂/摆臂期望 150~300\n")
print(f"  {'动画':16s} " + " ".join(f"{m:>13s}" for m in ("anim_q0", "skel", "skel_conj", "skel_invconj")))
for fn in ("inventory_idle", "walk_barmaid"):
    row = []
    for m in ("anim_q0", "skel", "skel_conj", "skel_invconj"):
        try:
            x, z = run(fn, m)
            row.append(f"{x:7.0f}/{z:5.0f}")
        except Exception as e:
            row.append(f"err:{type(e).__name__}")
    print(f"  {fn:16s} " + " ".join(f"{r:>13s}" for r in row))
print("\n（格式 水平距离/手高。水平距离落到 150~300 且手高明显低于肩，才算对）")
