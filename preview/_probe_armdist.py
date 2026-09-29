# -*- coding: utf-8 -*-
"""判据换成"手到身体中线的水平距离"：
  自然站姿/走路摆臂 ≈ 0.15~0.25m；A-pose（姿势退化成绑定姿势）≈ 0.5~0.6m。"""
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
print("绑定姿势（rest）的手部水平距离：", end="")
h = np.array([rest[i] for i in (19, 26)]) @ AP.C_ARM_FROM_ENG
print(f" 左 {abs(h[0,0])*1000:.0f}mm  右 {abs(h[1,0])*1000:.0f}mm")

for fn in ("inventory_idle", "walk_barmaid"):
    d = json.load(open(f"anims/{fn}.json", encoding="utf-8"))
    R0 = {i: d["boneAnims"][i]["rot"][0]["q"] for i in order}
    t_end = max(b["rot"][-1]["t"] for b in d["boneAnims"] if b["rot"])
    ts = np.linspace(1, t_end, 20, endpoint=False)
    xs, zs = [], []
    for t in ts:
        Ms = AP.build_pose(rest, Rrest, parent, order, d, float(t), R0)
        p = np.array([Ms[i][:3, 3] for i in (19, 26)]) @ AP.C_ARM_FROM_ENG
        xs.append(abs(p[:, 0]).mean()); zs.append(p[:, 2].mean())
    xs = np.array(xs) * 1000; zs = np.array(zs) * 1000
    verdict = "★ 手在身体两侧张开（=A-pose，动画旋转没生效）" if xs.mean() > 400 \
              else ("手贴身体（正常）" if xs.mean() < 300 else "居中，需人工判断")
    print(f"{fn:16s} 水平距离 中位 {np.median(xs):6.0f}mm 范围 [{xs.min():.0f},{xs.max():.0f}]  "
          f"手高 {np.median(zs):6.0f}mm   {verdict}")
