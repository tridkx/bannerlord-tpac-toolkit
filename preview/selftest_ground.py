# -*- coding: utf-8 -*-
"""站立待机时**脚底必须贴地** —— 这是最硬的几何判据。
若脚底 z 在 0 与十几厘米之间来回跳，说明脚在抬落（待机不该），
也说明姿势幅度确实被放大了。"""
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
print(f"绑定姿势：脚底最低 z = {V[:,2].min()*1000:+.1f}mm（应≈0）")

for fn in ("inventory_idle", "walk_barmaid"):
    d = json.load(open(f"anims/{fn}.json", encoding="utf-8"))
    R0 = {i: d["boneAnims"][i]["rot"][0]["q"] for i in order}
    t_end = max(b["rot"][-1]["t"] for b in d["boneAnims"] if b["rot"])
    ts = np.linspace(1, t_end, 36, endpoint=False)
    lows, hips = [], []
    for t in ts:
        Ms = AP.build_pose(rest, Rrest, parent, order, d, float(t), R0)
        Pp = AP.lbs(Varm, bi, bw, Ms, Mrest,
                    mats=AP.pose_matrices(Ms, Mrest, Minv)) @ AP.C_ARM_FROM_ENG
        lows.append(Pp[:, 2].min())
        hips.append(Ms[0][:3, 3] @ AP.C_ARM_FROM_ENG)
    lows = np.array(lows) * 1000
    hips = np.array(hips)
    print(f"\n===== {fn}（{len(ts)} 帧）")
    print(f"  脚底最低点 z：min {lows.min():+7.1f}  max {lows.max():+7.1f}  "
          f"范围 {lows.max()-lows.min():6.1f}mm")
    print(f"  骨盆位置范围：x {((hips[:,0].max()-hips[:,0].min())*1000):5.1f}  "
          f"y {((hips[:,1].max()-hips[:,1].min())*1000):5.1f}  "
          f"z {((hips[:,2].max()-hips[:,2].min())*1000):5.1f} mm")
    if fn == "inventory_idle":
        verdict = "★ 脚底在离地/落地之间来回（待机不该）" if lows.max()-lows.min() > 30 \
                  else "脚底基本贴地 ✓"
        print(f"  -> {verdict}")
