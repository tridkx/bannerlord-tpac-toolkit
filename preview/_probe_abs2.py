# -*- coding: utf-8 -*-
"""如果 R(q(t)) 是骨骼在游戏空间的**绝对朝向**，那么 armature 空间的世界旋转
就是 COORD·R(q(t))·COORDᵀ —— 不需要再右乘 Rrest（Rrest 只该出现在 M_rest 里）。
之前一直写成 W = Δ·Rrest，等于把"绝对朝向"又当成"增量"用了一次。"""
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

def run(fn, mode, n=20):
    d = json.load(open(f"anims/{fn}.json", encoding="utf-8"))
    R0q = {i: d["boneAnims"][i]["rot"][0]["q"] for i in order}
    t_end = max(b["rot"][-1]["t"] for b in d["boneAnims"] if b["rot"])
    ts = np.linspace(1, t_end, n, endpoint=False)
    xs, zs, hs = [], [], []
    for t in ts:
        W, joint = {}, {}
        for i in order:
            qm = S.qmat(AP.sample_rot(d["boneAnims"][i]["rot"], float(t)), conj=False)
            Qa = COORD @ qm @ COORD.T                 # 绝对朝向（armature 空间）
            if mode == "abs":                         # 纯绝对朝向，不乘 Rrest
                Rb = Qa
            elif mode == "abs_rest":                  # 绝对朝向 × Rrest⁻¹ × Rrest 等价于 abs
                Rb = Qa
            elif mode == "delta":
                D = COORD @ (qm @ S.qmat(R0q[i], conj=True)) @ COORD.T
                Rb = D @ Rrest[i]
            W[i] = Rb
            p = parent[i]
            joint[i] = (rest[i].copy() if p is None or p not in joint
                        else joint[p] + W[p] @ (Rrest[p].T @ (rest[i] - rest[p])))
        ph = np.array([joint[i] for i in (0, 13, 19, 26)]) @ AP.C_ARM_FROM_ENG
        xs.append((abs(ph[2][0]) + abs(ph[3][0])) / 2 * 1000)
        zs.append((ph[2][2] + ph[3][2]) / 2 * 1000)
        hs.append(ph[1][2] * 1000)
    return np.median(xs), np.median(zs), np.median(hs)

print("水平距离 / 手高 / 头高（mm）。期望：水平 150~300、手高 800~1000、头高 ~1560\n")
for fn in ("inventory_idle", "walk_barmaid"):
    for m in ("delta", "abs"):
        x, z, h = run(fn, m)
        tag = "✓" if (150 < x < 350 and z < h - 300) else ("手高举 ✗" if z > h - 200 else "?")
        print(f"  {fn:16s} {m:8s} 水平 {x:6.0f}  手高 {z:6.0f}  头高 {h:6.0f}   {tag}")
