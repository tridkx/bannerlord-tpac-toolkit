# -*- coding: utf-8 -*-
"""验证"骨骼叠加"在**每个角色**上都真的画出来了。

为什么要专门测这个：骨骼是在材质组渲染**之后**追加绘制的，会继承最后一个
材质组留下的 GL 状态（发丝那种 alphaTest=0.2745 的镂空材质会把骨骼线整条剪掉）。
而 `groups` 的顺序来自 `np.unique(face_group)`，**不同角色不一样** ——
于是出现"月清疏能看见骨骼、白茉晴一根线都没有"这种跟着角色变的怪现象。
判据用的是**开/关骨骼的 A/B 差异像素**（比"数某种颜色的像素"可靠：
按橙色统计会把粉色腰带、红色配饰算进去，实测让我一度得出相反结论）。

用法：
  python selftest_bones.py --posed-dir <工程>/work/imported --skeleton bl_skeleton.json \
      --anim-dir anims --tex-dir <工程>/work/imported/tex_png
"""
import sys, argparse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass
import numpy as np, pyglet
import mbpreview_gui as G

ap0 = argparse.ArgumentParser()
ap0.add_argument("--posed-dir", required=True)
ap0.add_argument("--skeleton", default=str(Path(__file__).resolve().parent / "bl_skeleton.json"))
ap0.add_argument("--anim-dir", default=str(Path(__file__).resolve().parent / "anims"))
ap0.add_argument("--tex-dir", default=None)
ap0.add_argument("--out", default="_verify")
A = ap0.parse_args()
OUT = Path(A.out); OUT.mkdir(parents=True, exist_ok=True)
P = Path(A.posed_dir)
texdir = A.tex_dir or str(P / "tex_png")
win = pyglet.window.Window(1100, 800, visible=False)
args = argparse.Namespace(fps=24.0, unlit=False, only_mats=None, flip_tex=False,
                          shot=False, record=None, tex_dir=texdir)
_anims = []
for f in sorted(Path(A.anim_dir).glob("*.json")):
    if f.name != "index.json":
        _anims.append((f.stem, str(f)))
data = G.DataSet(P, A.skeleton, _anims[:1], G.load_texmap(P), 6, 0, {}, drop_mats=None)
v = G.Viewer(data, args, texdir, window=win)
v.show_bones = True
v.load_textures(); v.upload_dynamic()
win.switch_to()

def shot(tag):
    """用 A/B 差异判断骨骼到底画出来没有 —— 比数"橙色像素"可靠得多
    （橙色判据会把粉色腰带/红色配饰算进去，实测误导过一次结论）。"""
    from pyglet.gl import glFinish
    from PIL import Image
    prev, imgs = v.show_bones, {}
    for flag in (False, True):
        v.show_bones = flag
        v.upload_dynamic()
        v.draw(1100, 800)
        glFinish()
        p = OUT / f"switch_{tag}_{'on' if flag else 'off'}.png"
        pyglet.image.get_buffer_manager().get_color_buffer().save(str(p))
        imgs[flag] = np.array(Image.open(p).convert("RGB")).astype(int)
    v.show_bones = prev
    diff = (np.abs(imgs[True] - imgs[False]).sum(2) > 24)
    print(f"  {tag:20s} char={v.char:4s}  show_bones 开/关的差异像素 = {int(diff.sum()):6d}"
          f"   -> {'有骨骼' if diff.sum() > 500 else '**没画出来**'}")
    return int(diff.sum())

shot("1_init_bai")
v.switch_char(1); shot("2_tab_yue")
v.switch_char(1); shot("3_tab_back_bai")
v.switch_anim(0); shot("4_after_anim")
