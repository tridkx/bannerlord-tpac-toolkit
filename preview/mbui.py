# -*- coding: utf-8 -*-
"""mbui —— 预览器的按钮/滑块层（给"人"用的操作界面）。

为什么自己做而不用现成的
------------------------
* `pyglet.gui`（1.5 里有）要求自己准备按钮纹理，且内部用 **GLSL shader**；
* `pyglet.shapes` 同样走 shader。而本预览器的三维部分是**固定管线**
  （`glVertexPointer` + `GL_LIGHT0`），混用 shader 程序要多管一层状态。
* 这里只用 `pyglet.graphics.Batch`（客户端顶点数组，固定管线友好）+ `pyglet.text.Label`
  （贴图文字），几十个矩形对十万级三角形的场景毫无压力。

交互约定
--------
* 按钮条贴在窗口底部，时间轴（进度条）在它上面一条：**和视频播放器的习惯一致**
  —— 左边播放控制、中间动画切换、右边视角与工具。
* 鼠标落在 UI 上时**不旋转模型**（`on_mouse_press` 返回 True 表示已消费）。
* 时间轴可以**点击跳帧、按住拖动**。
* 悬停高亮，当前项（角色/动画/开关）用不同底色标出。
"""
import pyglet
from pyglet.gl import (GL_TRIANGLES, GL_BLEND, GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA,
                       glEnable, glDisable, glBlendFunc, GL_DEPTH_TEST,
                       glMatrixMode, GL_PROJECTION, glPushMatrix, glLoadIdentity,
                       glOrtho, GL_MODELVIEW, glPopMatrix, GL_LIGHTING,
                       GL_TEXTURE_2D, GL_ALPHA_TEST, GL_CULL_FACE, GL_SCISSOR_TEST,
                       glColor4f)

# ★ 按钮是中文，字体必须能出汉字：Consolas 没有汉字字形，会渲染成方块。
#   Microsoft YaHei 是 Windows 自带的，pyglet 会按名字去系统字体里找。
FONT = "Microsoft YaHei"
FONT_FALLBACK = "SimHei"
FSIZE = 10

# 配色（RGBA 0..255）
C_BAR = (18, 20, 24, 215)
C_BTN = (52, 57, 66, 235)
C_BTN_HOVER = (78, 86, 99, 245)
C_BTN_ACTIVE = (58, 122, 106, 245)       # 当前项（角色/动画/开关）
C_BTN_ACCENT = (52, 92, 156, 245)        # 主动作（打开 mod…）
C_TEXT = (228, 230, 236, 255)
C_TEXT_DIM = (150, 156, 166, 255)
C_TRACK = (44, 48, 56, 225)
C_FILL = (86, 150, 132, 235)
C_KNOB = (216, 222, 230, 255)


def _text_width(text, fs):
    """按字符估宽：汉字/全角 ≈ 1 个字宽，西文 ≈ 0.62 个字宽。

    早先一律用 `len(text)*0.66*fs` 估算 —— 换成中文按钮后每个按钮都会算窄，
    字被裁掉。
    """
    w = 0.0
    for ch in text:
        w += fs * (1.02 if ord(ch) > 0x2E80 else 0.62)
    return w


class Button:
    __slots__ = ("x", "y", "w", "h", "text", "cb", "active", "enabled", "tip",
                 "accent")

    def __init__(self, text, cb, active=False, enabled=True, tip="", accent=False):
        self.text, self.cb = text, cb
        self.active, self.enabled, self.tip = active, enabled, tip
        self.accent = accent          # 强调色（"打开 mod" 这类主动作）
        self.x = self.y = self.w = self.h = 0


