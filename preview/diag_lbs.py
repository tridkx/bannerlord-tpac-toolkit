# -*- coding: utf-8 -*-
"""用**真实网格的顶点位移**当判据，判定哪一组动画约定是对的。

为什么需要它
------------
`solve_anim_convention.py` 只用了几根骨的**位置**（两腿分开、脚在地上、头最高）当判据。
那个判据有两个盲区：
  ① 用 abs() 取绝对值 ⇒ 看不到"左右翻转"；
  ② 完全不看**旋转** ⇒ 骨段长度照样守恒、关节照样在对的地方，但权重顶点的
     **旋转方向反了**，渲染出来就是"袖子被拉成长尖刺、头发甩到一边"。
实测踩到：把世界增量写成 `R(q0)·R(qt)ᵀ`（转置）而不是 `R(qt)·R(q0)ᵀ`，
pelvis 的 LBS 旋转从 4° 变成 32°、平移 0.51m —— 骨骼图上完全看不出来。

判据（两阶段，都是硬约束）
  ① t=0（动画第 0 帧就是绑定姿势）：顶点位移必须为 **0**
  ② t=mid：位移的 p99 必须小，且 **p99/p50 比值**要小
     （孤立的尖刺会把比值拉大 —— 正常姿势是平滑的整体运动）

用法
----
  python diag_lbs.py <bl_skeleton.json> <anim.json> <mesh.npz> [tag]
"""
import itertools
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import anim_pose as A                      # noqa: E402
from sketch_anim_frames import load_skeleton   # noqa: E402

C = A.C_ARM_FROM_ENG          # arm = C @ eng


def build2(rest, Rrest, parent, order, anim, t, R0, cfg):
    """通用骨骼求解：直接枚举"增量方向 / 坐标系 / 累积方式"。"""
    dmod, coord, acc, posmode, rootmode = cfg
    ba = anim["boneAnims"]
    Wrot, joint = {}, {}
    for i in order:
        rot = ba[i]["rot"] if i < len(ba) else []
        q = A.sample_rot(rot, t)
        D = A.S.qmat(q, conj=False) @ A.S.qmat(R0[i], conj=True)   # 世界增量
        if coord == "eng2arm":
            D = C @ D @ C.T
        elif coord == "arm2eng":
            D = C.T @ D @ C
        if dmod == "A_T":
            D = D.T
        Rb = D @ Rrest[i]
        p = parent[i]
        if p is None or p not in joint:
            Wrot[i] = Rrest[i] @ Rb if rootmode == "rest_then" else Rb
            joint[i] = rest[i].copy()
            continue
        Wp = Wrot[p]
        Wrot[i] = (Wp @ Rb) if acc == "local" else Rb
        d = rest[i] - rest[p]
        if posmode == "restT":
            d = Rrest[p].T @ d
        joint[i] = joint[p] + Wp @ d

    M = {}
    for i in order:
        m = np.eye(4)
        m[:3, :3] = Wrot[i]
        m[:3, 3] = joint[i]
        M[i] = m
    return M


def candidates():
    return list(itertools.product(
        ["A", "A_T"],                        # 增量方向
        ["arm", "eng2arm", "arm2eng"],       # q 所在的坐标系
        ["abs", "local"],                    # 旋转是否沿骨链累积
        ["plain", "restT"],                  # 关节偏移是否用父骨 rest 旋转
        ["raw", "rest_then"],                # 根骨是否多乘自身 rest
    ))


def main():
    skel_path, anim_path, mesh_path = sys.argv[1], sys.argv[2], sys.argv[3]
    tag = sys.argv[4] if len(sys.argv) > 4 else "mesh"

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
    F = np.asarray(d["faces"], dtype=np.int64)
    V_arm = V @ C.T
    A0 = tri_area(V, F)

    t_end = max(b["rot"][-1]["t"] for b in anim["boneAnims"] if b["rot"])
    ts = [0, t_end / 2.0]

    print(f"mesh={tag} verts={len(V)} faces={len(F)}  anim={anim['name']}  "
          f"t_end={t_end:.0f}  候选={len(candidates())}")
    print("判据：★三角面积比 p99 —— 「尖刺」的本质是三角形被拉长，")
    print("      顶点位移大不一定错（角色真转身也会大），面积爆炸一定是错。")
    print()
    print(f"{'dmod':<5} {'coord':<8} {'acc':<6} {'pos':<6} {'root':<10} | "
          f"{'t=0 °':>7} | {'area p50':>9} {'area p99':>9} {'area max':>10} | {'disp p50':>9}")
    print("-" * 128)

    rows = []
    for cfg in candidates():
        area_ratio, disp = None, None
        for t in ts:
            Ms = build2(rest, Rrest, parent, order, anim, t, R0, cfg)
            V2 = A.lbs(V_arm, idx, wt, Ms, Mrest) @ C
            if t == 0:
                disp0 = np.linalg.norm(V2 - V, axis=1)
            else:
                area_ratio = tri_area(V2, F) / np.maximum(A0, 1e-12)
                disp = np.linalg.norm(V2 - V, axis=1)
        rows.append((disp0, area_ratio, disp, cfg))

    rows.sort(key=lambda r: (0 if r[0].max() * 1000 < 0.5 else 1,
                             np.percentile(r[1], 99)))
    for d0, ar, dp, cfg in rows:
        print(f"{cfg[0]:<5} {cfg[1]:<8} {cfg[2]:<6} {cfg[3]:<6} {cfg[4]:<10} | "
              f"{d0.max()*1000:6.2f}m | {np.percentile(ar,50):9.3f} "
              f"{np.percentile(ar,99):9.3f} {ar.max():10.2f} | {np.percentile(dp,50)*1000:8.1f}")

    ok = [r for r in rows if r[0].max() * 1000 < 0.5]
    print()
    if not ok:
        print("=> 没有任何组合能在 t=0 精确还原绑定姿势。")
    else:
        best = min(ok, key=lambda r: np.percentile(r[1], 99))
        print(f"=> t=0 能还原的组合 {len(ok)} 个；三角形拉伸最小的是 {best[3]}")
        print(f"   area p99={np.percentile(best[1],99):.3f}  max={best[1].max():.2f}  "
              f"disp p50={np.percentile(best[2],50)*1000:.1f}mm")
    return 0


def tri_area(V, F):
    a, b, c = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
    return 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1)


if __name__ == "__main__":
    sys.exit(main())