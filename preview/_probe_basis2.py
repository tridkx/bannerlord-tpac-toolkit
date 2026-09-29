# -*- coding: utf-8 -*-
"""假设：q(0) 是"各动画自己的第一帧姿势"，不是共享 rest 朝向。
那么用"姿势正常的动画"的 q(0) 当基准，去驱动"姿势崩掉的动画"，
后者应该变正常（手臂不再高举张开）。"""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass
import numpy as np
import anim_pose as AP
from sketch_anim_frames import load_skeleton

P = Path("D:/dsh-mod/mb-xianjian7/work/imported")
rest, Rrest, parent, names, order = load_skeleton("bl_skeleton.json")
D = {f: json.load(open(f"anims/{f}.json", encoding="utf-8"))
     for f in ("inventory_idle", "inv_movements", "walk_barmaid")}
z = np.load(P / "yue.npz", allow_pickle=True)
V = z["verts"].astype(np.float64); bi = z["bone_idx"]; bw = z["bone_wt"]
Varm = V @ AP.C_ARM_FROM_ENG.T

def arm_span(fn, basis):
    """手臂端点的运动范围 + 上臂相对躯干的角度（走路时应自然摆动，不该高举）"""
    d = D[fn]
    R0 = {i: D[basis]["boneAnims"][i]["rot"][0]["q"] for i in order}
    t_end = max(b["rot"][-1]["t"] for b in d["boneAnims"] if b["rot"])
    ts = np.linspace(1, t_end, 24, endpoint=False)
    hands, shoulders = [], []
    for t in ts:
        Ms = AP.build_pose(rest, Rrest, parent, order, d, float(t), R0)
        hands.append([Ms[i][:3, 3] @ AP.C_ARM_FROM_ENG for i in (19, 26)])
        shoulders.append([Ms[i][:3, 3] @ AP.C_ARM_FROM_ENG for i in (0, 13)])
    H = np.stack(hands); S = np.stack(shoulders)
    hand_rng = (H.max(0) - H.min(0)).max() * 1000
    hand_h = H[:, :, 2].mean() * 1000          # 手的平均高度
    head_h = S[:, 1, 2].mean() * 1000
    return hand_rng, hand_h, head_h

print("走路动画（walk_barmaid）在不同基准下的表现：")
print(f"  {'基准 R0 取自':18s} {'手运动范围':>10} {'手平均高度':>10} {'头平均高度':>10}   判断")
for basis in ("walk_barmaid", "inventory_idle", "inv_movements"):
    r, hh, th = arm_span("walk_barmaid", basis)
    tag = "★ 手在头附近 = 高举（错）" if hh > th - 250 else "手低于头（正常摆臂）"
    print(f"  {basis:18s} {r:9.1f}mm {hh:9.1f}mm {th:9.1f}mm   {tag}")
print("\n对照：待机动画自身")
for basis in ("inventory_idle", "walk_barmaid"):
    r, hh, th = arm_span("inventory_idle", basis)
    print(f"  基准={basis:16s} 手范围 {r:8.1f}mm  手高 {hh:8.1f}mm  头高 {th:8.1f}mm")
