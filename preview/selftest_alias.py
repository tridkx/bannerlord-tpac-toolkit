# -*- coding: utf-8 -*-
"""验证"抽"是采样率不足（混叠）：同样的动画，不同的采样密度，
看**逐帧最大位移**怎么变 —— 采样越密，每帧位移越小、画面越顺。"""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass
import numpy as np
import anim_pose as AP
from sketch_anim_frames import load_skeleton

P = Path(__import__("os").environ.get("MB_POSED", "work_imported"))
rest, Rrest, parent, names, order = load_skeleton("bl_skeleton.json")
Mrest = {}
for i in order:
    m = np.eye(4); m[:3, :3] = Rrest[i]; m[:3, 3] = rest[i]; Mrest[i] = m
Minv = {i: np.linalg.inv(Mrest[i]) for i in order}
z = np.load(P / "yue.npz", allow_pickle=True)   # 可用 MB_POSED 指定目录
V = z["verts"].astype(np.float64); bi = z["bone_idx"]; bw = z["bone_wt"]
Varm = V @ AP.C_ARM_FROM_ENG.T

d = json.load(open("anims/inventory_idle.json", encoding="utf-8"))
R0 = {i: d["boneAnims"][i]["rot"][0]["q"] for i in order}
meta = json.load(open("anims/index.json", encoding="utf-8"))["inventory_idle"]
tpsec = meta["tEnd"] / meta["seconds"]

print(f"{'帧数':>5} {'fps':>6} {'覆盖':>7} {'每帧跨t':>8} | "
      f"{'逐帧位移中位':>12} {'p99':>8} {'max':>8}  (mm)")
for nf, fps in ((48, 15), (48, 30), (48, 60), (96, 60), (48, 84.5)):
    t_beg = 1
    span = nf / fps * tpsec
    ts = np.linspace(t_beg, t_beg + span, nf, endpoint=False)
    Pp = []
    for t in ts:
        Ms = AP.build_pose(rest, Rrest, parent, order, d, float(t), R0)
        Pp.append(AP.lbs(Varm, bi, bw, Ms, Mrest,
                         mats=AP.pose_matrices(Ms, Mrest, Minv)) @ AP.C_ARM_FROM_ENG)
    Pp = np.stack(Pp)
    st = np.linalg.norm(np.diff(Pp, axis=0), axis=2) * 1000
    print(f"{nf:5d} {fps:6.1f} {nf/fps:6.2f}s {span/nf:8.2f} | "
          f"{np.median(st):12.1f} {np.percentile(st,99):8.1f} {st.max():8.1f}")
print("\n（'每帧跨 t' 越小 = 采样越密；max 随之下降说明原来是在混叠，不是动画本身在抖）")
