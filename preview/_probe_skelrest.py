# -*- coding: utf-8 -*-
"""用**骨架资产的 rest 旋转**（游戏真正的 bind pose）当 Δ 的基准，
替换掉一直用的"动画第 0 帧姿势"。判据：走路时手臂应前后自然摆动、
手不该停在 A-pose 附近。"""
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
# 骨架资产 -> 每根骨的绝对 rest 旋转（游戏空间）
d = json.load(open(sorted(glob.glob("_tmp/sk_*.json"))[0], encoding="utf-8"))
B = d["bones"]; par = {x["i"]: x["parent"] for x in B}
Mloc = {x["i"]: np.array(x["rest"], float).reshape(4, 4).T for x in B}
Abs = {}
def absolute(i):
    if i in Abs: return Abs[i]
    p = par[i]
    Abs[i] = Mloc[i] if (p is None or p < 0) else absolute(p) @ Mloc[i]
    return Abs[i]
for i in range(len(B)): absolute(i)
print("骨架资产的骨骼名 vs bl_skeleton 的映射检查：")
skel_names = [x["name"] for x in B]
mapping = {}
for i in order:
    bn = names.get(i, "")
    base = bn.rsplit("_", 1)[0]          # bip01_pelvis_0 -> bip01_pelvis
    for k, sn in enumerate(skel_names):
        if sn == base:
            mapping[i] = k
            break
print(f"  匹配上 {len(mapping)}/{len(order)} 根")
Qskel = {i: Abs[k][:3, :3] for i, k in mapping.items()}

anim = json.load(open("anims/walk_barmaid.json", encoding="utf-8"))
q0 = {i: anim["boneAnims"][i]["rot"][0]["q"] for i in order}
print("\n逐骨对比：q(0) 的旋转 与 骨架 rest 的旋转（夹角）")
bad = 0
for i in order:
    Rq = S.qmat(q0[i]); Rs = Qskel.get(i)
    if Rs is None: continue
    c = (np.trace(Rq.T @ Rs) - 1) / 2
    a = np.degrees(np.arccos(max(-1, min(1, c))))
    if a > 20 and i in (14, 15, 17, 19, 5, 1, 2, 3, 0):
        print(f"  {names.get(i):30s} 夹角 {a:6.1f}°")
        bad += 1
print(f"  （示例骨中差异 >20° 的有 {bad} 根 -> 基准确实不同）")
