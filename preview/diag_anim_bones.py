# -*- coding: utf-8 -*-
"""定位：动画姿势下**哪些骨骼的权重顶点被甩出去**。

渲染里出现"袖子被拉成长尖刺"这种形状，说明不是平滑地整体旋转，
而是**两组顶点被分开**：跟随某根骨的顶点留在原地，跟随另一根骨的被甩到远处。
所以按"顶点的主骨骼（权重最大的那根）"分组统计位移，就能直接指出是哪根骨。

用法
----
  python diag_anim_bones.py <bl_skeleton.json> <anim.json> <mesh.npz> [t]
"""
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import anim_pose as A                      # noqa: E402
from sketch_anim_frames import load_skeleton   # noqa: E402


def main():
    skel_path, anim_path, mesh_path = sys.argv[1], sys.argv[2], sys.argv[3]
    t = float(sys.argv[4]) if len(sys.argv) > 4 else None

    rest, Rrest, parent, names, order = load_skeleton(skel_path)
    anim = json.load(open(anim_path, encoding="utf-8"))
    R0 = {i: anim["boneAnims"][i]["rot"][0]["q"] for i in order}
    Mrest = {}
    for i in order:
        m = np.eye(4)
        m[:3, :3] = Rrest[i]
        m[:3, 3] = rest[i]
        Mrest[i] = m

    d = np.load(mesh_path, allow_pickle=True)
    V = np.asarray(d["verts"], dtype=np.float64)
    idx = np.asarray(d["bone_idx"], dtype=np.int64)
    wt = np.asarray(d["bone_wt"], dtype=np.float64)
    V_arm = V @ A.C_ARM_FROM_ENG

    t_end = max(b["rot"][-1]["t"] for b in anim["boneAnims"] if b["rot"])
    if t is None:
        t = t_end / 2.0

    Ms = A.build_pose(rest, Rrest, parent, order, anim, t, R0)
    V2 = A.lbs(V_arm, idx, wt, Ms, Mrest) @ A.C_ARM_FROM_ENG.T
    disp = np.linalg.norm(V2 - V, axis=1)

    main_bone = idx[np.arange(len(idx)), np.argmax(wt, axis=1)]
    print(f"anim={anim['name']}  t={t:.0f}  verts={len(V)}  "
          f"整体 p50={np.percentile(disp,50)*1000:.1f}mm "
          f"p99={np.percentile(disp,99)*1000:.1f}mm max={disp.max()*1000:.1f}mm")
    print()
    print(f"{'bone':>4} {'name':<34} {'nverts':>7} {'p50':>8} {'p99':>9} {'max':>9}")
    print("-" * 80)
    rows = []
    for b in order:
        m = main_bone == b
        n = int(m.sum())
        if n == 0:
            rows.append((0.0, b, n, 0.0, 0.0, 0.0))
            continue
        rows.append((np.percentile(disp[m], 99), b, n,
                     np.percentile(disp[m], 50) * 1000,
                     np.percentile(disp[m], 99) * 1000,
                     disp[m].max() * 1000))
    for _, b, n, p50, p99, mx in sorted(rows, reverse=True):
        flag = "  <<<" if p99 > 200 else ""
        print(f"{b:>4} {names[b]:<34} {n:>7} {p50:8.1f} {p99:9.1f} {mx:9.1f}{flag}")

    # 位移最大的顶点，看它们到底跟了谁
    print()
    top = np.argsort(disp)[-2000:]
    print("位移最大的 2000 个顶点的主骨骼分布：")
    vals, cnts = np.unique(main_bone[top], return_counts=True)
    for v, c in sorted(zip(vals, cnts), key=lambda x: -x[1])[:10]:
        print(f"   bone {v:>3} {names[int(v)]:<34} {c:>5} 个")
    return 0


if __name__ == "__main__":
    sys.exit(main())