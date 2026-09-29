# -*- coding: utf-8 -*-
"""暴力搜索「动画四元数 -> 骨骼世界变换」的正确约定。

为什么必须搜
------------
实测三个互不相关的动画（inventory_idle / inventory_movements / barmaid_walk_forward）
的第 0 帧，pelvis 的四元数**都是同一个 ~90° 绕 -Y**、thigh 都是 ~175°。
所有动画都带同一个值 ⇒ 它属于**骨骼 rest 朝向**，不是动画内容 ⇒
不能把四元数直接当"相对 rest 的增量"，也不能当"绝对朝向"，必须先除掉/换算 rest。

而在"不能直接看到结果"的情况下推理约定极其容易绕进去（本工程已经在
UV 的 V 轴、脚骨朝向上各栽过一次）。所以改成**枚举 + 用解剖学硬约束打分**：

判据（对走路动画，人应当是站立/迈步的）
  ① 左右大腿必须在 **X 方向分开**（≈±0.1m）—— 这是解剖学硬约束，
     任何让人"前后劈叉"的约定都是错的
  ② 最低关节应在地面附近（y≈0）
  ③ 头应是最高点，且高度在 1.45~1.78m 之间

用法
----
  python solve_anim_convention.py <bl_skeleton.json> <anim.json> [frame]
"""
import itertools
import json
import sys

import numpy as np

L_THIGH, R_THIGH, L_TOE, R_TOE, HEAD, PELVIS = 1, 5, 4, 8, 13, 0


def qmat(q, conj=False):
    x, y, z, w = [float(v) for v in q]
    if conj:
        x, y, z = -x, -y, -z
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


def apply(v, pre, post, Rr):
    """按 pre/post 把 rest 旋转 Rr 与 v 组合。"""
    if pre == "none" and post == "none":
        return v
    if pre == "RrT":
        v = Rr.T @ v
    elif pre == "Rr":
        v = Rr @ v
    if post == "RrT":
        v = v @ Rr.T
    elif post == "Rr":
        v = v @ Rr
    return v


def build(rest, Rrest, parent, order, anim, frame, cfg):
    qmode, pre, post, refmode, acc, posmode, rootmode = cfg
    ba = anim["boneAnims"]
    Wrot, joint = {}, {}
    for i in order:
        rot = ba[i]["rot"] if i < len(ba) else []
        q = rot[min(frame, len(rot) - 1)]["q"] if rot else (0.0, 0.0, 0.0, 1.0)
        Rb = apply(qmat(q, conj=(qmode == "conj")), pre, post, Rrest[i])
        if refmode != "none" and rot:
            # ★ 关键：所有动画第 0 帧的四元数都相同（pelvis 恒为 ~90° 绕 -Y）
            #   ⇒ 那是「游戏里骨骼 rest 的局部朝向」，不是姿势。
            #   于是先用 R0 = q(0) 除掉它，剩下的才是真正的姿态增量。
            R0 = qmat(rot[0]["q"], conj=(qmode == "conj"))
            Rb = (R0.T @ Rb) if refmode == "R0T" else (Rb @ R0.T)
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
    return joint, Wrot


def score(joint):
    a = np.array(list(joint.values()), float)
    if not np.isfinite(a).all():
        return 1e9, {}
    legs_dx = abs(joint[L_THIGH][0] - joint[R_THIGH][0])
    legs_dz = abs(joint[L_THIGH][2] - joint[R_THIGH][2])
    min_y = a[:, 1].min()
    head_y = joint[HEAD][1]
    top_y = a[:, 1].max()

    s = 0.0
    s += 4.0 * abs(legs_dx - 0.20)          # 左右大腿在 X 分开
    s += 4.0 * legs_dz                       # 不该前后劈叉
    s += 3.0 * abs(min_y)                    # 最低点在脚底(0)
    s += 3.0 * max(0.0, head_y - 1.78)       # 头不该冒顶
    s += 3.0 * max(0.0, 1.45 - head_y)       # 头不该缩进去
    s += 2.0 * max(0.0, abs(top_y - head_y) - 0.02)  # 头应是最高点
    return s, {"legs_dx": legs_dx, "legs_dz": legs_dz, "min_y": min_y,
               "head_y": head_y, "top_y": top_y, "height": top_y - min_y}


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    skel_path, anim_path = sys.argv[1], sys.argv[2]
    frame = int(sys.argv[3]) if len(sys.argv) > 3 else None

    skel = json.load(open(skel_path, encoding="utf-8"))
    anim = json.load(open(anim_path, encoding="utf-8"))

    byname = {b["name"]: b["engine_index"] for b in skel["bones"]}
    rest, Rrest, parent = {}, {}, {}
    for src in skel["bones"]:
        ei = src["engine_index"]
        if ei is None:
            continue
        M = np.array(src["matrix_local"], float)
        rest[ei] = M[:3, 3].copy()
        Rrest[ei] = M[:3, :3].copy()
        pn = src["parent"]
        parent[ei] = byname.get(pn) if pn else None
    order = sorted(rest)

    if frame is None:
        frame = len(anim["boneAnims"][0]["rot"]) // 2

    grid = list(itertools.product(
        ["asis", "conj"],            # qmode
        ["none", "RrT", "Rr"],       # pre
        ["none", "RrT", "Rr"],       # post
        ["none", "R0T", "R0T_post"], # refmode：先除掉 rest 局部朝向
        ["local", "abs"],            # acc
        ["plain", "restT"],          # posmode
        ["raw", "rest_then"],        # rootmode
    ))

    results = []
    for cfg in grid:
        j, _ = build(rest, Rrest, parent, order, anim, frame, cfg)
        s, info = score(j)
        results.append((s, cfg, info))
    results.sort(key=lambda x: x[0])

    print(f"anim='{anim['name']}'  frame={frame}  ({len(grid)} combos)")
    print()
    print(f"{'score':>8}  {'qmode':<5} {'pre':<5} {'post':<5} {'ref':<9} {'acc':<6} "
          f"{'posmode':<6} {'root':<10} | legs_dx legs_dz min_y  head_y height")
    print("-" * 122)
    for s, cfg, info in results[:16]:
        if not info:
            continue
        print(f"{s:8.3f}  {cfg[0]:<5} {cfg[1]:<5} {cfg[2]:<5} {cfg[3]:<9} {cfg[4]:<6} "
              f"{cfg[5]:<6} {cfg[6]:<10} | {info['legs_dx']:7.3f} {info['legs_dz']:7.3f} "
              f"{info['min_y']:+6.3f} {info['head_y']:7.3f} {info['height']:6.3f}")
    print()
    best = results[0]
    if best[0] < 1.0:
        print("=> 有明确解：", best[1], " score", round(best[0], 3))
    else:
        print("=> 没有干净解，最优 score =", round(best[0], 3))
    return 0


if __name__ == "__main__":
    sys.exit(main())