"""可复用的小组件：卡片、标签、徽章、头像、步骤条、统计块、错误卡片（设计稿 07）。"""
from PySide6.QtCore import Qt, Signal, QTimer, QRectF, QSize
from PySide6.QtGui import QPainter, QColor, QLinearGradient, QFont, QPen
from PySide6.QtWidgets import (QFrame, QLabel, QHBoxLayout, QVBoxLayout, QWidget, QPushButton, QSizePolicy)
from . import theme as T
from .. import errors as E


def label(text="", role=None, wrap=False, sel=False):
    l = QLabel(text)
    if role:
        l.setProperty("role", role)
    l.setWordWrap(wrap)
    if sel:
        l.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return l


def chip(text, kind="purple", icon_name=None):
    l = QLabel(text)
    l.setProperty("chip", kind)
    if icon_name:  # 图标 + 文字：用富文本内嵌不方便，改为前置符号
        l.setText(("✓ " if icon_name == "check" else "") + text)
    l.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
    return l


def restyle(w):
    w.style().unpolish(w)
    w.style().polish(w)
    w.update()


def button(text, kind=None, icon_name=None, icon_color=None):
    b = QPushButton(text)
    if kind:
        b.setObjectName(kind)
    if icon_name:
        col = icon_color or ("#FFFFFF" if kind == "primary" else (T.PURPLE_DARK if kind in ("link", "soft") else T.TEXT))
        b.setIcon(T.icon(icon_name, col, 16))
        b.setIconSize(QSize(16, 16))
    b.setCursor(Qt.PointingHandCursor)
    return b


def icon_label(name, color=T.PURPLE, size=16):
    l = QLabel()
    l.setPixmap(T.pixmap(name, color, size))
    l.setFixedSize(size, size)
    return l


class Card(QFrame):
    def __init__(self, kind="card", margins=(20, 18, 20, 18), spacing=12, horizontal=False):
        super().__init__()
        if kind in ("card", "tile", "option"):
            self.setProperty(kind, True)
        else:
            self.setProperty("banner", kind)
        self.lay = (QHBoxLayout if horizontal else QVBoxLayout)(self)
        self.lay.setContentsMargins(*margins)
        self.lay.setSpacing(spacing)


def divider():
    f = QFrame()
    f.setObjectName("divider")
    return f


def hbox(*items, spacing=8, margins=(0, 0, 0, 0)):
    w = QWidget()
    l = QHBoxLayout(w)
    l.setContentsMargins(*margins)
    l.setSpacing(spacing)
    for it in items:
        if it is None:
            l.addStretch(1)
        elif isinstance(it, int):
            l.addSpacing(it)
        else:
            l.addWidget(it)
    return w


def vbox(*items, spacing=4, margins=(0, 0, 0, 0)):
    w = QWidget()
    l = QVBoxLayout(w)
    l.setContentsMargins(*margins)
    l.setSpacing(spacing)
    for it in items:
        if it is None:
            l.addStretch(1)
        else:
            l.addWidget(it)
    return w


class IconBadge(QWidget):
    """圆角方形浅色底 + 图标。"""

    def __init__(self, name, color=T.PURPLE, bg=T.PURPLE_SOFT, size=40, icon_size=20, radius=12, circle=False):
        super().__init__()
        self.setFixedSize(size, size)
        self.name, self.color, self.bg, self.icon_size = name, color, bg, icon_size
        self.radius = size / 2 if circle else radius
        self.angle = 0.0

    def set_icon(self, name, color=None, bg=None):
        self.name, self.color, self.bg = name, color or self.color, bg or self.bg
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(self.bg))
        p.drawRoundedRect(QRectF(0, 0, self.width(), self.height()), self.radius, self.radius)
        pm = T.pixmap(self.name, self.color, self.icon_size, self.angle)
        p.drawPixmap(int((self.width() - self.icon_size) / 2), int((self.height() - self.icon_size) / 2), pm)


class Spinner(IconBadge):
    def __init__(self, size=64):
        super().__init__("spinner", T.PURPLE, T.PURPLE_SOFT, size, 30, circle=True)
        self.t = QTimer(self)
        self.t.timeout.connect(self._tick)
        self.t.start(40)

    def _tick(self):
        self.angle = (self.angle + 12) % 360
        self.update()


