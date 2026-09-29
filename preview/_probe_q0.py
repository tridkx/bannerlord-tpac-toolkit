# -*- coding: utf-8 -*-
"""三个动画的第 0 帧是不是同一个"rest 朝向"？
逐骨对比 q(0) —— 若同一根骨在不同动画里 q(0) 不同，那它就不是 rest，
用它做 Δ = q(t)·q(0)⁻¹ 的基准就会把"起点差异"混进每一帧。"""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass
import numpy as np
from sketch_anim_frames import load_skeleton

rest, Rrest, parent, names, order = load_skeleton("bl_skeleton.json")
fns = ["inventory_idle", "inv_movements", "walk_barmaid"]
Q0 = {}
for fn in fns:
    d = json.load(open(f"anims/{fn}.json", encoding="utf-8"))
    Q0[fn] = {i: np.array(d["boneAnims"][i]["rot"][0]["q"], float) for i in order}

print("逐骨对比 q(0)（度：两个动画第 0 帧朝向的夹角）")
print(f"  {'骨名':30s} " + " ".join(f"{b[:9]:>9s}" for b in fns[1:]) + "   与第1帧的夹角")
d1 = json.load(open("anims/inventory_idle.json", encoding="utf-8"))
bad = 0
for i in order:
    a = Q0[fns[0]][i]
    diffs = []
    for fn in fns[1:]:
        c = abs(float(np.dot(a, Q0[fn][i])))
        diffs.append(np.degrees(2 * np.arccos(min(1.0, c))))
    q1 = np.array(d1["boneAnims"][i]["rot"][1]["q"], float)
    c1 = abs(float(np.dot(a, q1)))
    a1 = np.degrees(2 * np.arccos(min(1.0, c1)))
    flag = ""
    if max(diffs) > 1.0:
        flag = "  ← ★ q(0) 各动画不同，不是 rest！"
        bad += 1
    print(f"  {names.get(i,'?'):30s} " + " ".join(f"{x:9.2f}" for x in diffs)
          + f"   {a1:9.2f}°{flag}")
print(f"\n结论：{bad} 根骨的 q(0) 在不同动画间不一致"
      + ("（若 >0，说明 q(0) 是「该动画自己的起点」而不是共享的 rest 朝向）" if bad else "（q(0) 确实是共享的 rest 朝向）"))
