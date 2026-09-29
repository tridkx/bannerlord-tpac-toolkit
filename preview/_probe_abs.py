# -*- coding: utf-8 -*-
"""Δ 到底是"世界增量"（不该沿链累积）还是"局部增量"（必须累积）？
用物理判据对撞：站立待机时脚不该动。

skill 当初是靠"网格边长拉伸"选的 abs（不累积）—— 但那个判据只保证形变不爆炸，
不保证姿势正确。真正能分辨的是"脚动不动"。
"""
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
t_end = max(b["rot"][-1]["t"] for b in d["boneAnims"] if b["rot"])
R0 = {i: d["boneAnims"][i]["rot"][0]["q"] for i in order}


def pose(t, accumulate):
    ba = d["boneAnims"]
    W, joint = {}, {}
    for i in order:
        q = AP.sample_rot(ba[i]["rot"], float(t))
        D = S.qmat(q, conj=False) @ S.qmat(R0[i], conj=True)
        D = COORD @ D @ COORD.T
        p = parent[i]
        if accumulate and p is not None and p in W:
            D = W[p][0] @ D                    # 沿链复合（局部增量假设）
        Rb = D @ Rrest[i]
        W[i] = (D, Rb)
        if p is None or p not in joint:
            joint[i] = rest[i].copy()
        else:
            joint[i] = joint[p] + W[p][1] @ (Rrest[p].T @ (rest[i] - rest[p]))
    return joint


ts = np.arange(1, t_end + 1, max(1, t_end // 300), dtype=float)
watch = {3: "左脚", 7: "右脚", 4: "左趾", 13: "头", 19: "左手", 26: "右手"}
print(f"inventory_idle（站立待机）：期望脚几乎不动\n")
print(f"  {'方案':12s} " + " ".join(f"{v:>9s}" for v in watch.values()) + "   （运动范围 mm）")
for acc in (False, True):
    J = []
    for t in ts:
        j = pose(float(t), acc)
        J.append([j[i] for i in order])
    J = np.stack(J) @ AP.C_ARM_FROM_ENG
    rng = (J.max(0) - J.min(0)) * 1000
    nm = "沿链累积" if acc else "不累积(abs)"
    print(f"  {nm:12s} " + " ".join(f"{rng[i].max():9.1f}" for i in watch))
print("\n（脚的范围小得多的那个方案才是对的）")