class Avatar(QWidget):
    """渐变圆形头像，显示首字母（设计稿 04/05c）。"""

    def __init__(self, text="M", size=56, colors=("#F0A6CA", "#9B8AF7")):
        super().__init__()
        self.setFixedSize(size, size)
        self.text, self.colors = text, colors

    def set_text(self, t):
        self.text = (t or "?").strip()[:1].upper() or "?"
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        g = QLinearGradient(0, 0, self.width(), self.height())
        g.setColorAt(0, QColor(self.colors[0]))
        g.setColorAt(1, QColor(self.colors[1]))
        p.setPen(Qt.NoPen)
        p.setBrush(g)
        p.drawEllipse(0, 0, self.width(), self.height())
        f = QFont(self.font())
        f.setPixelSize(int(self.height() * 0.42))
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor("#FFFFFF"))
        p.drawText(self.rect(), Qt.AlignCenter, self.text)


class Logo(QWidget):
    def __init__(self, size=34):
        super().__init__()
        self.setFixedSize(size, size)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        g = QLinearGradient(0, 0, self.width(), self.height())
        g.setColorAt(0, QColor(T.PURPLE))
        g.setColorAt(1, QColor(T.BLUE))
        p.setPen(Qt.NoPen)
        p.setBrush(g)
        p.drawRoundedRect(QRectF(0, 0, self.width(), self.height()), self.width() * 0.26, self.width() * 0.26)
        f = QFont(self.font())
        f.setPixelSize(int(self.height() * 0.5))
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor("#FFFFFF"))
        p.drawText(self.rect(), Qt.AlignCenter, "S")


class StepDot(QWidget):
    """步骤圆点：pending（白底灰边数字）/ current（渐变数字）/ done（渐变对勾）。"""

    def __init__(self, n, size=24):
        super().__init__()
        self.n, self.state = n, "pending"
        self.setFixedSize(size, size)

    def set_state(self, s):
        self.state = s
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(1, 1, self.width() - 2, self.height() - 2)
        if self.state == "pending":
            p.setPen(QPen(QColor("#DAD7E5"), 1.2))
            p.setBrush(QColor("#FFFFFF"))
            p.drawEllipse(r)
            col = QColor(T.MUTED)
        else:
            g = QLinearGradient(0, 0, self.width(), self.height())
            g.setColorAt(0, QColor(T.PURPLE))
            g.setColorAt(1, QColor("#7FA3F9"))
            p.setPen(Qt.NoPen)
            p.setBrush(g)
            p.drawEllipse(r)
            col = QColor("#FFFFFF")
        if self.state == "done":
            s = int(self.width() * 0.55)
            p.drawPixmap(int((self.width() - s) / 2), int((self.height() - s) / 2), T.pixmap("check", "#FFFFFF", s))
        else:
            f = QFont(self.font())
            f.setPixelSize(int(self.height() * 0.46))
            f.setBold(True)
            p.setFont(f)
            p.setPen(col)
            p.drawText(self.rect(), Qt.AlignCenter, str(self.n))


STEPS = [("连接 iPhone", "USB 连接并信任"), ("提取存档", "仅保留游戏数据"),
         ("登录 StarMoe", "浏览器授权"), ("上传", "同步到 bdon.moe")]


class SideStep(QFrame):
    def __init__(self, n, title, sub):
        super().__init__()
        self.setObjectName("sidestep")
        l = QHBoxLayout(self)
        l.setContentsMargins(10, 8, 10, 8)
        l.setSpacing(10)
        self.dot = StepDot(n)
        l.addWidget(self.dot)
        self.t = label(title)
        self.s = label(sub, "muted")
        l.addWidget(vbox(self.t, self.s, spacing=1))
        self.set_state("pending", False)

    def set_state(self, state, current):
        self.dot.set_state(state)
        self.setStyleSheet("QFrame#sidestep { background: %s; border-radius: 10px; }" % ("#EFEBFD" if current else "transparent"))
        self.t.setStyleSheet("font-weight: 600; color: %s;" % (T.TEXT if state != "pending" or current else T.TEXT2))


