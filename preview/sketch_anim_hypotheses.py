# -*- coding: utf-8 -*-
"""把「动画四元数怎么用」的几种假设各画一张骨架图，肉眼选对的那个。

为什么需要它
------------
`probe_anim_space.py` 显示：动画第 0 帧里多数骨的四元数**接近单位**
（spine/spine1/spine2 = 0.00°，calf 3.08°，head 0.51°），少数是整齐的
90°/180°（pelvis 90.08°，thigh 175.43°，clavicle 179.97°，toe0 90.00°）。
"整齐"说明这不是噪声，而是**骨骼局部轴约定**的差异 —— 但光看角度分不出
"绝对朝向"还是"局部增量"，也算不出坐标系。纯推理容易绕进去
（本工程已经在 UV 的 V 轴、脚骨朝向上各栽过一次），所以直接把结果画出来：
对的那一个会是一个**站立的、比例正常的人形**。

所有格子共用同一个世界窗口，所以"错的假设"会直接表现为**跑到画外看不见**，
而不是各自自动取景后看起来都挺像。

用法
----
  python sketch_anim_hypotheses.py <bl_skeleton.json> <anim.json> [frame] [out.png]
"""
import json
import os
import sys

import numpy as np
from PIL import Image, ImageDraw

BG = (18, 20, 24)
FG = (240, 240, 240)
HI = (90, 220, 140)
DIM = (130, 140, 155)

# 世界窗口（米）：u 是水平轴，v 是高度轴（armature 空间是 Y-up）
WIN_FRONT = (-1.10, 1.10, -0.15, 2.05)   # u=x, v=y
WIN_SIDE = (-1.10, 1.10, -0.15, 2.05)    # u=z, v=y


def quat_to_mat(q):
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


def to_mat(q, mode):
    x, y, z, w = [float(v) for v in q]
    if mode == "wxyz":
        q = (y, z, w, x)
    elif mode == "swap_yz":
        q = (x, z, y, w)
    elif mode == "conj":
        q = (-x, -y, -z, w)
    elif mode == "swap_yz_conj":
        q = (-x, -z, -y, w)
    return quat_to_mat(q)


def build_pose(bones, anim, frame, acc_mode, qmode):
    """返回 {engine_index: 关节世界位置}。bones 已按引擎索引升序（父索引 < 子索引）。"""
    rest = {b["i"]: b["rest"] for b in bones}
    parent = {b["i"]: b["parent"] for b in bones}
    order = sorted(rest)

    ba = anim["boneAnims"]
    acc, joint = {}, {}
    for i in order:
        rot = ba[i]["rot"] if i < len(ba) else []
        q = rot[min(frame, len(rot) - 1)]["q"] if rot else (0.0, 0.0, 0.0, 1.0)
        Rl = to_mat(q, qmode)
        p = parent[i]
        if p is None or p not in joint:
            acc[i] = Rl
            joint[i] = rest[i].copy()
        else:
            Rp = acc[p]
            acc[i] = (Rp @ Rl) if acc_mode == "local" else Rl
            joint[i] = joint[p] + Rp @ (rest[i] - rest[p])
    return joint, parent


def make_proj(cx, cy, cw, ch, win):
    umin, umax, vmin, vmax = win
    s = min(cw / (umax - umin), ch / (vmax - vmin))
    ox = cx + (cw - (umax - umin) * s) / 2.0
    oy = cy + (ch - (vmax - vmin) * s) / 2.0

    def proj(u, v):
        return ox + (u - umin) * s, oy + (vmax - v) * s
    return proj


