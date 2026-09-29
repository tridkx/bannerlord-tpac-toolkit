# -*- coding: utf-8 -*-
"""验证动画解包是否干净：四元数归一化、关键帧跳变、以及"看起来抽搐"的真正来源。"""
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

for fn in ["inventory_idle", "walk_barmaid", "inv_movements"]:
    d = json.load(open(f"anims/{fn}.json", encoding="utf-8"))
    ba = d["boneAnims"]
    print(f"\n===== {fn}  boneNum={d['boneNum']} boneAnims={len(ba)} =====")

    # ---- 1. 四元数模长 ----
    norms, bad = [], 0
    for b in ba:
        q = np.array([f["q"] for f in b["rot"]], float)
        n = np.linalg.norm(q, axis=1)
        norms.append(n)
        bad += int((np.abs(n - 1.0) > 1e-3).sum())
    alln = np.concatenate(norms)
    print(f"  [四元数] |q| min={alln.min():.6f} max={alln.max():.6f} "
          f"均值={alln.mean():.6f}  偏离1超过1e-3的帧数={bad}/{len(alln)}")

    # ---- 2. 相邻**关键帧**的旋转夹角（找跳变；这才是解包层面的硬判据） ----
    worst = []
    for b in ba:
        q = np.array([f["q"] for f in b["rot"]], float)
        if len(q) < 3:
            continue
        t = np.array([f["t"] for f in b["rot"]], float)
        dot = np.abs((q[:-1] * q[1:]).sum(1)).clip(0, 1)
        ang = np.degrees(2 * np.arccos(dot))          # 相邻关键帧转了多少度
        dt = np.diff(t)
        # 每秒的角速度（度/秒）—— 用 clip 时长换算
        spd = ang / np.maximum(dt, 1e-9)
        i = int(np.argmax(spd))
        worst.append((spd[i], names.get(b["i"], b["i"]), ang[i], dt[i], t[i]))
    worst.sort(reverse=True)
    print("  [角速度最高 5 根骨] 度/tick, 骨名, 该步转角度, dt, t")
    for w in worst[:5]:
        print(f"     {w[0]:8.2f}  {w[1]:14s} {w[2]:7.2f}°  dt={w[3]:5.0f}  t={w[4]:6.0f}")

    # ---- 3. 采样帧之间的顶点位移（真正决定"看着抽不抽"） ----
    V = np.load("D:/dsh-mod/mb-xianjian7/work/imported/yue.npz",
                allow_pickle=True)["verts"].astype(np.float64)
    idx = np.load("D:/dsh-mod/mb-xianjian7/work/imported/yue.npz",
                  allow_pickle=True)["bone_idx"]
    wt = np.load("D:/dsh-mod/mb-xianjian7/work/imported/yue.npz",
                 allow_pickle=True)["bone_wt"]
    Mrest = {}
    for i in order:
        m = np.eye(4); m[:3, :3] = Rrest[i]; m[:3, 3] = rest[i]; Mrest[i] = m
    R0 = {i: ba[i]["rot"][0]["q"] for i in order}
    t_end = max(b["rot"][-1]["t"] for b in ba if b["rot"])
    meta = json.load(open("anims/index.json", encoding="utf-8")).get(fn, {})
    t_cov = min(t_end, 48 / 15.0 * (t_end / meta["seconds"])) if meta.get("seconds") else t_end
    ts = np.linspace(0, t_cov, 48, endpoint=False)
    Varm = V @ AP.C_ARM_FROM_ENG.T
    P = []
    for t in ts:
        Ms = AP.build_pose(rest, Rrest, parent, order, d, float(t), R0)
        P.append(AP.lbs(Varm, idx, wt, Ms, Mrest) @ AP.C_ARM_FROM_ENG)
    P = np.stack(P)
    step = np.linalg.norm(np.diff(P, axis=0), axis=2)
    print(f"  [48 帧采样] 帧间顶点位移：中位 {np.median(step)*1000:.1f}mm  "
          f"p99 {np.percentile(step,99)*1000:.1f}mm  max {step.max()*1000:.1f}mm")
    # 找出跳得最狠的那一帧、以及是哪些顶点
    f = int(np.argmax(step.max(1)))
    v = int(np.argmax(step[f]))
    print(f"     最跳的一步：第 {f}->{f+1} 帧，顶点 {v} 动了 {step[f,v]*1000:.1f}mm，"
          f"权重骨={idx[v]} wt={np.round(wt[v],3)}")
