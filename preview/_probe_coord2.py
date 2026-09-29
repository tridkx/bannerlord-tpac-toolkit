# -*- coding: utf-8 -*-
"""用**解剖学判据**穷举 COORD：
  走路时大腿/小腿 = 绕**左右轴**前后摆（轴应与左右轴平行）；
  前臂扭转骨 = 绕**自身骨轴**扭转。
（之前用"脚不动"穷举有盲区 —— 姿势缩起来也能让脚不动。）"""
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

def axis_of(R):
    tr = np.trace(R)
    ang = np.degrees(np.arccos(max(-1.0, min(1.0, (tr - 1) / 2))))
    if ang < 1e-6:
        return 0.0, np.zeros(3)
    ax = np.array([R[2,1]-R[1,2], R[0,2]-R[2,0], R[1,0]-R[0,1]])
    n = np.linalg.norm(ax)
    return ang, (ax/n if n > 1e-9 else np.zeros(3))

d = json.load(open("anims/walk_barmaid.json", encoding="utf-8"))
R0 = {i: d["boneAnims"][i]["rot"][0]["q"] for i in order}
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

print("判据：走路时大腿(thigh)/小腿(calf) 的旋转轴应与**左右轴**平行（夹角→0 最好）\n")
print(f"  {'大腿轴↔左右轴':>13} {'小腿轴↔左右轴':>13}   COORD")
rows = []
for M in mats:
    scores = []
    for i in (1, 5, 2, 6):
        best, bx = 0.0, None
        for t in ts:
            q = AP.sample_rot(d["boneAnims"][i]["rot"], float(t))
            R = S.qmat(q) @ S.qmat(R0[i], conj=True)
            a, ax = axis_of(R)
            if a > best:
                best, bx = a, ax
        if bx is None:
            continue
        # 轴变换到 armature 空间，取与 X 轴的夹角
        bxa = M @ bx
        c = abs(float(bxa[0])) / (np.linalg.norm(bxa) + 1e-12)
        scores.append(np.degrees(np.arccos(min(1.0, c))))
    if not scores:
        continue
    rows.append((np.mean(scores[:2]), np.mean(scores[2:]), M))
rows.sort(key=lambda x: x[0] + x[1])
for th, ca, M in rows[:6]:
    tag = "  ← skill 现用" if np.allclose(M, AP.COORD) else ""
    print(f"  {th:13.1f} {ca:13.1f}   "
          f"[[{M[0,0]:+.0f},{M[0,1]:+.0f},{M[0,2]:+.0f}],"
          f"[{M[1,0]:+.0f},{M[1,1]:+.0f},{M[1,2]:+.0f}],"
          f"[{M[2,0]:+.0f},{M[2,1]:+.0f},{M[2,2]:+.0f}]]{tag}")
print("\n（夹角越接近 0 越好；90 表示轴完全跑到别的方向上去了）")
