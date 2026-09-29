import sys, json
from pathlib import Path
sys.path.insert(0, ".")
for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass
import numpy as np, argparse, pyglet
import mbpreview_gui as G
P = Path("D:/dsh-mod/mb-xianjian7/work/imported")
win = pyglet.window.Window(1100, 800, visible=False)
a = argparse.Namespace(fps=24.0, unlit=False, only_mats=None, flip_tex=False,
                       shot=False, record=None, tex_dir=str(P/"tex_png"),
                       alpha_test=None, no_compose_q=False)
anims = [("inv_movements","anims/inv_movements.json"),
         ("inventory_idle","anims/inventory_idle.json"),
         ("walk_barmaid","anims/walk_barmaid.json")]
data = G.DataSet(P, "bl_skeleton.json", anims, G.load_texmap(P), 24, 0, {}, drop_mats=None)
v = G.Viewer(data, a, str(P/"tex_png"), window=win); v.load_textures()
print(f"  {'角色':6s} {'动画':16s} {'手到中线':>8} {'手高':>7} {'头高':>7} {'脚底z范围':>9}")
for ci, ch in enumerate(data.chars):
    v.ci = ci
    for ai, (nm, _) in enumerate(anims):
        v.ai = ai; v._cur = 0
        fr = v.frames
        J = fr["joints"]                      # (F, nid, 3) armature
        pos = fr["pos"]                       # (F, nv, 3) engine
        hand_x = np.abs(J[:, [19, 26], 0]).mean() * 1000
        hand_z = J[:, [19, 26], 2].mean() * 1000
        head_z = J[:, 13, 2].mean() * 1000
        foot = (pos[:, :, 2].min(1) * 1000)
        print(f"  {ch:6s} {nm:16s} {hand_x:8.0f} {hand_z:7.0f} {head_z:7.0f} "
              f"{foot.max()-foot.min():9.1f}")
