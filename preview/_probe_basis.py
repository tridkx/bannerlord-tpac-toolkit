# -*- coding: utf-8 -*-
"""用物理判据挑基准：待机动画里脚应该基本不动。
分别拿三个动画各自的 q(0) 当 rest 基准，算同一段待机里各关节的运动范围。"""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass
import numpy as np
import anim_pose as AP
from sketch_anim_frames import load_skeleton

rest, Rrest, parent, names, order = load_skeleton("bl_skeleton.json")
D = {f: json.load(open(f"anims/{f}.json", encoding="utf-8"))
     for f in ("inventory_idle", "inv_movements", "walk_barmaid")}
target = D["inventory_idle"]
t_end = max(b["rot"][-1]["t"] for b in target["boneAnims"] if b["rot"])
ts = np.arange(1, t_end + 1, max(1, t_end // 300), dtype=float)

watch = {3: "左脚", 7: "右脚", 13: "头", 19: "左手", 26: "右手", 0: "骨盆"}
print(f"目标：inventory_idle（待机）。期望：脚几乎不动、头微晃、手轻微摆动\n")
print(f"  {'基准 R0 取自':18s} " + " ".join(f"{v:>9s}" for v in watch.values())
      + "   （各关节运动范围 mm，取 xyz 最大分量）")
for basis in ("inventory_idle", "inv_movements", "walk_barmaid"):
    R0 = {i: D[basis]["boneAnims"][i]["rot"][0]["q"] for i in order}
    J = []
    for t in ts:
        Ms = AP.build_pose(rest, Rrest, parent, order, target, float(t), R0)
        J.append([Ms[i][:3, 3] for i in order])
    J = np.stack(J) @ AP.C_ARM_FROM_ENG
    rng = (J.max(0) - J.min(0)) * 1000
    row = " ".join(f"{rng[i].max():9.1f}" for i in watch)
    print(f"  {basis:18s} {row}")
print("\n（若某个基准让脚的范围掉到几十毫米以内，那它就是真正的 rest 朝向）")