def draw_pose(d, joint, parent, cx, cy, cw, ch, view, color, win, width=2):
    proj = make_proj(cx, cy, cw, ch, win)
    for i, p in parent.items():
        if p is None or p not in joint or i not in joint:
            continue
        a, b = joint[i], joint[p]
        ua, va = (a[0], a[1]) if view == "front" else (a[2], a[1])
        ub, vb = (b[0], b[1]) if view == "front" else (b[2], b[1])
        d.line([*proj(ua, va), *proj(ub, vb)], fill=color, width=width)
    for i, j in joint.items():
        u, v = (j[0], j[1]) if view == "front" else (j[2], j[1])
        px, py = proj(u, v)
        d.ellipse([px - 2, py - 2, px + 2, py + 2], fill=color)


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    skel_path, anim_path = sys.argv[1], sys.argv[2]
    frame = int(sys.argv[3]) if len(sys.argv) > 3 else 0
    out = sys.argv[4] if len(sys.argv) > 4 else os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "anim_hypotheses.png")

    skel = json.load(open(skel_path, encoding="utf-8"))
    anim = json.load(open(anim_path, encoding="utf-8"))

    byname = {b["name"]: b["engine_index"] for b in skel["bones"]}
    bones = []
    for src in skel["bones"]:
        ei = src["engine_index"]
        if ei is None:
            continue
        m = np.array(src["matrix_local"], float)
        pn = src["parent"]
        bones.append({
            "i": ei,
            "name": src["name"],
            "parent": byname.get(pn) if pn else None,
            "rest": m[:3, 3].copy(),      # 关节位置 = rest 矩阵的平移列
        })
    bones.sort(key=lambda x: x["i"])
    parent = {b["i"]: b["parent"] for b in bones}
    rest = {b["i"]: b["rest"] for b in bones}

    variants = [
        ("REST (no anim)", None, None),
        ("local acc / q as-is", "local", "asis"),
        ("abs / q as-is", "abs", "asis"),
        ("local acc / swap yz", "local", "swap_yz"),
        ("local acc / conj", "local", "conj"),
        ("local acc / wxyz", "local", "wxyz"),
    ]

    CW, CH = 250, 320
    img = Image.new("RGB", (CW * len(variants), CH * 2), BG)
    d = ImageDraw.Draw(img)

    for col, (title, acc_mode, qmode) in enumerate(variants):
        if acc_mode is None:
            joint = dict(rest)
        else:
            joint, _ = build_pose(bones, anim, frame, acc_mode, qmode)

        arr = np.array(list(joint.values()), float)
        bad = not np.isfinite(arr).all()
        bb = "" if bad else (f"x[{arr[:,0].min():+.2f},{arr[:,0].max():+.2f}] "
                             f"y[{arr[:,1].min():+.2f},{arr[:,1].max():+.2f}] "
                             f"z[{arr[:,2].min():+.2f},{arr[:,2].max():+.2f}]")

        x0 = col * CW
        draw_pose(d, joint, parent, x0, 0, CW, CH, "front", FG, WIN_FRONT)
        draw_pose(d, joint, parent, x0, CH, CW, CH, "side", DIM, WIN_SIDE)

        d.text((x0 + 6, 5), title, fill=HI)
        d.text((x0 + 6, CH + 5), "front (X-Y)", fill=DIM)
        d.text((x0 + 6, CH + 19), "side (Z-Y)", fill=DIM)
        d.text((x0 + 6, CH - 16), ("NaN!" if bad else bb), fill=(230, 120, 120))

    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    img.save(out)
    print("WROTE", out, img.size, "frame", frame)
    for col, (title, acc_mode, qmode) in enumerate(variants):
        if acc_mode is None:
            continue
        j, _ = build_pose(bones, anim, frame, acc_mode, qmode)
        a = np.array(list(j.values()), float)
        if not np.isfinite(a).all():
            print(f"  {title:<24} NaN")
            continue
        print(f"  {title:<24} height={a[:,1].max()-a[:,1].min():.3f}  "
              f"feet_y={min(j[4][1], j[8][1]):+.3f}  head_y={j[13][1]:+.3f}  "
              f"span_x={a[:,0].max()-a[:,0].min():.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())