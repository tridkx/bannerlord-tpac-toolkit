# -*- coding: utf-8 -*-
"""mb-preview —— 游戏动画离线预览：一条命令从「骨架 + 游戏动画 + 皮套网格」出序列图/GIF。

它把三件事串起来（各自也可单独用）：
  1. `anim_pose.py`   把游戏动画套到网格上，逐帧写 npz
  2. Blender + 工程自带的 `render.py`  渲染每帧（贴图/多视角/取景都复用已验证的管线）
  3. 拼成序列图与 GIF

为什么值得单独做一条命令
------------------------
在这之前，离线预览只能套 `pose_test.py` 里**自己手写的合成姿势**（walk/knee/stride）——
手的角度、裙摆的摆动、肩胯关系全是猜的，所以"预览图跟游戏内表现对不上"。
现在直接套游戏真正在播的动画（`inventory_idle` 等），预览才有验收价值。

用法
----
  python mb-preview.py --skeleton work/bl_skeleton.json \
      --anim work/anims/inventory_idle.json \
      --posed-dir work/posed --work-dir work \
      --render-script pipeline/render.py \
      --out renders/anim_idle --chars yue --views front,q34 --nframes 8

Blender 与游戏路径都**先探测再使用**，可用参数/环境变量覆盖（不写死盘符）。
"""
import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

# ★ 控制台默认是中文 GBK(936)：本脚本 print 中文，不钉死编码会 UnicodeEncodeError 崩掉。
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HERE = Path(__file__).resolve().parent

BLENDER_CANDIDATES = [
    r"D:\Blender Foundation\Blender 5.2\blender.exe",
    r"D:\Blender Foundation\Blender 5.0\blender.exe",
    r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe",
    r"C:\Program Files\Blender Foundation\Blender 4.2\blender.exe",
]


def find_blender(explicit=None):
    if explicit:
        return explicit
    env = os.environ.get("MB_BLENDER")
    if env and Path(env).exists():
        return env
    for c in BLENDER_CANDIDATES:
        if Path(c).exists():
            return c
    found = shutil.which("blender")
    if found:
        return found
    raise SystemExit("找不到 blender.exe —— 用 --blender 或环境变量 MB_BLENDER 指定")


