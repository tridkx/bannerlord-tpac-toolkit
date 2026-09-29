# -*- coding: utf-8 -*-
"""用解出来的旋转约定，把一段动画的若干帧骨架画出来 —— 验证时序对不对。

`solve_anim_convention.py` 用**单帧**的解剖学约束（两腿必须在 X 方向分开、
脚在地上、头最高）选出了约定，但那只能证明"静止姿势对"。
**运动对不对是另一回事** —— 走路时双腿应当交替前后摆动、手臂反向摆。
所以这里把整段动画逐帧画出来，一眼就能看出是"走路"还是"抽搐"。

用法
----
  python sketch_anim_frames.py <bl_skeleton.json> <anim.json> [n_frames] [out.png] [start]
"""
import json
import os
import sys

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import solve_anim_convention as S   # noqa: E402

BG = (18, 20, 24)
FG = (240, 240, 240)
HI = (90, 220, 140)
DIM = (140, 150, 165)
WIN_FRONT = (-0.95, 0.95, -0.15, 1.90)
WIN_SIDE = (-0.95, 0.95, -0.15, 1.90)

# 由 solve_anim_convention.py 选出的最优约定
BEST = ("conj", "none", "Rr", "R0T", "abs", "restT", "rest_then")


def load_skeleton(path):
    skel = json.load(open(path, encoding="utf-8"))
    byname = {b["name"]: b["engine_index"] for b in skel["bones"]}
    rest, Rrest, parent, names = {}, {}, {}, {}
    for src in skel["bones"]:
        ei = src["engine_index"]
        if ei is None:
            continue
        M = np.array(src["matrix_local"], float)
        rest[ei] = M[:3, 3].copy()
        Rrest[ei] = M[:3, :3].copy()
        names[ei] = src["name"]
        pn = src["parent"]
        parent[ei] = byname.get(pn) if pn else None
    return rest, Rrest, parent, names, sorted(rest)


def make_proj(cx, cy, cw, ch, win):
    umin, umax, vmin, vmax = win
    s = min(cw / (umax - umin), ch / (vmax - vmin))
    ox = cx + (cw - (umax - umin) * s) / 2.0
    oy = cy + (ch - (vmax - vmin) * s) / 2.0
    return lambda u, v: (ox + (u - umin) * s, oy + (vmax - v) * s)


def draw(d, joint, parent, cx, cy, cw, ch, view, color, win):
    proj = make_proj(cx, cy, cw, ch, win)
    for i, p in parent.items():
        if p is None or i not in joint or p not in joint:
            continue
        a, b = joint[i], joint[p]
        ua, va = (a[0], a[1]) if view == "front" else (a[2], a[1])
        ub, vb = (b[0], b[1]) if view == "front" else (b[2], b[1])
        d.line([*proj(ua, va), *proj(ub, vb)], fill=color, width=2)
    for i, j in joint.items():
        u, v = (j[0], j[1]) if view == "front" else (j[2], j[1])
        px, py = proj(u, v)
        d.ellipse([px - 2, py - 2, px + 2, py + 2], fill=color)


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    skel_path, anim_path = sys.argv[1], sys.argv[2]
    n = int(sys.argv[3]) if len(sys.argv) > 3 else 8
    out = sys.argv[4] if len(sys.argv) > 4 else os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "anim_frames.png")
    start = int(sys.argv[5]) if len(sys.argv) > 5 else 0

    rest, Rrest, parent, names, order = load_skeleton(skel_path)
    anim = json.load(open(anim_path, encoding="utf-8"))
    total = max(len(b["rot"]) for b in anim["boneAnims"])
    span = max(1, (total - start) // n)

    CW, CH = 190, 300
    img = Image.new("RGB", (CW * n, CH * 2), BG)
    d = ImageDraw.Draw(img)

    print(f"anim='{anim['name']}'  total_rot_frames={total}  showing {n} frames from {start}")
    print(f"{'frame':>6} | {'L_toe z':>8} {'R_toe z':>8} | {'L_toe y':>8} {'R_toe y':>8} | "
          f"{'L_hand z':>9} {'R_hand z':>9}")
    for k in range(n):
        f = start + k * span
        f = min(f, total - 1)
        joint, _ = S.build(rest, Rrest, parent, order, anim, f, BEST)
        d.text((k * CW + 6, 5), f"f={f}", fill=HI)
        d.text((k * CW + 6, CH + 5), "front", fill=DIM)
        d.text((k * CW + 6, CH + 19), "side", fill=DIM)
        draw(d, joint, parent, k * CW, 0, CW, CH, "front", FG, WIN_FRONT)
        draw(d, joint, parent, k * CW, CH, CW, CH, "side", DIM, WIN_SIDE)
        print(f"{f:>6} | {joint[4][2]:+8.3f} {joint[8][2]:+8.3f} | "
              f"{joint[4][1]:+8.3f} {joint[8][1]:+8.3f} | "
              f"{joint[19][2]:+9.3f} {joint[26][2]:+9.3f}")

    img.save(out)
    print("WROTE", out, img.size)
    return 0


if __name__ == "__main__":
    sys.exit(main())