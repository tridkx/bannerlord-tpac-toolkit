# -*- coding: utf-8 -*-
"""确定"骨骼矩阵的哪一列指向骨轴"（轴向约定）。
骨架资产的绝对关节位置与 rest 旋转都在游戏空间，可以直接比 —— 这能定出
R_skel 的约定；用同样办法再看动画的 q 是哪一套。"""
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

g = json.load(open("game_skeleton_rest.json", encoding="utf-8"))
B = g["bones"]; par = {x["i"]: x["parent"] for x in B}
Mabs = {x["i"]: np.array(x["absolute"], float) for x in B}
pos = {x["i"]: Mabs[x["i"]][:3, 3] for x in B}
kids = {}
for x in B:
    if x["parent"] is not None and x["parent"] >= 0:
        kids.setdefault(x["parent"], []).append(x["i"])

LAB = ["X", "Y", "Z"]
print("骨架资产：R_skel 的各列 与 骨轴（指向第一个子骨）的夹角")
print(f"  {'骨名':30s} {'列X':>7} {'列Y':>7} {'列Z':>7}   最佳列")
votes = []
for x in B:
    i = x["i"]
    if i not in kids:
        continue
    v = pos[kids[i][0]] - pos[i]
    n = np.linalg.norm(v)
    if n < 1e-6:
        continue
    v = v / n
    R = Mabs[i][:3, :3]
    ang = []
    for c in range(3):
        col = R[:, c]
        col = col / (np.linalg.norm(col) + 1e-12)
        ang.append(np.degrees(np.arccos(min(1, abs(float(np.dot(col, v)))))))
    best = int(np.argmin(ang))
    votes.append(best)
    if i < 6 or i in (9, 13, 14, 17, 19):
        print(f"  {x['name']:30s} {ang[0]:7.1f} {ang[1]:7.1f} {ang[2]:7.1f}   {LAB[best]}")
print(f"\n  统计：X 列 {votes.count(0)} 根，Y 列 {votes.count(1)} 根，Z 列 {votes.count(2)} 根"
      f"  （共 {len(votes)} 根有子骨）")

# 动画侧：用 q(t) 与"t 时刻的关节位置"比 —— 关节位置由 build_pose 推出，同一套约定，
# 所以直接看 R(q) 的各列与"该骨在 rest 几何里的骨轴（转到游戏空间）"的夹角
rest, Rrest, parent, names, order = load_skeleton("bl_skeleton.json")
C = AP.C_ARM_FROM_ENG
print("\n动画侧：R(q(0)) 的各列 与 骨轴（bl_skeleton rest 几何，转到游戏空间）的夹角")
d = json.load(open("anims/walk_barmaid.json", encoding="utf-8"))
votes2 = []
for i in order:
    kk = [k for k in order if parent[k] == i]
    if not kk:
        continue
    v = rest[kk[0]] - rest[i]                 # armature 空间
    v = v @ C.T                                # -> 游戏空间（行向量约定）
    n = np.linalg.norm(v)
    if n < 1e-6:
        continue
    v = v / n
    R = S.qmat(d["boneAnims"][i]["rot"][0]["q"])
    ang = []
    for c in range(3):
        col = R[:, c]; col = col / (np.linalg.norm(col) + 1e-12)
        ang.append(np.degrees(np.arccos(min(1, abs(float(np.dot(col, v)))))))
    best = int(np.argmin(ang))
    votes2.append(best)
    if i < 6 or i in (9, 13, 14, 17, 19):
        print(f"  {names.get(i):30s} {ang[0]:7.1f} {ang[1]:7.1f} {ang[2]:7.1f}   {LAB[best]}")
print(f"\n  统计：X 列 {votes2.count(0)} 根，Y 列 {votes2.count(1)} 根，Z 列 {votes2.count(2)} 根"
      f"  （共 {len(votes2)} 根有子骨）")
