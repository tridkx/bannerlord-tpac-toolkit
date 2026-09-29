# -*- coding: utf-8 -*-
"""用动画**自身的运动周期**给 t 轴定标 —— 比"拿 clip duration 换算"可靠。

思路：待机动作的"摇晃"是重心/呼吸的往复运动，周期在物理上是有常识范围的
（人的站姿重心摆动 ≈ 2~4 秒一个来回）。量出"一个来回是多少个 t"，
就能反推 t 的真实刻度（t/秒），再看它跟 clip 换算出来的值差多少。
"""
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

for fn, probe_ids in (("inventory_idle", [0, 9, 13]), ("walk_barmaid", [0, 13])):
    d = json.load(open(f"anims/{fn}.json", encoding="utf-8"))
    t_end = max(b["rot"][-1]["t"] for b in d["boneAnims"] if b["rot"])
    R0 = {i: d["boneAnims"][i]["rot"][0]["q"] for i in order}
    meta = idx[fn]
    print(f"\n===== {fn}  t 范围 0..{t_end}  clip={meta['clip']} "
          f"dur={meta['seconds']}s  -> 换算 {meta['fps']:.1f} t/s =====")

    # 全身采样（1 t 一个点），记录几根代表骨的世界位置
    ts = np.arange(1, t_end + 1, 1.0)
    track = []
    for t in ts:
        Ms = AP.build_pose(rest, Rrest, parent, order, d, float(t), R0)
        track.append([Ms[i][:3, 3] for i in probe_ids])
    T = np.stack(track)                      # (F, nb, 3)
    T = T @ AP.C_ARM_FROM_ENG                # engine 空间

    for k, i in enumerate(probe_ids):
        sig = T[:, k, :]
        # 去均值后看主周期：对 x/y 分别做自相关
        for ax, an in ((0, "x 左右"), (1, "y 前后")):
            v = sig[:, ax] - sig[:, ax].mean()
            if v.std() < 1e-4:
                continue
            ac = np.correlate(v, v, "full")[len(v)-1:]
            ac /= ac[0]
            # 找第一个上升沿之后的峰值（跳过 lag=0 附近的下降段）
            lo = int(np.argmin(ac[:min(200, len(ac))]))       # 第一个谷
            if lo + 2 >= len(ac):
                continue
            pk = lo + int(np.argmax(ac[lo:]))
            amp = (sig[:, ax].max() - sig[:, ax].min()) * 1000
            print(f"  {names.get(i,''):22s} {an}: 振幅 {amp:6.1f}mm  "
                  f"主周期 ≈ {pk:4d} t  ->  按 {meta['fps']:.1f} t/s 是 {pk/meta['fps']:5.2f}s，"
                  f"按 30 t/s 是 {pk/30.0:5.2f}s，按 60 t/s 是 {pk/60.0:5.2f}s")
