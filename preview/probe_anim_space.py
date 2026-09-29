# -*- coding: utf-8 -*-
"""探针：动画四元数到底在哪个空间、相对于什么。

背景
----
`mbtool anim` 能把 SkeletalAnimation 的关键帧 dump 成 JSON，但数据里没有任何字段
说明"这根骨的四元数是①绝对朝向 还是②相对父骨的增量，以及在哪个坐标系里"。
搞错这一点的表现是**整个骨架扭成一团**，而肉眼看 JSON 完全看不出来
（分量都是 0~1 的浮点数，看起来都"很像"）。

做法
----
拿动画第 0 帧逐骨对比官方骨架的 rest 矩阵：
  act_inventory_idle 是循环 idle，第 0 帧的姿势 ≈ 静止姿势（A-pose/站姿）。
  如果四元数是"绝对朝向"，那么 R_anim · R_rest⁻¹ 在第 0 帧应**接近单位阵**；
  如果它是"相对父骨的增量"，那这个乘积会是随机大角度，而四元数本身应接近单位阵。

同时验证 boneAnims[i] 的下标 i 是否就是 BL 引擎索引（28 骨 0..27）：
  对上了 → 偏差角普遍很小；错位了 → 会出现一片随机大角度。

用法
----
  python probe_anim_space.py <bl_skeleton.json> <anim.json> [frame]
"""
import json
import math
import sys

import numpy as np


def quat_to_mat(q):
    """四元数 (x,y,z,w) -> 3x3 旋转矩阵。"""
    x, y, z, w = [float(v) for v in q]
    n = x * x + y * y + z * z + w * w
    if n < 1e-12:
        return np.eye(3)
    s = 2.0 / n
    xx, yy, zz = x * x * s, y * y * s, z * z * s
    xy, xz, yz = x * y * s, x * z * s, y * z * s
    wx, wy, wz = w * x * s, w * y * s, w * z * s
    return np.array([
        [1.0 - (yy + zz), xy - wz, xz + wy],
        [xy + wz, 1.0 - (xx + zz), yz - wx],
        [xz - wy, yz + wx, 1.0 - (xx + yy)],
    ])


def rot_angle_deg(R):
    """旋转矩阵的角度（度）。"""
    t = (np.trace(R) - 1.0) / 2.0
    return math.degrees(math.acos(max(-1.0, min(1.0, t))))


def quat_angle_deg(q):
    """四元数本身的角度（度），=|2·acos(w)|。"""
    w = abs(float(q[3]))
    return math.degrees(2.0 * math.acos(max(-1.0, min(1.0, w))))


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    skel_path, anim_path = sys.argv[1], sys.argv[2]
    frame = int(sys.argv[3]) if len(sys.argv) > 3 else 0

    skel = json.load(open(skel_path, encoding="utf-8"))
    anim = json.load(open(anim_path, encoding="utf-8"))

    # 引擎索引 -> rest 旋转（armature 空间）
    rest_rot, rest_name = {}, {}
    for b in skel["bones"]:
        ei = b["engine_index"]
        if ei is None:
            continue
        rest_rot[ei] = np.array(b["matrix_local"], float)[:3, :3]
        rest_name[ei] = b["name"]

    ba = anim["boneAnims"]
    print(f"anim='{anim['name']}'  bones={len(ba)}  skeleton='{skel.get('armature')}'")
    print(f"rest bones with engine_index: {len(rest_rot)}")
    print(f"frame={frame}")
    print()
    print("  idx  bone name                     |q|deg  D_abs=Ra*Rr^T  D_rel=Rr^T*Ra")
    print("  " + "-" * 74)

    rows = []
    for i, b in enumerate(ba):
        rot = b["rot"]
        if frame >= len(rot):
            continue
        q = rot[frame]["q"]
        Ra = quat_to_mat(q)
        Rr = rest_rot.get(i)
        if Rr is None:
            print(f"  {i:>3}  (no rest for engine_index {i})")
            continue
        D_abs = Ra @ Rr.T
        D_rel = Rr.T @ Ra
        a_abs = rot_angle_deg(D_abs)
        a_rel = rot_angle_deg(D_rel)
        rows.append((i, quat_angle_deg(q), a_abs, a_rel))
        print(f"  {i:>3}  {rest_name[i]:<30} {quat_angle_deg(q):8.2f}  "
              f"{a_abs:10.2f}      {a_rel:10.2f}")

    if rows:
        qa = np.array([r[1] for r in rows])
        aa = np.array([r[2] for r in rows])
        ar = np.array([r[3] for r in rows])
        print()
        print(f"  quat angle  : median {np.median(qa):7.2f}  mean {qa.mean():7.2f}")
        print(f"  D_abs angle : median {np.median(aa):7.2f}  mean {aa.mean():7.2f}  "
              f"max {aa.max():7.2f}")
        print(f"  D_rel angle : median {np.median(ar):7.2f}  mean {ar.mean():7.2f}  "
              f"max {ar.max():7.2f}")
        print()
        if np.median(aa) < 20.0:
            print("  => 判读：D_abs 普遍很小 —— 四元数是【绝对朝向】，")
            print("     且与 skeleton FBX 的 rest 旋转同一坐标系（armature 空间）。")
        elif np.median(ar) < 20.0:
            print("  => 判读：D_rel 普遍很小 —— 四元数是【相对父骨的增量】。")
        else:
            print("  => 判读：两者都不小 —— 坐标约定/分量顺序与 FBX 不同，")
            print("     需要再试共轭、轴交换(quat 的 y/z 对调)或分量顺序(w,x,y,z)。")
    return 0


if __name__ == "__main__":
    sys.exit(main())