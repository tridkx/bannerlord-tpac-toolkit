# -*- coding: utf-8 -*-
"""待机动作在预览器里"抽"—— 逐帧查最坏情况，并定位是哪根骨在抖。"""
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
Mrest = {}
for i in order:
    m = np.eye(4); m[:3, :3] = Rrest[i]; m[:3, 3] = rest[i]; Mrest[i] = m
Minv = {i: np.linalg.inv(Mrest[i]) for i in order}

d = json.load(open("anims/inventory_idle.json", encoding="utf-8"))
idx = json.load(open("anims/index.json", encoding="utf-8"))["inventory_idle"]
t_end, sec = d["boneAnims"][0]["rot"][-1]["t"], idx["seconds"]
tpsec = t_end / sec
nframes = 48
t_beg = 1                                   # 已跳过 rest 帧
keep = nframes / 15.0
ts = np.linspace(t_beg, t_beg + keep * tpsec, nframes, endpoint=False)
print(f"采样：{nframes} 帧，t={ts[0]:.0f}..{ts[-1]:.0f}，"
      f"覆盖 {keep:.2f}s，播放 {nframes/keep:.1f} fps，每帧跨 {ts[1]-ts[0]:.2f} 个 t")

R0 = {i: d["boneAnims"][i]["rot"][0]["q"] for i in order}
M = {}
for t in ts:
    M[float(t)] = AP.build_pose(rest, Rrest, parent, order, d, float(t), R0)

# ---- 1. 每根骨的**关节**逐帧位移（最能说明"哪根骨在跳"） ----
J = np.stack([np.array([M[float(t)][i][:3, 3] for i in order]) @ AP.C_ARM_FROM_ENG
              for t in ts])                       # (F, nb, 3)
stepJ = np.linalg.norm(np.diff(J, axis=0), axis=2)  # (F-1, nb)
mm = stepJ * 1000
print(f"\n关节逐帧位移（mm）：全骨 中位 {np.median(mm):.2f}  p99 {np.percentile(mm,99):.2f}  max {mm.max():.2f}")
per_bone = mm.max(0)                            # 每根骨的最坏帧
top = np.argsort(per_bone)[::-1][:8]
print("最抖的 8 根骨（最大单帧位移 mm）：")
for k in top:
    i = order[k]
    print(f"   {names.get(i,'?'):30s} id={i:2d}  max {per_bone[k]:7.2f}mm  "
          f"中位 {np.median(mm[:,k]):6.2f}mm")

# ---- 2. 顶点层面的最坏帧（用实际网格） ----
z = np.load(P / "yue.npz", allow_pickle=True)
V = z["verts"].astype(np.float64); bi = z["bone_idx"]; bw = z["bone_wt"]
Varm = V @ AP.C_ARM_FROM_ENG.T
Pp = []
for t in ts:
    Ms = M[float(t)]
    Pp.append(AP.lbs(Varm, bi, bw, Ms, Mrest, mats=AP.pose_matrices(Ms, Mrest, Minv))
              @ AP.C_ARM_FROM_ENG)
Pp = np.stack(Pp)
step = np.linalg.norm(np.diff(Pp, axis=0), axis=2) * 1000
print(f"\n顶点逐帧位移（mm）：中位 {np.median(step):.1f}  p99 {np.percentile(step,99):.1f}  max {step.max():.1f}")
print("逐帧最大值序列（mm）：")
print("   " + " ".join(f"{v:5.0f}" for v in step.max(1)[:24]))
print("   " + " ".join(f"{v:5.0f}" for v in step.max(1)[24:]))

# ---- 3. 是不是"来回抖"？看某根骨的角度序列有没有高频往复 ----
worst = order[int(top[0])]
qs = np.array([AP.sample_rot(d["boneAnims"][worst]["rot"], float(t)) for t in ts])
dots = np.abs((qs[:-1] * qs[1:]).sum(1)).clip(0, 1)
ang = np.degrees(2 * np.arccos(dots))
print(f"\n最抖的骨（{names.get(worst)}）逐帧转角（度）：")
print("   " + " ".join(f"{a:5.2f}" for a in ang[:24]))
sign = np.sign(np.diff(ang))
flips = int((np.diff(sign) != 0).sum())
print(f"   相邻帧转角的正负翻转次数 = {flips} / {len(ang)-1}"
      f"  -> {'★ 高频往复（在抖）' if flips > len(ang)*0.5 else '单调变化（正常）'}")
