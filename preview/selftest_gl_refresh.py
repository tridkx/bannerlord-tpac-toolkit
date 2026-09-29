"""在 pyglet 1.5.31 上确定"用 clock 驱动动画、让画面持续刷新"的正确写法。

跑法: python _probe_pyglet.py <A|B|C>
  A = win.invalid = True         （属性，1.5 没有 invalidate() 方法）
  B = 手动 switch_to + dispatch on_draw + flip
  C = 什么都不做（基线：看 EventLoop 会不会自动重绘）
"""
import sys, pyglet
for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass

mode = sys.argv[1] if len(sys.argv) > 1 else "C"
win = pyglet.window.Window(360, 240, caption="probe " + mode)
st = {"tick": 0, "draw": 0, "err": 0}

@win.event
def on_draw():
    st["draw"] += 1
    win.clear()

def tick(dt):
    st["tick"] += 1
    try:
        if mode == "A":
            win.invalid = True
        elif mode == "B":
            win.switch_to()
            win.dispatch_event("on_draw")
            win.flip()
    except Exception as e:
        st["err"] += 1
        if st["err"] == 1:
            print("  tick 异常:", type(e).__name__, e)

pyglet.clock.schedule_interval(tick, 1 / 30.0)
pyglet.clock.schedule_once(lambda dt: pyglet.app.exit(), 3.0)
pyglet.app.run()
print(f"方案 {mode}: tick={st['tick']} (期望≈90)  on_draw={st['draw']}  异常={st['err']}")