class UiBar:
    """底部按钮条 + 时间轴。所有回调由外部注入。"""

    def __init__(self, window, on_seek=None, tooltip_getter=None):
        self.win = window
        self.on_seek = on_seek                 # (t_index) -> None
        self.tooltip_getter = tooltip_getter   # () -> str（鼠标悬停时显示的信息）
        self.buttons = []
        self.hover = None
        self.pressed = None
        self.seeking = False
        self.track = None                      # (x, y, w, h)
        self.enabled = True
        self.tooltip = ""
        self._sig = None
        self._batch = None
        self._labels = []

    # ---------------- 布局 ----------------
    def _need_relayout(self, w, h):
        sig = (w, h, self.hover.text if self.hover else None,
               tuple((b.text, b.active, b.enabled, b.accent) for b in self.buttons))
        if sig != self._sig:
            self._sig = sig
            return True
        return False

    def layout(self, w, h):
        """从下往上排按钮；一行放不下就**换行**。

        ★ 早先不换行、只在挤的时候压缩间距 —— 中文按钮比英文宽得多，
          19 个按钮的总宽会顶到窗口边缘，右边那几个（"打开 mod"就在最后）
          直接被挤出可视区 = **看得见左半边、点不到右半边**。
        """
        self.w = w
        self.h = h
        pad, bh, gap = 8, 24, 5
        tw = w - 2 * pad
        for b in self.buttons:
            b.w = max(28, int(_text_width(b.text, FSIZE)) + 16)
            b.h = bh

        rows, cur, curw = [], [], 0
        for b in self.buttons:
            if cur and curw + b.w > tw:      # 本行放不下 → 开新行
                rows.append(cur)
                cur, curw = [], 0
            cur.append(b)
            curw += b.w + gap
        if cur:
            rows.append(cur)

        y = pad
        # 最后一行贴着底边，往上叠（视觉上像播放器）
        for row in reversed(rows):
            x = pad
            for b in row:
                b.x, b.y = x, y
                x += b.w + gap
            y += bh + 4
        th = 8
        self.track = (pad, y + 2, tw, th)
        self.bar_h = y + th + 8
        self.n_rows = len(rows)
        self._rebuild()

    def _rebuild(self):
        """重建矩形 batch 与文字（只在布局/hover/状态变化时调用）。"""
        from pyglet.graphics import Batch
        batch = Batch()
        labels = []

        def rect(x, y, w, h, col):
            # 用两个三角形而不是 GL_QUADS：现代 GL 已去掉四边形图元，
            # 走三角形在任何驱动上都稳。
            batch.add(6, GL_TRIANGLES, None,
                      ("v2f", (x, y, x + w, y, x + w, y + h,
                               x, y, x + w, y + h, x, y + h)),
                      ("c4B", col * 6))

        if self.enabled:
            # 底栏背景（高度随行数自适应）
            rect(0, 0, self.w, getattr(self, "bar_h", 64), C_BAR)
            # 时间轴
            tx, ty, tw, th = self.track
            rect(tx, ty, tw, th, C_TRACK)
            frac = getattr(self, "progress", 0.0)
            rect(tx, ty, max(2, int(tw * frac)), th, C_FILL)
            kx = tx + int(tw * frac)
            rect(max(tx, kx - 2), ty - 3, 5, th + 6, C_KNOB)
            # 按钮
            for b in self.buttons:
                if not b.enabled:
                    col = (40, 43, 49, 200)
                elif b is self.hover and b is self.pressed:
                    col = (100, 110, 126, 250)
                elif b is self.hover:
                    col = C_BTN_HOVER
                elif b.active:
                    col = C_BTN_ACTIVE
                elif b.accent:
                    col = C_BTN_ACCENT
                else:
                    col = C_BTN
                rect(b.x, b.y, b.w, b.h, col)
                labels.append(pyglet.text.Label(
                    b.text, font_name=FONT, font_size=FSIZE,
                    x=b.x + b.w // 2, y=b.y + b.h // 2,
                    anchor_x="center", anchor_y="center",
                    color=C_TEXT if b.enabled else C_TEXT_DIM))

        self._batch = batch
        self._labels = labels

    def refresh(self):
        self._sig = None

    # ---------------- 绘制 ----------------
    def draw(self, w, h, progress=0.0, overlay=()):
        """overlay：额外的文字 Label（HUD 等）。

        ★ 必须和 UI 在**同一个正交投影**里画。三维那边用的是 gluPerspective，
          拿屏幕坐标（x=8, y=height-16）的 Label 直接在透视矩阵下画会被投到
          屏幕外 —— 表现就是"HUD 文字完全看不见"。
        """
        if not self.enabled:
            return
        self.progress = progress
        if self._need_relayout(w, h):
            self.layout(w, h)
        # 切到屏幕正交坐标系
        glMatrixMode(GL_PROJECTION); glPushMatrix(); glLoadIdentity()
        glOrtho(0, w, 0, h, -1, 1)
        glMatrixMode(GL_MODELVIEW); glPushMatrix(); glLoadIdentity()
        # ★ 三维那边留下的状态必须清掉，否则矩形会被"上一张绑定的贴图"调制、
        #   被 alpha test 剪掉、或者被背面剔除吞掉 —— 表现就是"按钮文字在、
        #   底色不见了"。
        glDisable(GL_DEPTH_TEST)
        glDisable(GL_LIGHTING)
        glDisable(GL_TEXTURE_2D)
        glDisable(GL_ALPHA_TEST)
        glDisable(GL_CULL_FACE)
        glDisable(GL_SCISSOR_TEST)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        glColor4f(1.0, 1.0, 1.0, 1.0)     # 别让残留的材质色把 UI 染色
        self._batch.draw()
        for lb in self._labels:
            lb.draw()
        for lb in overlay:
            lb.draw()
        glDisable(GL_BLEND)
        glMatrixMode(GL_MODELVIEW); glPopMatrix()
        glMatrixMode(GL_PROJECTION); glPopMatrix()
        glEnable(GL_DEPTH_TEST)

    # ---------------- 命中测试 ----------------
    def _hit_button(self, x, y):
        for b in self.buttons:
            if b.enabled and b.x <= x <= b.x + b.w and b.y <= y <= b.y + b.h:
                return b
        return None

    def _hit_track(self, x, y):
        if not self.track:
            return False
        tx, ty, tw, th = self.track
        return tx - 4 <= x <= tx + tw + 4 and ty - 8 <= y <= ty + th + 8

    def on_mouse_press(self, x, y, button, mods):
        if not self.enabled:
            return False
        b = self._hit_button(x, y)
        if b:
            self.pressed = b
            self.refresh()
            return True
        if self._hit_track(x, y):
            self.seeking = True
            self._seek(x)
            return True
        return False

    def on_mouse_release(self, x, y, button, mods):
        if self.pressed:
            b = self._hit_button(x, y)
            # 宽容度：按下和松开之间鼠标挪了一两个像素也算点了这个按钮
            if b is not self.pressed:
                p = self.pressed
                if (p.x - 6 <= x <= p.x + p.w + 6
                        and p.y - 6 <= y <= p.y + p.h + 6):
                    b = p
            if b is self.pressed and b.cb:
                b.cb()
            self.pressed = None
            self.refresh()
            return True
        if self.seeking:
            self.seeking = False
            return True
        return False

    def on_mouse_drag(self, x, y, dx, dy, buttons, mods):
        if self.seeking:
            self._seek(x)
            return True
        return False

    def on_mouse_motion(self, x, y, dx, dy):
        if not self.enabled:
            return False
        b = self._hit_button(x, y)
        over_track = self._hit_track(x, y)
        if b is not self.hover:
            self.hover = b
            self.refresh()
        self.tooltip = (b.tip if (b and b.tip) else
                        ("按住拖动跳帧 / 点击跳帧" if over_track else
                         (self.tooltip_getter() if self.tooltip_getter else "")))
        return bool(b or over_track)

    def _seek(self, x):
        if not (self.track and self.on_seek):
            return
        tx, _ty, tw, _th = self.track
        frac = min(1.0, max(0.0, (x - tx) / max(1, tw)))
        self.on_seek(frac)


# ---------------------------------------------------------------------------
#  视图预设（和工程 render.py 的视角习惯一致：+Y 是角色正前方）
# ---------------------------------------------------------------------------
VIEWS = {
    "front":   (0.0, 0.0),
    "3/4":     (0.62, 0.10),
    "side":    (1.5708, 0.0),
    "back":    (3.1416, 0.0),
}