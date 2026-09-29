# -*- coding: utf-8 -*-
"""把**游戏自带的骨骼动画**套到皮套网格上，逐帧写出 npz —— 带动画的离线预览。

为什么需要它
------------
原先的离线预览（`pose_test.py`）只能套**自己手写的合成姿势**（walk/knee/stride），
所以"预览图跟游戏内表现对不上"—— 手的角度、裙摆的摆动、肩胯的相对关系
全是猜的。而游戏里真正播的是 `inventory_idle` 这类动画。
既然 `mbtool anim` 已经能把它们 dump 出来（见 `solve_anim_convention.py` 解出的旋转约定），
就应当直接拿真动画来套。

坐标
----
网格顶点在**引擎空间**（Z-up、+Y 前、+X 右）；官方骨架 FBX 是 **armature 空间**（Y-up）。
本脚本全程在 armature 空间做 LBS，只在进出口各转一次：
    arm = C @ engine,  C = [[1,0,0],[0,0,-1],[0,1,0]]
这样动画四元数不用动（它就是在 armature 空间表达的）。

用法
----
  python anim_pose.py --skeleton bl_skeleton.json --anim inventory_idle.json \
      --src <proj>/work/posed --out <proj>/work/anim_idle --nframes 12 [--start 0]
产出 <out>/f000/<tag>.npz ... ，之后用 render.py --mode=anim_idle/f000 渲染。
"""
import argparse
import json
import os
import sys

import numpy as np

# ★ 控制台默认是中文 GBK(936)：本脚本 print 中文，不钉死编码会 UnicodeEncodeError 崩掉。
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import solve_anim_convention as S          # noqa: E402
from sketch_anim_frames import load_skeleton   # noqa: E402

# 由 solve_anim_coord2.py 穷举（24 个坐标 × 增量方向 × 累积公式）选出的解。
# 判据是「网格边长拉伸」：修正坐标变换的转置之后，p999 从 20.9 降到 1.79（正常）。
# 全部前 16 名都是 abs（旋转不沿骨链累积）—— 说明游戏存的就是**世界空间**的
# 绝对朝向，每根骨的增量已经包含了父链的贡献，再累积一次反而会重复旋转。
COORD = np.array([[0.0, 0.0, 1.0],
                  [0.0, -1.0, 0.0],
                  [1.0, 0.0, 0.0]])

# arm <- engine 的坐标变换（列约定 arm = C @ eng；行向量约定下要右乘 Cᵀ）
C_ARM_FROM_ENG = np.array([[1.0, 0.0, 0.0],
                           [0.0, 0.0, 1.0],
                           [0.0, -1.0, 0.0]])


def slerp(q0, q1, u):
    a = np.asarray(q0, dtype=np.float64)
    b = np.asarray(q1, dtype=np.float64)
    d = float(np.dot(a, b))
    if d < 0.0:
        b = -b
        d = -d
    if d > 0.9995:
        q = a + u * (b - a)
    else:
        th = np.arccos(max(-1.0, min(1.0, d)))
        q = (np.sin((1.0 - u) * th) * a + np.sin(u * th) * b) / np.sin(th)
    n = np.linalg.norm(q)
    return q / n if n > 1e-12 else np.array([0.0, 0.0, 0.0, 1.0])


def sample_rot(rot, t):
    """★ 按**时间 t** 取关键帧（带 slerp），不能按数组下标。

    实测 inventory_idle 各骨的旋转帧数并不相同（1256 / 1258 / 1268），
    所以"第 k 个元素 == 第 k 帧"这个假设是错的 —— 按下标取会让姿势整体错位。
    """
    if not rot:
        return (0.0, 0.0, 0.0, 1.0)
    ts = [f["t"] for f in rot]
    i = int(np.searchsorted(ts, t, side="right")) - 1
    if i < 0:
        return rot[0]["q"]
    if i >= len(rot) - 1:
        return rot[-1]["q"]
    t0, t1 = ts[i], ts[i + 1]
    if t1 <= t0:
        return rot[i]["q"]
    return slerp(rot[i]["q"], rot[i + 1]["q"], (t - t0) / (t1 - t0))


