# -*- coding: utf-8 -*-
"""对照 bai 与 yue 的头发数据：法线朝向/量级、UV、面数、材质。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass
import numpy as np
P = Path("D:/dsh-mod/mb-xianjian7/work/imported")
for ch in ("bai", "yue"):
    z = np.load(P / f"{ch}.npz", allow_pickle=True)
    V = z["verts"]; N = z["normals"]; F = z["faces"]; FG = z["face_group"]
    mats = list(z["materials"]) if "materials" in z else []
    print(f"\n===== {ch}: {len(V)} 顶点 {len(F)} 面")
    ln = np.linalg.norm(N, axis=1)
    print(f"  法线模长：均值 {ln.mean():.4f}  最小 {ln.min():.4f}  最大 {ln.max():.4f}  "
          f"|n|<0.5 的顶点 {int((ln<0.5).sum())}")
    print(f"  法线 z 分量：>0 占 {(N[:,2]>0.1).mean()*100:.1f}%  <-0.1 占 {(N[:,2]<-0.1).mean()*100:.1f}%")
    for gi, m in enumerate(mats):
        gname = m if isinstance(m, str) else str(m)
        if "hair" in gname.lower() or "lash" in gname.lower():
            sel = FG == gi
            if not sel.sum():
                continue
            fi = F[sel]
            vi = np.unique(fi)
            n = N[vi]
            ln2 = np.linalg.norm(n, axis=1)
            # 绕序：面法线与顶点法线是否一致
            a, b, c = V[fi[:,0]], V[fi[:,1]], V[fi[:,2]]
            fn = np.cross(b-a, c-a)
            fn /= (np.linalg.norm(fn, axis=1, keepdims=True) + 1e-12)
            vn = N[fi].mean(1)
            vn /= (np.linalg.norm(vn, axis=1, keepdims=True) + 1e-12)
            agree = (np.einsum("ij,ij->i", fn, vn) > 0).mean() * 100
            print(f"  [{gi:2d}] {gname:28s} 面 {sel.sum():6d} 顶点 {len(vi):6d}  "
                  f"法线模长 {ln2.mean():.3f}  面法线↔顶点法线同向 {agree:5.1f}%")
