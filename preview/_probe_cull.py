# -*- coding: utf-8 -*-
"""渲染前查询 GL_CULL_FACE 的真实状态 —— 用户描述的"从哪个视角看就看不到
哪个方向的头发"只可能是背面剔除的行为，而我此前只凭"代码里没写 glEnable"
就排除了它，从没查过实际状态。"""
import sys, argparse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass
import numpy as np, pyglet
import mbpreview_gui as G
from pyglet.gl import (glIsEnabled, GL_CULL_FACE, GL_DEPTH_TEST, GL_BLEND,
                       GL_ALPHA_TEST, GL_LIGHTING, GL_TEXTURE_2D, glGetIntegerv,
                       GL_FRONT_FACE, GL_CW, GL_CCW, glGetError)

P = Path("D:/dsh-mod/mb-xianjian7/work/imported")
win = pyglet.window.Window(1100, 800, visible=False)
args = argparse.Namespace(fps=24.0, unlit=False, only_mats=None, flip_tex=False,
                          shot=False, record=None, tex_dir=str(P / "tex_png"))
data = G.DataSet(P, "bl_skeleton.json",
                 [("inventory_idle", "anims/inventory_idle.json")],
                 G.load_texmap(P), 4, 0, {}, drop_mats=None)
v = G.Viewer(data, args, str(P / "tex_png"), window=win)
v.load_textures(); v.upload_dynamic(); win.switch_to()

def state(tag):
    ff = (pyglet.gl.GLint)()
    glGetIntegerv(GL_FRONT_FACE, ff)
    print(f"  {tag:22s} CULL_FACE={bool(glIsEnabled(GL_CULL_FACE))}  "
          f"DEPTH={bool(glIsEnabled(GL_DEPTH_TEST))}  BLEND={bool(glIsEnabled(GL_BLEND))}  "
          f"ALPHA_TEST={bool(glIsEnabled(GL_ALPHA_TEST))}  LIGHT={bool(glIsEnabled(GL_LIGHTING))}  "
          f"TEX2D={bool(glIsEnabled(GL_TEXTURE_2D))}  FRONT_FACE={'CW' if ff.value==GL_CW else 'CCW'}")

state("窗口创建后")
state("load_textures 后")
v.draw(1100, 800)
state("draw 之后")
# 逐组渲染中途的状态（复制 draw 的循环，只查状态）
from pyglet.gl import glDisable
for gi, g in enumerate(v.groups[:6]):
    if not g["tex"]:
        continue
    print(f"    组[{gi}] {g.get('name','?')[:22]:24s} blend={g.get('blend')} "
          f"alpha_test={g.get('alpha_test')}  深度写入={'关' if (g.get('blend') and not (g.get('alpha_test') or 0)>0) else '开'}")
print("  glGetError:", glGetError())