def build_pose(rest, Rrest, parent, order, anim, t, R0):
    """返回 {engine_index: (4x4 骨骼世界矩阵)}，armature 空间。

    模型：q_i(t) 是骨骼 i 在**游戏模型空间**的绝对朝向；q_i(0) 是所有动画共有的
    那个"骨骼 rest 朝向"（pelvis 恒为 ~90° 绕 -Y）。除掉它得到世界增量
        Δ_i = R(q_i(t)) · R(q_i(0))⁻¹
    再把 Δ 从游戏空间换到 armature 空间（COORD 共轭），右乘到 rest 朝向上：
        W_i = Δ_i · Rrest_i
    Δ 已经包含父链贡献，所以**不再沿链累积**（abs）。
    """
    ba = anim["boneAnims"]
    Wrot, joint = {}, {}
    for i in order:
        rot = ba[i]["rot"] if i < len(ba) else []
        q = sample_rot(rot, t)
        D = S.qmat(q, conj=False) @ S.qmat(R0[i], conj=True)
        D = COORD @ D @ COORD.T
        Rb = D @ Rrest[i]
        p = parent[i]
        if p is None or p not in joint:
            Wrot[i] = Rb
            joint[i] = rest[i].copy()
            continue
        Wp = Wrot[p]
        Wrot[i] = Rb                        # abs：增量本身已是世界增量
        joint[i] = joint[p] + Wp @ (Rrest[p].T @ (rest[i] - rest[p]))

    M = {}
    for i in order:
        m = np.eye(4)
        m[:3, :3] = Wrot[i]
        m[:3, 3] = joint[i]
        M[i] = m
    return M


def pose_matrices(Ms, Mrest, Mrest_inv=None):
    """把 {骨: M_anim} 折成"每根骨一个 4×4 蒙皮矩阵"的数组，按 **engine id** 索引。

    ★ 原实现对每个顶点、每根骨都做一次 `np.linalg.inv(Mrest[b])`：求逆是 O(27)
      的小活，但乘以"每帧 × 每槽 × 每骨"就是几万次，是切动画要等 2 秒的主因之一。
      这里一次算好，之后只做查表。
    """
    bones = sorted(Ms)
    if not bones:
        return np.zeros((0, 4, 4))
    nid = max(bones) + 1
    out = np.zeros((nid, 4, 4))
    for b in bones:
        inv = (Mrest_inv[b] if Mrest_inv is not None
               else np.linalg.inv(Mrest[b]))
        out[b] = Ms[b] @ inv
    return out


def lbs(V, idx, wt, Ms, Mrest, Mrest_inv=None, mats=None):
    """标准 LBS：v' = Σ w · (M_anim · M_rest⁻¹ · v)。

    用查表 + 向量化代替"逐骨 Python 循环"（见 pose_matrices 的说明）。
    """
    M = mats if mats is not None else pose_matrices(Ms, Mrest, Mrest_inv)
    out = np.zeros_like(V)
    nb = idx.shape[1]
    for k in range(nb):
        j = idx[:, k].astype(np.int64)
        w = wt[:, k].astype(np.float64)
        sel = np.where(w > 0)[0]
        if not len(sel):
            continue
        js = j[sel]
        ws = w[sel]
        if M.shape[0] <= int(js.max()):
            raise IndexError(f"骨骼索引 {int(js.max())} 超出骨架范围 "
                             f"（{M.shape[0]} 根）—— 这个网格大概不是 BL 骨架")
        R = M[js][:, :3, :3]                 # (n,3,3)
        t = M[js][:, :3, 3]                  # (n,3)
        # ★ 行向量约定：v' = v @ Rᵀ + t ⇒ einsum 必须写 `nji`。
        #   写成 `nij` 就是漏了转置（v @ R），结果模型整体被拧/放大 ——
        #   本文件开头就记着同一个坑（bug #1："行向量约定下要右乘 Cᵀ"），
        #   这次在 einsum 上又踩了一遍。判据：位移会从百毫米级跳到米级。
        out[sel] += ws[:, None] * (np.einsum("ni,nji->nj", V[sel], R) + t)
    return out


