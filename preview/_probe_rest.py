# -*- coding: utf-8 -*-
"""各动画的 q(0) 到底是不是"游戏空间的 rest 朝向"？

推导：build_pose 里 Rb = D_arm · Rrest，其中 D_arm = COORD·D·COORDᵀ。
要让 Rb 等于骨骼在 armature 空间的**绝对朝向**，必须有
    COORD · Q_rest_eng · COORDᵀ = Rrest      （Q_rest_eng = 游戏空间的 rest 朝向）
即  Q_rest_eng = COORDᵀ · Rrest · COORD。
把每个动画的 q(0) 与它比，夹角小的那个才配当基准。"""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass
import numpy as np
import anim_pose as AP
from sketch_anim_frames import load_skeleton
import solve_anim_convention as S

rest, Rrest, parent, names, order = load_skeleton("bl_skeleton.json")
COORD = AP.COORD
Qrest = {i: COORD.T @ Rrest[i] @ COORD for i in order}     # 游戏空间的 rest 朝向（矩阵）

def ang_between(A, B):
    d = (np.trace(A.T @ B) - 1.0) / 2.0
    return np.degrees(np.arccos(max(-1.0, min(1.0, d))))

print(f"  {'骨名':30s} " + " ".join(f"{f[:12]:>13s}" for f in
      ("inventory_idle", "inv_movements", "walk_barmaid")) + "   （度：q(0) 与推导出的 rest 的夹角）")
fns = ["inventory_idle", "inv_movements", "walk_barmaid"]
D = {f: json.load(open(f"anims/{f}.json", encoding="utf-8")) for f in fns}
tot = {f: [] for f in fns}
for i in order:
    row = []
    for f in fns:
        q0m = S.qmat(D[f]["boneAnims"][i]["rot"][0]["q"], conj=False)
        a = ang_between(q0m, Qrest[i])
        row.append(a)
        tot[f].append(a)
    print(f"  {names.get(i,'?'):30s} " + " ".join(f"{x:13.2f}" for x in row))
print()
for f in fns:
    a = np.array(tot[f])
    print(f"  {f:18s} 平均 {a.mean():6.2f}°  中位 {np.median(a):6.2f}°  "
          f"最大 {a.max():7.2f}°   <=5° 的骨 {int((a<=5).sum())}/28  "
          f"<=15° 的骨 {int((a<=15).sum())}/28")