def run(cmd, **kw):
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", **kw)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skeleton", required=True, help="bl_skeleton.json（官方 human_skeleton.fbx 导出）")
    ap.add_argument("--anim", required=True, help="mbtool anim 导出的动画 JSON")
    ap.add_argument("--posed-dir", required=True, help="含 <char>.npz（verts/bone_idx/bone_wt）")
    ap.add_argument("--work-dir", required=True, help="工程的 work 目录（中间产物写这里）")
    ap.add_argument("--render-script", required=True, help="工程里的 pipeline/render.py")
    ap.add_argument("--out", required=True, help="输出目录（PNG/GIF/序列图）")
    ap.add_argument("--chars", default=None, help="逗号分隔，默认自动扫描 posed-dir")
    ap.add_argument("--views", default="front,q34")
    ap.add_argument("--nframes", type=int, default=8)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--res", type=int, default=560)
    ap.add_argument("--blender", default=None)
    ap.add_argument("--rest-anim", default=None, help="提供 rest 四元数的动画（默认用 --anim 的第 0 帧）")
    ap.add_argument("--anim-index", default=None,
                    help="anims/index.json（由 build_anim_index.py 生成，"
                         "含每个动画对应的 clip 时长）。缺省自动找 --anim 同目录的 index.json，"
                         "用它把 GIF 的帧延时设成**游戏里的真实节奏**")
    ap.add_argument("--no-render", action="store_true", help="只生成 npz，不渲染")
    a = ap.parse_args()

    blender = find_blender(a.blender)
    anim_name = Path(a.anim).stem
    tag = "anim_" + anim_name.replace("anim_", "")
    anim_work = Path(a.work_dir) / tag

    chars = ([c.strip() for c in a.chars.split(",")] if a.chars
             else sorted(Path(p).stem for p in glob.glob(str(Path(a.posed_dir) / "*.npz"))
                         if not os.path.basename(p).startswith("_")))
    views = [v.strip() for v in a.views.split(",") if v.strip()]

    print(f"[1/3] 生成动画帧: {anim_name}  chars={chars}  -> {anim_work}")
    cmd = [sys.executable, str(HERE / "anim_pose.py"),
           "--skeleton", a.skeleton, "--anim", a.anim,
           "--src", a.posed_dir, "--out", str(anim_work),
           "--nframes", str(a.nframes), "--start", str(a.start)]
    if a.chars:
        cmd += ["--tags", ",".join(chars)]
    if a.rest_anim:
        cmd += ["--rest-anim", a.rest_anim]
    rc, out = run(cmd)
    print("\n".join(out.strip().splitlines()[-6:]))
    if rc != 0:
        return rc

    if a.no_render:
        return 0

    outdir = Path(a.out)
    outdir.mkdir(parents=True, exist_ok=True)
    frames = sorted(p.name for p in anim_work.iterdir() if p.is_dir())
    print(f"[2/3] 渲染 {len(frames)} 帧 × {len(chars)} 角色 × {len(views)} 视角（Blender 无头）")
    for i, fr in enumerate(frames):
        for ch in chars:
            cmd = [blender, "-b", "--factory-startup", "--python", a.render_script,
                   "--", f"--mode={tag}/{fr}", f"--tag={fr}", f"--out={outdir}",
                   f"--chars={ch}", f"--views={','.join(views)}", f"--res={a.res}"]
            rc, out = run(cmd)
            ok = [l for l in out.splitlines() if "WROTE" in l]
            print(f"  [{i+1}/{len(frames)}] {fr}/{ch}: {len(ok)} 张"
                  + ("" if ok else "  !! 没出图"))
            for l in out.splitlines():
                if "Traceback" in l or "[render] !!" in l:
                    print("      " + l.strip())

    print("[3/3] 拼序列图与 GIF")
    try:
        from PIL import Image
    except ImportError:
        print("  （没装 Pillow，跳过拼接）")
        return 0

    # ★ 帧延时：优先用 clip 声明的真实时长算，而不是拍一个固定值。
    #   （动画 t 轴与"秒"的换算关系不在数据里，唯一有据可查的是
    #     AnimationClip.duration —— 见 build_anim_index.py 的说明。）
    idx_path = a.anim_index
    if idx_path is None:
        cand = Path(a.anim).resolve().parent / "index.json"
        if cand.exists():
            idx_path = str(cand)
    anim_meta = {}
    if idx_path and Path(idx_path).exists():
        try:
            anim_meta = json.loads(Path(idx_path).read_text(encoding="utf-8"))
            anim_meta = anim_meta.get(Path(a.anim).stem, {})
        except Exception as e:
            print(f"  索引读取失败 {type(e).__name__}: {e}")
            anim_meta = {}
    sec = anim_meta.get("seconds")
    frame_ms = 200
    if sec:
        frame_ms = max(20, int(round(sec / max(1, len(frames)) * 1000)))
        print(f"  帧延时 {frame_ms}ms（{anim_meta.get('clip')} 声明 {sec:.2f}s / "
              f"{len(frames)} 帧 ≈ {1000.0/frame_ms:.1f} fps 等效）")
    else:
        print(f"  帧延时 {frame_ms}ms（没有 clip 时长可用，用固定值）")
    for ch in chars:
        for view in views:
            files = sorted(glob.glob(str(outdir / f"f*_{ch}_{view}.png")))
            if not files:
                continue
            imgs = [Image.open(f).convert("RGB") for f in files]
            gif = outdir / f"_{ch}_{view}.gif"
            imgs[0].save(gif, save_all=True, append_images=imgs[1:],
                         duration=frame_ms, loop=0, optimize=True)
            w, h = imgs[0].size
            sheet = Image.new("RGB", (w * len(imgs), h), (20, 22, 26))
            for c, im in enumerate(imgs):
                sheet.paste(im, (c * w, 0))
            seq = outdir / f"_{ch}_{view}_sequence.png"
            sheet.save(seq)
            print(f"  {gif.name} / {seq.name}  ({len(imgs)} 帧)")
    print(f"完成 -> {outdir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())