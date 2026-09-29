# -*- coding: utf-8 -*-
"""无头地点一遍 UI 按钮的回调 —— 验证新写的交互路径不抛异常。"""
import sys, time, argparse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass
import pyglet, numpy as np
import mbpreview_gui as G
import mbui

P = Path("D:/dsh-mod/mb-xianjian7/work/imported")
win = pyglet.window.Window(1100, 800, caption="probe ui", visible=False)
args = argparse.Namespace(fps=24.0, unlit=False, only_mats=None, flip_tex=False,
                          shot=False, record=None, tex_dir=str(P / "tex_png"))
data = G.DataSet(P, "bl_skeleton.json", [("inventory_idle", "anims/inventory_idle.json"),
                                         ("walk_barmaid", "anims/walk_barmaid.json")],
                 G.load_texmap(P), 12, 0, {}, drop_mats=None)
v = G.Viewer(data, args, str(P / "tex_png"), window=win)
v.load_textures(); v.upload_dynamic()

# 直接构造与 GUI 里同构的按钮（回调在这里重写一份等价的，验证动作语义）
acts = {
    "char -": lambda: v.switch_char(-1),
    "char +": lambda: v.switch_char(1),
    "frame -": lambda: setattr(v, "_cur", (v.cur - 1) % v.frames["pos"].shape[0]),
    "frame +": lambda: setattr(v, "_cur", (v.cur + 1) % v.frames["pos"].shape[0]),
    "play": lambda: setattr(v, "playing", not v.playing),
    "anim 0": lambda: v.switch_anim(0),
    "anim 1": lambda: v.switch_anim(1),
}
for nm, yaw in mbui.VIEWS.items():
    acts["view " + nm] = (lambda y=yaw: setattr(v, "rot", [y[0], y[1]]))
acts["tex"] = lambda: setattr(v, "show_tex", not v.show_tex)

ui = mbui.UiBar(win, on_seek=lambda f: setattr(v, "_cur", int(f * 11)))
ui.buttons = [mbui.Button(k, cb) for k, cb in acts.items()]
win.switch_to()
ui.layout(1100, 800)

bad = 0
for b in ui.buttons:
    try:
        b.cb()
        v.upload_dynamic()
        win.clear(); v.draw(1100, 800)
        ui.draw(1100, 800, progress=v.cur / 11.0,
                overlay=(pyglet.text.Label("x", x=5, y=5),))
        print(f"  [ok] {b.text:12s} -> char={v.char} anim={v.frames['name']:16s} "
              f"cur={v.cur:2d} playing={v.playing} tex={v.show_tex}")
    except Exception as e:
        bad += 1
        print(f"  [FAIL] {b.text}: {type(e).__name__}: {e}")

# 滑块跳帧
try:
    ui.on_seek(0.5); ui.on_seek(0.0); ui.on_seek(1.0)
    print(f"  [ok] 时间轴跳帧 -> cur={v.cur}")
except Exception as e:
    bad += 1; print(f"  [FAIL] 时间轴: {type(e).__name__}: {e}")

# 命中测试：点在按钮中心应当命中，点在画面中央不应命中
b0 = ui.buttons[0]
hit = ui._hit_button(b0.x + b0.w // 2, b0.y + b0.h // 2) is b0
mid = ui._hit_button(550, 400) is None
print(f"  [{'ok' if hit else 'FAIL'}] 按钮命中测试")
print(f"  [{'ok' if mid else 'FAIL'}] 画面中央不误触 UI")
print(f"\n结果：{'全部通过' if bad == 0 and hit and mid else f'{bad} 处失败'}")
