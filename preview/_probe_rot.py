# -*- coding: utf-8 -*-
"""每根骨在动画里到底转了多少度 —— 直接对比"骨骼旋转"与"关节位移"，
看是旋转本身过大，还是被链式杠杆放大了。"""
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
BONE_LEN = {}
for i in order:
    p = parent[i]
    BONE_LEN[i] = (float(np.linalg.norm(rest[i] - rest[p])) * 1000) if p is not None else 0.0

idx = json.load(open("anims/index.json", encoding="utf-8"))
for fn in ("inventory_idle", "walk_barmaid"):
    d = json.load(open(f"anims/{fn}.json", encoding="utf-8"))
    t_end = max(b["rot"][-1]["t"] for b in d["boneAnims"] if b["rot"])
    R0 = {i: d["boneAnims"][i]["rot"][0]["q"] for i in order}
    ts = np.arange(1, t_end + 1, max(1, t_end // 300), dtype=float)
    ang = {i: [] for i in order}
    for t in ts:
        for i in order:
            rot = d["boneAnims"][i]["rot"]
            q = AP.sample_rot(rot, float(t))
            c = abs(float(np.dot(q, R0[i])))
            ang[i].append(np.degrees(2 * np.arccos(min(1.0, c))))
    print(f"\n===== {fn}（Δ 相对 rest 的旋转角）=====")
    print(f"  {'骨名':30s} {'骨长mm':>7} {'最大转角':>9} {'末端弧长mm':>11}  说明")
    rows = []
    for i in order:
        a = max(ang[i])
        arc = BONE_LEN[i] * np.radians(a)          # 该骨旋转带来的末端位移上限
        rows.append((a, i, arc))
    for a, i, arc in sorted(rows, reverse=True)[:10]:
        note = ""
        if i in (1, 5) and a > 15:  note = "← 大腿转这么多，待机不该"
        if i in (2, 6) and a > 15:  note = "← 小腿转这么多"
        if i in (3, 7, 4, 8) and a > 20: note = "← 脚/趾转这么多"
        print(f"  {names.get(i,'?'):30s} {BONE_LEN[i]:7.1f} {a:9.2f}° {arc:11.1f}{note}")
