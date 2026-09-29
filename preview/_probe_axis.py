# -*- coding: utf-8 -*-
"""验证旋转轴是否符合解剖学：
  走路时大腿 = 绕左右轴(X)前后摆；前臂扭转骨 = 绕自身长轴扭转。
若轴跑到别处，视觉上就是"肘关节一直在转""腿左右扭"。"""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass
import numpy as np
import anim_pose as AP
import solve_anim_convention as S
from sketch_anim_frames import load_skeleton

rest, Rrest, parent, names, order = load_skeleton("bl_skeleton.json")
COORD = AP.COORD

def axis_angle(R):
    tr = np.trace(R)
    ang = np.degrees(np.arccos(max(-1.0, min(1.0, (tr - 1) / 2))))
    if ang < 1e-6:
        return ang, np.zeros(3)
    ax = np.array([R[2,1]-R[1,2], R[0,2]-R[2,0], R[1,0]-R[0,1]])
    n = np.linalg.norm(ax)
    return ang, (ax/n if n > 1e-9 else np.zeros(3))

def bone_axis_eng(i):
    """骨轴（指向子骨）在游戏空间的近似方向：用 rest 里该骨与其子骨的向量"""
    kids = [k for k in order if parent[k] == i]
    if not kids:
        return None
    v = rest[kids[0]] - rest[i]
    n = np.linalg.norm(v)
    return v/n if n > 1e-9 else None

def report(fn, ids, label):
    d = json.load(open(f"anims/{fn}.json", encoding="utf-8"))
    R0 = {i: d["boneAnims"][i]["rot"][0]["q"] for i in order}
    t_end = max(b["rot"][-1]["t"] for b in d["boneAnims"] if b["rot"])
    print(f"\n===== {fn}：{label}")
    print(f"  {'骨名':28s} {'最大角':>7}  旋转轴(游戏空间)         骨轴(指向子骨)        夹角")
    for i in ids:
        ts = np.linspace(1, t_end, 40, endpoint=False)
        best = (0, None)
        for t in ts:
            q = AP.sample_rot(d["boneAnims"][i]["rot"], float(t))
            R = S.qmat(q) @ S.qmat(R0[i], conj=True)
            a, ax = axis_angle(R)
            if a > best[0]:
                best = (a, ax)
        a, ax = best
        ba = bone_axis_eng(i)
        # 把"游戏空间的骨轴"拿来比：骨轴也要乘 COORD 才是 armature；这里两边都留在游戏空间
        if ba is None or ax is None:
            print(f"  {names.get(i,'?'):28s} {a:7.1f}  （无子骨，跳过）")
            continue
        cos = abs(float(np.dot(ax, ba)))
        ang = np.degrees(np.arccos(min(1.0, cos)))
        tag = "  ← 与骨轴重合（扭转，可能正常）" if ang < 25 else \
              ("  ← 与骨轴垂直（弯曲，正常）" if ang > 65 else "  ← 斜交，可疑")
        print(f"  {names.get(i,'?'):28s} {a:7.1f}  [{ax[0]:+.2f} {ax[1]:+.2f} {ax[2]:+.2f}]  "
              f"[{ba[0]:+.2f} {ba[1]:+.2f} {ba[2]:+.2f}]  {ang:5.1f}°{tag}")

report("walk_barmaid", [1, 5, 2, 6, 17, 18, 24], "大腿应绕左右轴摆；扭转骨应绕骨轴")
report("inventory_idle", [17, 18, 24, 15, 22, 19, 26, 1, 2], "待机时肘/前臂应几乎不动")