def transform_normals(N, idx, wt, Ms, Mrest, Mrest_inv=None, mats=None):
    M = mats if mats is not None else pose_matrices(Ms, Mrest, Mrest_inv)
    out = np.zeros_like(N)
    nb = idx.shape[1]
    for k in range(nb):
        j = idx[:, k].astype(np.int64)
        w = wt[:, k].astype(np.float64)
        sel = np.where(w > 0)[0]
        if not len(sel):
            continue
        js = j[sel]
        ws = w[sel]
        R = M[js][:, :3, :3]
        out[sel] += ws[:, None] * np.einsum("ni,nji->nj", N[sel], R)   # 同样要转置
    ln = np.linalg.norm(out, axis=1, keepdims=True)
    ln[ln < 1e-9] = 1.0
    return out / ln


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skeleton", required=True, help="bl_skeleton.json（官方 human_skeleton.fbx 导出）")
    ap.add_argument("--anim", required=True, help="mbtool anim 导出的动画 JSON")
    ap.add_argument("--src", required=True, help="含 <tag>.npz（verts/bone_idx/bone_wt）的目录")
    ap.add_argument("--out", required=True)
    ap.add_argument("--nframes", type=int, default=12)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--tags", default=None, help="逗号分隔，默认自动扫描")
    ap.add_argument("--rest-anim", default=None,
                    help="提供 rest 四元数的动画 JSON（默认用 --anim 自己的第 0 帧）")
    a = ap.parse_args()

    rest, Rrest, parent, names, order = load_skeleton(a.skeleton)
    anim = json.load(open(a.anim, encoding="utf-8"))

    src_anim = json.load(open(a.rest_anim, encoding="utf-8")) if a.rest_anim else anim
    R0 = {}
    for i in order:
        rot = src_anim["boneAnims"][i]["rot"]
        R0[i] = rot[0]["q"]
    if a.rest_anim:
        d = max(abs(np.linalg.norm(np.array(R0[i], float)) - 1.0) for i in order)
        print(f"[rest] 从 {os.path.basename(a.rest_anim)} 取 rest 四元数，|q| 偏差 {d:.2e}")

    tags = ([t.strip() for t in a.tags.split(",")] if a.tags
            else sorted(os.path.splitext(f)[0] for f in os.listdir(a.src)
                        if f.endswith(".npz") and not f.startswith("_")))

    Mrest = {}
    for i in order:
        m = np.eye(4)
        m[:3, :3] = Rrest[i]
        m[:3, 3] = rest[i]
        Mrest[i] = m

    # ★ 时间轴用关键帧的 t（各骨帧数不一致，长度不能当时间用）
    t_end = max(b["rot"][-1]["t"] for b in anim["boneAnims"] if b["rot"])
    if a.nframes > 1:
        frames = sorted(set(int(round(x)) for x in np.linspace(a.start, t_end, a.nframes)))
    else:
        frames = [a.start]
    frames = [f for f in frames if f <= t_end]

    print(f"[anim] {anim['name']}  t 范围 0..{t_end:.0f}  渲染 {len(frames)} 帧: {frames[:8]}"
          f"{'...' if len(frames) > 8 else ''}")
    print(f"[src ] {a.src}   tags={tags}")

    for fi, f in enumerate(frames):
        Ms = build_pose(rest, Rrest, parent, order, anim, f, R0)
        outdir = os.path.join(a.out, f"f{fi:03d}")
        os.makedirs(outdir, exist_ok=True)
        for tag in tags:
            p = os.path.join(a.src, tag + ".npz")
            if not os.path.exists(p):
                print(f"  [{tag}] 缺 {p}")
                continue
            d = np.load(p, allow_pickle=True)
            V_eng = np.asarray(d["verts"], dtype=np.float64)
            N_eng = np.asarray(d["normals"], dtype=np.float64) if "normals" in d.files else None
            idx = np.asarray(d["bone_idx"], dtype=np.int64)
            wt = np.asarray(d["bone_wt"], dtype=np.float64)

            # engine -> armature：★ 行向量约定下必须右乘 Cᵀ（不是 C）。
            #   写反的后果极其隐蔽：t=0 时 Δ=I、LBS 退化成恒等变换，
            #   坐标变换"进去再出来"正好相互抵消 ⇒ 网格完美还原、偏移 0.00mm、
            #   任何基于 t=0 的自检都全绿。但一进动画就暴露：
            #   实测头部顶点被镜像到 Y 负侧（y=-1.55，而骨架 head 在 y=+1.57），
            #   |v-rest| 高达 3m，LBS 于是按错的距离旋转，袖子头发全甩成长尖刺。
            V_arm = V_eng @ C_ARM_FROM_ENG.T
            V2_arm = lbs(V_arm, idx, wt, Ms, Mrest)
            V2_eng = V2_arm @ C_ARM_FROM_ENG

            kw = dict(verts=V2_eng.astype(np.float32),
                      uv=d["uv"], faces=d["faces"], face_group=d["face_group"],
                      group_names=d["group_names"], materials=d["materials"])
            if N_eng is not None:
                N_arm = N_eng @ C_ARM_FROM_ENG.T
                kw["normals"] = (transform_normals(N_arm, idx, wt, Ms, Mrest)
                                 @ C_ARM_FROM_ENG).astype(np.float32)
            np.savez_compressed(os.path.join(outdir, tag + ".npz"), **kw)

            drift = np.linalg.norm(V2_eng - V_eng, axis=1)
            print(f"  f{fi:03d}/{tag:<6} frame={f:<5} 顶点={len(V2_eng)}  "
                  f"z[{V2_eng[:,2].min():+.3f},{V2_eng[:,2].max():+.3f}]  "
                  f"与绑定姿势平均位移={drift.mean()*1000:.1f}mm 最大={drift.max()*1000:.1f}mm")
    print(f"输出 {a.out}（render.py --mode=<相对 work 的路径>）")
    return 0


if __name__ == "__main__":
    sys.exit(main())