class Sidebar(QWidget):
    settings_clicked = Signal()
    region_clicked = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("sidebar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedWidth(210)
        l = QVBoxLayout(self)
        l.setContentsMargins(14, 22, 14, 16)
        l.setSpacing(4)
        brand = hbox(Logo(34), vbox(label("StarMoe Box", "cardtitle"), label("iOS 存档提取 · 开源版", "muted"), spacing=0),
                     None, spacing=10, margins=(6, 0, 0, 0))
        l.addWidget(brand)
        l.addSpacing(18)
        l.addWidget(label("步骤", "muted"))
        self.steps = [SideStep(i + 1, *s) for i, s in enumerate(STEPS)]
        for s in self.steps:
            l.addWidget(s)
        l.addStretch(1)
        self.region = QPushButton()
        self.region.setIcon(T.icon("globe", T.TEXT2, 15))
        self.region.setStyleSheet("QPushButton { text-align: left; font-weight: 500; font-size: 11px; padding: 8px 8px;"
                                  " border-radius: 10px; background: #FFFFFF; }")
        self.region.setCursor(Qt.PointingHandCursor)
        self.region.clicked.connect(self.region_clicked)
        l.addWidget(self.region)
        l.addSpacing(4)
        st = button("设置与关于", "side", "sliders", T.TEXT)
        st.clicked.connect(self.settings_clicked)
        l.addWidget(st)

    def set_step(self, current, done_upto):
        """current: 0..3 当前步骤；done_upto: 已完成的步骤数。"""
        for i, s in enumerate(self.steps):
            s.set_state("done" if i < done_upto else ("current" if i == current else "pending"), i == current)

    def set_region(self, text):
        self.region.setToolTip(text)
        fm = self.region.fontMetrics()
        self.region.setText(fm.elidedText(text, Qt.ElideRight, 160))


class Stepper(QWidget):
    """欢迎页的横向四步。"""

    def __init__(self):
        super().__init__()
        l = QHBoxLayout(self)
        l.setContentsMargins(0, 0, 0, 0)
        l.setSpacing(0)
        for i, (t, s) in enumerate(STEPS):
            d = StepDot(i + 1, 32)
            d.set_state("current" if i == 0 else "pending")
            col = vbox(hbox(None, d, None), label(t), label(s, "muted"), spacing=4)
            for w in col.findChildren(QLabel):
                w.setAlignment(Qt.AlignCenter)
            col.setFixedWidth(120)
            l.addWidget(col)
            if i < 3:
                line = QFrame()
                line.setFixedHeight(2)
                line.setStyleSheet("background: #E6E3EF; border: none;")
                l.addWidget(vbox(line, None, margins=(0, 15, 0, 0)), 1)


class StatTile(Card):
    """四张等宽统计卡。数值从 20px 往下缩，仍放不下才省略，避免「84.5 MB/s」被裁成「84.5 MB/」。"""

    def __init__(self, icon_name, title, value="—"):
        super().__init__("tile", (14, 12, 14, 12), 6)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self._title = label(title, "small")
        self.lay.addWidget(hbox(icon_label(icon_name, T.PURPLE, 14), self._title, None, spacing=6))
        self.v = label(value, "stat")
        self.v.setMinimumWidth(0)
        self.v.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.lay.addWidget(self.v)
        self._full = str(value)

    def set(self, v):
        self._full = str(v)
        self._fit()

    def set_title(self, text):
        self._title.setText(text)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit()

    def _fit(self):
        from PySide6.QtGui import QFontMetrics
        text = self._full
        avail = self.v.width()
        if avail < 8:
            avail = max(8, self.width() - 28)
        size = 20
        shown = text
        while size >= 14:
            self.v.setStyleSheet(f"font-size: {size}px; font-weight: 700; color: {T.TEXT};")
            width = QFontMetrics(self.v.font()).horizontalAdvance(text)
            if width <= avail:
                self.v.setText(text)
                return
            size -= 1
        self.v.setStyleSheet(f"font-size: 14px; font-weight: 700; color: {T.TEXT};")
        shown = QFontMetrics(self.v.font()).elidedText(text, Qt.ElideRight, avail)
        self.v.setText(shown)


class Option(Card):
    """服务器选择项。"""
    clicked = Signal()

    def __init__(self, title, sub):
        super().__init__("option", (14, 12, 14, 12), 10, horizontal=True)
        self.radio = QLabel()
        self.radio.setFixedSize(16, 16)
        self.lay.addWidget(self.radio)
        self.lay.addWidget(vbox(label(title, "value"), label(sub, "muted"), spacing=1))
        self.lay.addStretch(1)
        self.tag = chip("已选择", "white")
        self.lay.addWidget(self.tag)
        self.setCursor(Qt.PointingHandCursor)
        self.set_selected(False)

    def set_selected(self, on):
        self.setProperty("selected", on)
        self.tag.setVisible(on)
        self.radio.setStyleSheet(
            f"border-radius: 8px; border: {'5px solid ' + T.PURPLE if on else '1.5px solid #D5D2E0'}; background: #FFFFFF;")
        restyle(self)

    def mousePressEvent(self, e):
        self.clicked.emit()


class SegmentedControl(QWidget):
    """两段（或多段）圆角切换。选中项用主题紫蓝渐变 + 白字，未选中透明深色字。"""
    changed = Signal(str)

    def __init__(self, items, current=None):
        super().__init__()
        self.setObjectName("segment")
        self._keys = [k for k, _ in items]
        self._value = current if current in self._keys else self._keys[0]
        self.setFixedHeight(36)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(3, 3, 3, 3)
        lay.setSpacing(2)
        self._buttons = {}
        for key, text in items:
            b = QPushButton(text)
            b.setCursor(Qt.PointingHandCursor)
            b.setFocusPolicy(Qt.NoFocus)
            b.setFixedHeight(30)
            b.clicked.connect(lambda _=False, k=key: self._pick(k))
            self._buttons[key] = b
            lay.addWidget(b)
        self._restyle()

    def value(self):
        return self._value

    def set_value(self, key):
        if key not in self._buttons or key == self._value:
            return
        self._value = key
        self._restyle()
        self.changed.emit(key)

    def _pick(self, key):
        self.set_value(key)

    def _restyle(self):
        self.setStyleSheet("QWidget#segment { background: #F3F1FA; border-radius: 18px; }")
        for key, b in self._buttons.items():
            if key == self._value:
                b.setStyleSheet(
                    f"QPushButton {{ background: {T.GRAD}; color: #FFFFFF; border: none;"
                    f" border-radius: 15px; padding: 4px 16px; font-weight: 700; }}")
            else:
                b.setStyleSheet(
                    f"QPushButton {{ background: transparent; color: {T.TEXT}; border: none;"
                    f" border-radius: 15px; padding: 4px 16px; font-weight: 600; }}"
                    "QPushButton:hover { background: rgba(139, 124, 246, 0.14); }")


# ---- 错误卡片（设计稿 07） -------------------------------------------------------------
# code: (图标, 前景色, 底色, 标题, 步骤, 默认说明, [(按钮文字, action, 图标)])
ERRORS = {
    E.ERR_NO_DEVICE: ("phone", T.ORANGE, "#FFF3DF", "未检测到设备", "步骤 1",
                      "请用数据线把 iPhone 连到电脑，并解锁手机。手机上弹出“要信任此电脑吗？”时点“信任”。",
                      [("重新检测", "redetect", "refresh"), ("查看帮助", "help", None)]),
    E.ERR_NOT_TRUSTED: ("lock", T.ORANGE, "#FFF3DF", "等待信任此电脑", "步骤 1",
                        "请解锁 iPhone，在“要信任此电脑吗？”弹窗中点“信任”并输入锁屏密码。",
                        [("重新检测", "redetect", "refresh"), ("查看帮助", "help", None)]),
    E.ERR_NOT_INSTALLED: ("phone", T.ORANGE, "#FFF3DF", "手机上没有安装所选服务器的游戏", "步骤 1",
                          "这台手机上没找到所选服务器的游戏。玩的是日服？点“切换服务器”。",
                          [("重新检测", "redetect", "refresh"), ("切换服务器", "region", None)]),
    E.ERR_BACKUP_DENIED: ("xcircle", T.RED, T.RED_BG, "手机拒绝备份", "步骤 2",
                          "手机没有同意传输数据。请保持手机解锁再试一次；如果手机要求输入密码，请输入锁屏密码。",
                          [("重试", "retry", "refresh"), ("输入备份密码", "password", None)]),
    E.ERR_DISCONNECTED: ("refresh", T.ORANGE, "#FFF3DF", "连接中断", "步骤 2",
                         "自动重试了几次还是断开。换一根数据线或 USB 口，保持手机亮屏解锁，再试一次。",
                         [("重试", "retry", "refresh"), ("返回", "back", None)]),
    E.ERR_DISK: ("alert", T.RED, T.RED_BG, "电脑空间不足", "步骤 2", "电脑硬盘剩余空间不足 2 GB，请清理一些文件后重试（实际只会占用十几 MB）。",
                 [("重试", "retry", "refresh")]),
    E.ERR_PASSWORD: ("lock", T.RED, T.RED_BG, "需要备份密码", "步骤 2",
                     "你的手机开启了“加密本地备份”，需要输入当时设置的备份密码（不是锁屏密码）。",
                     [("输入备份密码", "password", None), ("重试", "rescan", "refresh")]),
    E.ERR_KEYS: ("key", T.RED, T.RED_BG, "密钥加载失败", "准备",
                 "没能拿到解密密钥。点“自动获取密钥”重试；网络不好时，也可以手动选择已下载的官方 StarMoe Box 安卓安装包（.apk）。",
                 [("自动获取密钥", "auto_keys", "download"), ("手动选择 APK", "reload_keys", None)]),
    E.ERR_DECRYPT: ("key", T.RED, T.RED_BG, "解密失败（密钥可能已更新）", "步骤 2",
                    "已自动检查过最新版密钥，仍然无法解密。可能游戏刚更新、官方 StarMoe Box 还没跟上，请过几天再试，或手动选择最新的官方 APK。",
                    [("重新获取密钥", "auto_keys", "download"), ("手动选择 APK", "reload_keys", None)]),
    E.ERR_NO_SAVE: ("folder", T.ORANGE, "#FFF3DF", "没有找到存档", "步骤 2",
                    "没找到存档。请确认服务器选对了，并且游戏在这台手机上登录过。",
                    [("重新提取", "retry", "refresh"), ("从文件夹导入", "folder", None)]),
    E.ERR_AUTH: ("user", T.RED, T.RED_BG, "登录失败", "步骤 3", "登录没有完成，请重新登录。",
                 [("重新登录", "relogin", "external"), ("稍后", "dismiss", None)]),
    E.ERR_AUTH_EXPIRED: ("clock", T.ORANGE, "#FFF3DF", "登录过期", "步骤 3/4",
                         "登录已过期，请重新登录后再上传。已提取的存档还在，不用重新连接手机。",
                         [("重新登录", "relogin", "external"), ("稍后", "dismiss", None)]),
    E.ERR_NETWORK: ("alert", T.RED, T.RED_BG, "网络或服务器错误", "步骤 4", "网络好像不太通畅，请稍后点“重试”。",
                    [("重试", "upload", "refresh"), ("稍后", "dismiss", None)]),
}


class ErrorCard(Card):
    action = Signal(str)

    def __init__(self, code, message=None, detail=None):
        super().__init__("card", (20, 18, 20, 18), 10)
        ic, fg, bg, title, step, default, actions = ERRORS.get(code, ERRORS[E.ERR_NETWORK])
        self.code = code
        head = hbox(IconBadge(ic, fg, bg, 40, 20), vbox(label(title, "cardtitle"), label(f"{code} · {step}", "muted"),
                                                        spacing=1), None, spacing=12)
        self.lay.addWidget(head)
        body = label(message or default, "small", wrap=True, sel=True)
        self.lay.addWidget(body)
        if detail:
            d = label(str(detail)[:300], "muted", wrap=True, sel=True)
            d.setToolTip(str(detail))
            self.lay.addWidget(d)
        self.lay.addStretch(1)
        btns = []
        for i, (text, act, icn) in enumerate(actions):
            b = button(text, "primary" if i == 0 else None, icn)
            b.clicked.connect(lambda _=False, a=act: self.action.emit(a))
            btns.append(b)
        self.lay.addWidget(hbox(*btns, None, spacing=8))
