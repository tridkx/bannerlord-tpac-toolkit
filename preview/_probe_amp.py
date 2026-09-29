# -*- coding: utf-8 -*-
"""量每根骨在整段动画里的**运动范围** —— 用物理常识当判据：
站立待机时脚不该动、头只能微晃、手臂轻微摆动。范围明显超出常识就是幅度被放大了。"""
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
idx = json.load(open("anims/index.json", encoding="utf-8"))

for fn in ("inventory_idle", "walk_barmaid"):
    d = json.load(open(f"anims/{fn}.json", encoding="utf-8"))
    t_end = max(b["rot"][-1]["t"] for b in d["boneAnims"] if b["rot"])
    R0 = {i: d["boneAnims"][i]["rot"][0]["q"] for i in order}
    # 整段 1 t 一采样（足够密，能反映真实范围）
    step = max(1, t_end // 400)
    ts = np.arange(1, t_end + 1, step, dtype=float)
    J = []
    for t in ts:
        Ms = AP.build_pose(rest, Rrest, parent, order, d, float(t), R0)
        J.append([Ms[i][:3, 3] for i in order])
    J = np.stack(J) @ AP.C_ARM_FROM_ENG            # (F, nb, 3)
    rng = (J.max(0) - J.min(0)) * 1000             # 每根骨的 xyz 范围 (mm)
    print(f"\n===== {fn}  （{len(ts)} 个采样点覆盖整段 {t_end} t）=====")
    print(f"  {'骨名':30s} {'左右x':>8} {'前后y':>8} {'上下z':>8}  (范围 mm)")
    for k, i in enumerate(order):
        span = rng[k]
        if k < 3 or i in (3, 7, 4, 8, 13, 19, 26, 12, 0, 15, 22):
            flag = ""
            if i in (3, 7, 4, 8) and span.max() > 60:
                flag = "   ← ★ 脚在动（站立时不应当）"
            elif i == 13 and span.max() > 120:
                flag = "   ← ★ 头晃得太多"
            print(f"  {names.get(i,'?'):30s} {span[0]:8.1f} {span[1]:8.1f} {span[2]:8.1f}{flag}")
