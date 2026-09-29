# -*- coding: utf-8 -*-
"""第三个判据（独立于脚）：待机时**上臂应自然下垂**，与躯干夹角很小（约 5~20°）。
A-pose（绑定姿势）是 ~45°。用骨轴的夹角量，不看脚。"""
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
d = json.load(open("anims/inventory_idle.json", encoding="utf-8"))
R0 = {i: d["boneAnims"][i]["rot"][0]["q"] for i in order}
t_end = max(b["rot"][-1]["t"] for b in d["boneAnims"] if b["rot"])

def axes(t, compose):
    Q = {}
    for i in order:
        qm = S.qmat(AP.sample_rot(d["boneAnims"][i]["rot"], float(t)), conj=False)
        p = parent[i]
        Q[i] = (Q[p] @ qm) if (compose and p is not None and p in Q) else qm
    Q0 = {}
    for i in order:
        q0 = S.qmat(R0[i], conj=False)
        p = parent[i]
        Q0[i] = (Q0[p] @ q0) if (compose and p is not None and p in Q0) else q0
    W = {}
    for i in order:
        D = Q[i] @ Q0[i].T
        W[i] = (COORD @ D @ COORD.T) @ Rrest[i]
    return W

def bone_dir(W, i, child):
    """骨轴方向：用父子关节位置差（与 preview 的推导一致）"""
    return None

# 更直接：用"上臂骨向量"在 armature 空间的朝向 —— rest 里的向量经 W 旋转
def arm_angle(W):
    # 上臂 = clavicle(14) -> upperarm_twist(15) 的骨向量；躯干 = spine(9) -> spine1(10)
    def seg(a, b):
        v = Rrest[a] @ (rest[b] - rest[a])          # rest 向量仍在该骨空间
        return W[a] @ v
    torso = seg(9, 10)
    la = seg(14, 15); ra = seg(21, 22)
    def ang(u, v):
        c = abs(float(np.dot(u, v) / (np.linalg.norm(u) * np.linalg.norm(v) + 1e-12)))
        return np.degrees(np.arccos(min(1.0, c)))
    return ang(torso, la), ang(torso, ra)

print("待机时上臂与躯干骨轴的夹角（度）。期望：自然下垂 ≈ 5~20°，A-pose ≈ 45°\n")
print(f"  {'方案':26s} {'左臂(中位)':>10} {'右臂(中位)':>10} {'左臂(最大)':>10}")
for compose in (False, True):
    ts = np.linspace(1, t_end, 24, endpoint=False)
    L, R = [], []
    for t in ts:
        W = axes(t, compose)
        a, b = arm_angle(W)
        L.append(a); R.append(b)
    nm = "复合 q（局部假设）" if compose else "直接用 q（世界假设）"
    print(f"  {nm:26s} {np.median(L):10.1f} {np.median(R):10.1f} {max(L):10.1f}")
print("\n另外：绑定姿势（rest 本身）的夹角 =", end=" ")
W0 = {i: Rrest[i] for i in order}
a, b = arm_angle(W0)
print(f"{a:.1f}° / {b:.1f}°")
