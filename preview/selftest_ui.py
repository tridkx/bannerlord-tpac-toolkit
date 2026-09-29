# -*- coding: utf-8 -*-
"""模拟点一下"骨骼"按钮：验证回调真的被调用、且 draw_bones 不抛异常。"""
import sys, argparse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass
import pyglet, numpy as np
import mbpreview_gui as G
import mbui

P = Path("D:/dsh-mod/mb-xianjian7/work/imported")
win = pyglet.window.Window(1100, 800, caption="bones btn", visible=False)
args = argparse.Namespace(fps=24.0, unlit=False, only_mats=None, flip_tex=False,
                          shot=False, record=None, tex_dir=str(P / "tex_png"))
data = G.DataSet(P, "bl_skeleton.json", [("inventory_idle", "anims/inventory_idle.json")],
                 G.load_texmap(P), 8, 0, {}, drop_mats=None)
v = G.Viewer(data, args, str(P / "tex_png"), window=win)
v.load_textures(); v.upload_dynamic()

toggled = {"n": 0}
def cb():
    v.show_bones = not v.show_bones
    toggled["n"] += 1

ui = mbui.UiBar(win)
ui.buttons = [mbui.Button("骨骼", cb)]
win.switch_to()
ui.layout(1100, 800)

b = ui.buttons[0]
cx, cy = b.x + b.w // 2, b.y + b.h // 2
print(f"按钮矩形 x={b.x} y={b.y} w={b.w} h={b.h}  中心=({cx},{cy})")

# 走一遍真正的 pyglet 事件路径（按下 -> 松开）
consumed_p = ui.on_mouse_press(cx, cy, 1, 0)
consumed_r = ui.on_mouse_release(cx, cy, 1, 0)
print(f"on_mouse_press 消费={consumed_p}  on_mouse_release 消费={consumed_r}  "
      f"回调次数={toggled['n']}  show_bones={v.show_bones}")

# 画一帧，确认 draw_bones 不抛
try:
    v.draw(1100, 800)
    print("draw() 含骨骼 -> OK")
except Exception as e:
    print(f"draw() 抛异常: {type(e).__name__}: {e}")

# 手抖 2px 再点一次
consumed_p = ui.on_mouse_press(cx, cy, 1, 0)
consumed_r = ui.on_mouse_release(cx + 2, cy + 2, 1, 0)
print(f"手抖 2px：回调次数={toggled['n']}  show_bones={v.show_bones}")

# 画面中央（模型上）不应命中 UI
hit_mid = ui._hit_button(550, 400)
print(f"画面中央命中 UI = {hit_mid is not None}（应为 False）")

ok = (toggled['n'] == 2 and hit_mid is None)
print("\n结果：" + ("通过" if ok else "不通过"))
