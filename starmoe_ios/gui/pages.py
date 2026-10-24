"""各步骤页面（设计稿 01–06）。页面只负责显示，动作通过信号交给 MainWindow。"""
import time
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLineEdit, QProgressBar, QStackedWidget,
                               QComboBox, QSizePolicy, QLabel)
from . import theme as T
from .widgets import (label, chip, button, icon_label, Card, divider, hbox, vbox, IconBadge, Spinner, Avatar, Stepper,
                      StatTile, Option, ErrorCard, restyle)
from .. import core


def human_bytes(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024


def mmss(sec):
    sec = int(sec)
    return f"{sec // 3600}:{sec % 3600 // 60:02d}:{sec % 60:02d}" if sec >= 3600 else f"{sec // 60:02d}:{sec % 60:02d}"


class Page(QWidget):
    action = Signal(str)   # 统一的动作信号（错误卡片按钮等）

    def __init__(self, title, subtitle):
        super().__init__()
        self.setObjectName("page")
        root = QVBoxLayout(self)
        root.setContentsMargins(26, 24, 26, 22)
        root.setSpacing(14)
        self.title = label(title, "h1")
        self.subtitle = label(subtitle, "sub", wrap=True)
        root.addWidget(vbox(self.title, self.subtitle, spacing=6))
        self.body = QVBoxLayout()
        self.body.setSpacing(14)
        root.addLayout(self.body, 1)
        self.footer = QHBoxLayout()
        self.footer.setSpacing(10)
        root.addLayout(self.footer)
        self.error = None

    def show_error(self, code, message=None, detail=None, index=0):
        self.clear_error()
        self.error = ErrorCard(code, message, detail)
        self.error.action.connect(self.action)
        self.body.insertWidget(index, self.error)

    def clear_error(self):
        if self.error:
            self.error.setParent(None)
            self.error.deleteLater()
            self.error = None


# ---- 01 欢迎（极简：一个“开始”按钮） --------------------------------------------------------
class WelcomePage(Page):
    server_changed = Signal(str)

    def __init__(self):
        super().__init__("欢迎使用 StarMoe Box",
                         "把 iPhone 上《BanG Dream! Our Notes》的存档同步到 bdon.moe（Moenotes）。插上手机，点“开始”就行。")
        st = Card("card", (20, 16, 20, 16), 14)
        st.lay.addWidget(label("只需四步，全程自动", "cardtitle"))
        st.lay.addWidget(Stepper())
        self.body.addWidget(st)
        self.steps = st

        # 准备情况：服务器 + 密钥（默认都不用管）
        prep = Card("card", (20, 14, 20, 14), 10)
        self.srv_text = label("", "value")
        self.btn_srv = button("更改", "link")
        self.btn_srv.clicked.connect(lambda: self.srv_opts.setVisible(not self.srv_opts.isVisible()))
        prep.lay.addWidget(hbox(IconBadge("globe", T.PURPLE, T.PURPLE_SOFT, 34, 17, 10),
                                vbox(label("服务器", "muted"), self.srv_text, spacing=0), None, self.btn_srv, spacing=12))
        self.opt = {"intl": Option("国际服", "com.bilibili.sirius（繁中 / EN / KR）"), "jp": Option("日服", "com.bushiroad.sirius")}
        for k, o in self.opt.items():
            o.clicked.connect(lambda k=k: (self.server_changed.emit(k), self.srv_opts.hide()))
        self.srv_opts = hbox(*self.opt.values(), spacing=10, margins=(46, 0, 0, 0))
        self.srv_opts.hide()
        prep.lay.addWidget(self.srv_opts)
        prep.lay.addWidget(divider())
        self.key_chip = chip("未就绪", "orange")
        self.key_text = label("", "value")
        self.key_sub = label("", "muted", wrap=True)
        self.btn_auto = button("自动获取密钥", "soft", "download")
        self.btn_auto.clicked.connect(lambda: self.action.emit("auto_keys"))
        self.btn_manual = button("手动选择 APK…", "link")
        self.btn_manual.clicked.connect(lambda: self.action.emit("reload_keys"))
        prep.lay.addWidget(hbox(IconBadge("key", T.PURPLE, T.PURPLE_SOFT, 34, 17, 10),
                                vbox(hbox(label("解密密钥", "muted"), self.key_chip, None, spacing=6), self.key_text,
                                     self.key_sub, spacing=1),
                                self.btn_auto, self.btn_manual, spacing=12))
        prep.lay.itemAt(prep.lay.count() - 1).widget().layout().setStretch(1, 1)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(6)
        self.bar.hide()
        prep.lay.addWidget(self.bar)
        self.body.addWidget(prep)
        self.err_slot = 2
        self.body.addStretch(1)

        self.btn_next = button("开始", "primary", "plug")
        self.btn_next.setMinimumSize(260, 52)
        self.btn_next.setStyleSheet("font-size: 18px; border-radius: 14px;")
        self.btn_next.clicked.connect(lambda: self.action.emit("next"))
        self.body.addWidget(hbox(None, self.btn_next, None))
        self.consent = label("", "muted", wrap=True)
        self.consent.setAlignment(Qt.AlignCenter)
        self.body.addWidget(self.consent)

        self.footer.addWidget(label("开源 · Apache-2.0 · 非官方工具", "muted"))
        self.footer.addStretch(1)
        self.btn_folder = button("已有游戏文件？从文件夹导入", "link", "folder")
        self.btn_folder.clicked.connect(lambda: self.action.emit("folder"))
        self.footer.addWidget(self.btn_folder)
        self.set_keys(None)

    def set_server(self, s):
        for k, o in self.opt.items():
            o.set_selected(k == s)
        self.srv_text.setText({"intl": "国际服（繁中 / EN / KR）", "jp": "日服"}.get(s, s))

    def set_keys(self, info, consented=False):
        """info: None 或 {kind: auto|apk|keys|env, file, date, tag}"""
        ok = bool(info)
        self.bar.hide()
        self.key_chip.setText("✓ 已就绪" if ok else "未就绪")
        self.key_chip.setProperty("chip", "green" if ok else "orange")
        restyle(self.key_chip)
        if ok:
            self.key_text.setText({"auto": f"官方 StarMoe Box {info.get('tag', '')}（自动获取）",
                                   "apk": "官方 StarMoe Box APK（手动选择）", "keys": "密钥文件",
                                   "env": "环境变量"}.get(info["kind"], "已加载"))
            self.key_sub.setText("来源：" + " · ".join(x for x in (info.get("file"), info.get("date")) if x))
        else:
            self.key_text.setText("首次使用会自动获取")
            self.key_sub.setText("从 GitHub 官方发布页下载安装包（约 1.4 MB），只在本机读取。")
        self.btn_auto.setText("检查更新" if ok and info["kind"] == "auto" else "自动获取密钥")
        self.btn_auto.setVisible(not ok or info["kind"] == "auto")
        self.btn_next.setEnabled(True)
        self.btn_next.setText("开始")
        self.consent.setText("" if ok or consented else
                             "点击“开始”即表示同意从 GitHub（StarMoe-org/StarMoe-box）下载官方安装包以读取密钥；密钥不随本软件分发，也不会上传。")

    def set_fetching(self, text, done=0, total=0):
        self.clear_error()
        self.key_chip.setText("获取中")
        self.key_chip.setProperty("chip", "blue")
        restyle(self.key_chip)
        self.key_text.setText(text)
        self.key_sub.setText(f"{human_bytes(done)} / {human_bytes(total)}" if total else "连接 GitHub…")
        self.bar.show()
        if total:
            self.bar.setRange(0, 1000)
            self.bar.setValue(int(done * 1000 / total))
        else:
            self.bar.setRange(0, 0)
        self.btn_auto.hide()
        self.btn_next.setEnabled(False)
        self.btn_next.setText("正在准备…")

    def show_error(self, code, message=None, detail=None, index=None):
        super().show_error(code, message, detail, self.err_slot if index is None else index)
        self.steps.hide()   # 出错时把步骤说明让出来，给错误提示留位置

    def clear_error(self):
        super().clear_error()
        self.steps.show()


# ---- 02 连接设备 -------------------------------------------------------------------------
class DevicePage(Page):
    def __init__(self):
        super().__init__("连接 iPhone", "用数据线把 iPhone 连到电脑并解锁。手机上弹出“要信任此电脑吗？”时，点“信任”。")
        row = QHBoxLayout()
        row.setSpacing(14)
        self.left = QVBoxLayout()
        self.left.setSpacing(14)
        # 设备卡片
        self.dev = Card("card", (20, 20, 20, 16), 12)
        self.dev_icon = IconBadge("phone", T.PURPLE, T.PURPLE_SOFT, 50, 24, 14)
        self.dev_name = label("正在检测设备…", "h2")
        self.dev_info = label("", "small")
        self.chips = hbox(None, spacing=6)
        self.dev.lay.addWidget(hbox(self.dev_icon, vbox(self.dev_name, self.dev_info, self.chips, spacing=4), None, spacing=14))
        self.dev.lay.addWidget(divider())
        self.app_line_icon = icon_label("check", T.GREEN, 14)
        self.app_line = label("", "small", wrap=True)
        self.dev.lay.addWidget(hbox(self.app_line_icon, self.app_line, spacing=8))
        self.left.addWidget(self.dev)
        # 加密备份面板
        self.enc = Card("orange", (18, 16, 18, 14), 10)
        self.enc.lay.addWidget(hbox(IconBadge("lock", T.ORANGE, "#FFFFFF", 34, 18, 10),
                                    vbox(label("请输入备份密码", "cardtitle"),
                                         label("这台手机开启过“加密本地备份”，需要当时设置的备份密码（不是锁屏密码）。只在本机使用，不保存、不上传。", "small",
                                               wrap=True), spacing=2), spacing=12))
        self.pw = QLineEdit()
        self.pw.setEchoMode(QLineEdit.Password)
        self.pw.setPlaceholderText("备份密码")
        self.pw.addAction(T.icon("lock", T.MUTED, 16), QLineEdit.LeadingPosition)
        eye = self.pw.addAction(T.icon("eye", T.MUTED, 16), QLineEdit.TrailingPosition)
        eye.triggered.connect(lambda: self.pw.setEchoMode(
            QLineEdit.Normal if self.pw.echoMode() == QLineEdit.Password else QLineEdit.Password))
        self.pw.textChanged.connect(lambda _: self.action.emit("validate"))
        self.enc.lay.addWidget(self.pw)
        self.enc.lay.addWidget(label("忘记密码？可在 iPhone 设置 › 通用 › 传输或还原 › 还原 › 还原所有设置 中重置（不会删除数据）",
                                     "muted", wrap=True))
        self.left.addWidget(self.enc)
        self.left.addStretch(1)
        row.addLayout(self.left, 3)
        # 右侧检查清单
        tips = Card("card", (20, 18, 20, 18), 14)
        tips.lay.addWidget(label("连接前请确认", "cardtitle"))
        for i, (t, s) in enumerate([("信任此电脑", "首次连接时，在 iPhone 弹窗中点击“信任”并输入锁屏密码。"),
                                    ("保持 iPhone 解锁", "提取过程中请保持屏幕点亮且解锁。"),
                                    ("关闭自动锁屏", "设置 › 显示与亮度 › 自动锁定 › 永不（完成后可改回）。")]):
            n = label(str(i + 1))
            n.setAlignment(Qt.AlignCenter)
            n.setFixedSize(22, 22)
            n.setStyleSheet(f"background: {T.PURPLE_SOFT}; color: {T.PURPLE_DARK}; border-radius: 11px; font-weight: 600;")
            tl, sl = label(t, "value"), label(s, "small", wrap=True)
            tl.setAlignment(Qt.AlignLeft)
            sl.setAlignment(Qt.AlignLeft)
            row_w = hbox(vbox(n, None), vbox(tl, sl, spacing=2), spacing=10)
            row_w.layout().setStretch(1, 1)
            tips.lay.addWidget(row_w)
        tips.lay.addWidget(divider())
        tips.lay.addWidget(hbox(vbox(icon_label("info", T.BLUEINFO, 13), None),
                                label("Windows 需安装 Apple 设备支持（Apple Devices 或 iTunes）。", "muted", wrap=True),
                                spacing=6))
        tips.lay.addStretch(1)
        row.addWidget(tips, 2)
        self.body.addLayout(row, 1)

        self.btn_refresh = button("刷新设备", None, "refresh")
        self.btn_refresh.clicked.connect(lambda: self.action.emit("redetect"))
        self.footer.addWidget(self.btn_refresh)
        b = button("从文件夹导入…", "link", "folder")
        b.clicked.connect(lambda: self.action.emit("folder"))
        self.footer.addWidget(b)
        self.footer.addStretch(1)
        back = button("上一步")
        back.clicked.connect(lambda: self.action.emit("back"))
        self.footer.addWidget(back)
        self.btn_start = button("开始提取存档", "primary", "download")
        self.btn_start.clicked.connect(self._start_now)
        self.footer.addWidget(self.btn_start)
        # 检测到设备且不需要密码时，倒数几秒自动开始
        self.auto = label("", "small")
        self.auto.setStyleSheet(f"color: {T.PURPLE_DARK};")
        self.btn_wait = button("先等等", "link")
        self.btn_wait.clicked.connect(self.stop_countdown)
        self.auto_row = hbox(icon_label("clock", T.PURPLE, 14), self.auto, self.btn_wait, None, spacing=6)
        self.auto_row.hide()
        self.left.insertWidget(1, self.auto_row)
        self.count = 0
        self.auto_start = True
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.set_searching()

    def start_countdown(self, n=3):
        if not self.auto_start:
            return
        self.count = n
        self.auto_row.show()
        self._show_count()
        self.timer.start(1000)

    def _show_count(self):
        self.auto.setText(f"一切就绪，{self.count} 秒后自动开始提取…")
        self.btn_start.setText(f"开始提取存档（{self.count}）")

    def stop_countdown(self):
        self.timer.stop()
        self.auto_row.hide()
        self.btn_start.setText("开始提取存档")

    def _tick(self):
        self.count -= 1
        if self.count <= 0:
            self._start_now()
        else:
            self._show_count()

    def _start_now(self):
        self.stop_countdown()
        if self.btn_start.isEnabled():
            self.action.emit("start")

    def _chips(self, items):
        lay = self.chips.layout()
        while lay.count():
            w = lay.takeAt(0).widget()
            if w:
                w.deleteLater()
        for text, kind in items:
            lay.addWidget(chip(text, kind))
        lay.addStretch(1)

    def set_searching(self, text="正在查找 iPhone…"):
        self.stop_countdown()
        self.clear_error()
        self.dev.show()
        self.dev_name.setText(text)
        self.dev_info.setText("请用数据线连接 iPhone，并保持手机解锁")
        self._chips([])
        self.app_line.setText("等待设备…")
        self.app_line_icon.setPixmap(T.pixmap("clock", T.MUTED, 14))
        self.enc.hide()
        self.info = None
        self.btn_start.setEnabled(False)

    def set_device(self, info, server_name):
        self.clear_error()
        self.dev.show()
        self.info = info
        self.dev_name.setText(info["name"])
        cap = f" · {round(info['capacity'] / 1e9)} GB" if info.get("capacity") else ""
        self.dev_info.setText(" · ".join(x for x in (info.get("model"), "iOS " + info["ios"] if info.get("ios") else "") if x) + cap)
        self._chips([("✓ 已信任", "green"), ("USB 已连接", "blue")])
        if info["installed"]:
            v = f" v{info['app_version']}" if info.get("app_version") else ""
            self.app_line.setText(f"已检测到《BanG Dream! Our Notes》{server_name}{v}（{info['bundle']}）")
            self.app_line_icon.setPixmap(T.pixmap("check", T.GREEN, 14))
        else:
            self.app_line.setText(f"这台 iPhone 上没有找到{server_name}的游戏（{info['bundle']}）。玩的是另一个服？回到首页点“更改”。")
            self.app_line_icon.setPixmap(T.pixmap("alert", T.ORANGE, 14))
        self.enc.setVisible(bool(info.get("will_encrypt")))
        self.validate()
        if info["installed"] and not info.get("will_encrypt"):
            if not self.timer.isActive():
                self.start_countdown()
        else:
            self.stop_countdown()

    def set_device_error(self, code, msg, detail=None):
        self.stop_countdown()
        self.dev.hide()
        self.enc.hide()
        self.info = None
        self.btn_start.setEnabled(False)
        self.show_error(code, msg, detail)
        self.left.insertWidget(0, self.error)

    def validate(self):
        i = self.info
        ok = bool(i and i["installed"] and (not i.get("will_encrypt") or self.pw.text()))
        self.btn_start.setEnabled(ok)

    def password(self):
        return self.pw.text() if self.info and self.info.get("will_encrypt") else None


# ---- Windows：缺少 Apple 设备支持时的引导页 ---------------------------------------------------
class AppleSupportPage(Page):
    def __init__(self):
        super().__init__("还差一步：安装 Apple 设备支持",
                         "Windows 需要 Apple 官方的 USB 驱动才能和 iPhone 通信。只需安装一次，免费。")
        c = Card("card", (24, 20, 24, 20), 14)
        self.head = label("", "h2")
        c.lay.addWidget(hbox(IconBadge("plug", T.ORANGE, "#FFF3DF", 44, 22, 12), self.head, None, spacing=12))
        self.steps = []
        for i, t in enumerate(["点下面的“打开 Microsoft Store”", "在商店里安装「Apple Devices」（Apple 官方出品，免费）",
                               "安装完成后，用数据线连接 iPhone，回到这里点“我装好了”"]):
            n = label(str(i + 1))
            n.setAlignment(Qt.AlignCenter)
            n.setFixedSize(22, 22)
            n.setStyleSheet(f"background: {T.PURPLE_SOFT}; color: {T.PURPLE_DARK}; border-radius: 11px; font-weight: 600;")
            t_l = label(t, "value", wrap=True)
            self.steps.append(t_l)
            row = hbox(n, t_l, spacing=10)
            row.layout().setStretch(1, 1)
            c.lay.addWidget(row)
        b1 = button("打开 Microsoft Store", "primary", "external")
        b1.clicked.connect(lambda: self.action.emit("open_store"))
        b2 = button("我装好了，重新检测", None, "refresh")
        b2.clicked.connect(lambda: self.action.emit("recheck_apple"))
        c.lay.addWidget(hbox(b1, b2, None, spacing=10, margins=(0, 6, 0, 0)))
        c.lay.addWidget(label("已经装了 iTunes 也可以。装完后如果仍提示，请重启电脑或打开一次 Apple Devices。", "muted", wrap=True))
        self.body.addWidget(c)
        self.body.addStretch(1)
        back = button("上一步")
        back.clicked.connect(lambda: self.action.emit("back"))
        self.footer.addWidget(back)
        self.footer.addStretch(1)
        b = button("跳过，从文件夹导入", "link", "folder")
        b.clicked.connect(lambda: self.action.emit("folder"))
        self.footer.addWidget(b)
        self.set_state("missing")

    def set_state(self, state):
        if state == "stopped":
            self.head.setText("已安装 Apple 设备支持，但它没有在运行")
            self.steps[0].setText("打开一次「Apple Devices」应用（或 iTunes），或重启电脑")
            self.steps[1].setText("如果还是不行，在 Microsoft Store 里更新「Apple Devices」")
        else:
            self.head.setText("没有找到 Apple 设备支持")
            self.steps[0].setText("点下面的“打开 Microsoft Store”")
            self.steps[1].setText("在商店里安装「Apple Devices」（Apple 官方出品，免费）")


# ---- 03 提取中 ---------------------------------------------------------------------------
class ExtractPage(Page):
    def __init__(self):
        super().__init__("正在提取存档", "手机会把整机备份数据传过来，本软件只留下游戏存档，其余数据边收边丢，不占电脑空间。")
        top = Card("card", (22, 18, 22, 18), 16, horizontal=True)
        self.pct = label("0%", "huge")
        self.pct.setMinimumWidth(96)
        top.lay.addWidget(self.pct)
        self.state = label("正在连接 iPhone…", "value")
        self.eta = label("", "muted")
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        top.lay.addWidget(vbox(hbox(self.state, None, self.eta), self.bar, spacing=10), 1)
        self.body.addWidget(top)
        tiles = QHBoxLayout()
        tiles.setSpacing(12)
        self.t_recv = StatTile("download", "已接收", "0 B")
        self.t_kept = StatTile("json", "已保留游戏文件", "0 个")
        self.t_speed = StatTile("refresh", "速度", "—")
        self.t_time = StatTile("clock", "已用时间", "00:00")
        for t in (self.t_recv, self.t_kept, self.t_speed, self.t_time):
            tiles.addWidget(t)
        self.body.addLayout(tiles)
        ban = Card("purple", (18, 14, 18, 14), 14, horizontal=True)
        ban.lay.addWidget(IconBadge("shield", "#FFFFFF", T.PURPLE, 42, 22, 12))
        self.kept_title = label("仅保存游戏数据", "h2")
        self.kept_title.setStyleSheet(f"color: {T.PURPLE_DARK};")
        ban.lay.addWidget(vbox(self.kept_title, label("不会在电脑上生成完整备份。手机数据越多需要的时间越长，可以去做别的事，完成后会自动进入下一步。",
                                                      "small", wrap=True), spacing=2), 1)
        self.body.addWidget(ban)
        self.retry = Card("orange", (18, 12, 18, 12), 12, horizontal=True)
        self.retry.lay.addWidget(icon_label("refresh", T.ORANGE, 18))
        self.retry_t = label("", "value")
        self.retry.lay.addWidget(vbox(self.retry_t, label("请检查数据线，保持手机亮屏解锁。已收到的游戏文件不会丢。", "small"),
                                      spacing=2), 1)
        self.retry.hide()
        self.body.addWidget(self.retry)
        self.body.addStretch(1)
        self.footer.addWidget(hbox(icon_label("info", T.MUTED, 13), label("请不要拔线；手机最好设成“永不自动锁定”", "muted"), spacing=6))
        self.footer.addStretch(1)
        self.btn_cancel = button("取消提取", None, "x")
        self.btn_cancel.clicked.connect(lambda: self.action.emit("cancel"))
        self.footer.addWidget(self.btn_cancel)
        self._last = (0.0, 0)
        self._speed = 0.0

    def reset(self):
        self.clear_error()
        self.retry.hide()
        self.bar.setValue(0)
        self.pct.setText("0%")
        self.state.setText("正在连接 iPhone…")
        self.eta.setText("")
        self.btn_cancel.setEnabled(True)
        self._last = (time.time(), 0)
        self._speed = 0.0
        self.update_stats(0, 0, 0, 0, 0, "connecting")

    def update_stats(self, percent, received, kept, kept_bytes, elapsed, phase):
        now = time.time()
        t0, r0 = self._last
        if now - t0 >= 1.0:
            inst = (received - r0) / (now - t0)
            self._speed = inst if not self._speed else 0.7 * self._speed + 0.3 * inst
            self._last = (now, received)
        p = max(0.0, min(100.0, percent))
        self.pct.setText(f"{p:.0f}%")
        self.bar.setValue(int(p * 10))
        self.state.setText({"connecting": "正在连接 iPhone…",
                            "waiting_device": "等待手机响应…如果手机要求输入密码，请输入锁屏密码",
                            "transferring": "正在接收备份数据…", "finishing": "正在收尾…",
                            "scanning": "正在解密并查找存档…"}.get(phase, phase))
        if 3 < p < 100 and elapsed > 20:
            rest = elapsed * (100 - p) / p
            self.eta.setText(f"预计剩余约 {max(1, round(rest / 60))} 分钟")
        self.t_recv.set(human_bytes(received))
        self.t_kept.set(f"{kept} 个")
        self.t_speed.set(f"{human_bytes(self._speed)}/s" if self._speed > 0 else "—")
        self.t_time.set(mmss(elapsed))
        if kept_bytes:
            self.kept_title.setText(f"仅保存游戏数据，占用约 {human_bytes(kept_bytes)}")

    def set_retrying(self, n, mx):
        self.retry_t.setText(f"连接中断，正在自动重试（第 {n}/{mx} 次）…")
        self.retry.show()

    def set_scanning(self):
        self.retry.hide()
        self.state.setText("正在解密并查找存档…（大存档约需 10–30 秒）")
        self.btn_cancel.setEnabled(False)


# ---- 04 存档确认 -------------------------------------------------------------------------
class ConfirmPage(Page):
    account_changed = Signal(int)

    def __init__(self):
        super().__init__("找到存档", "这是你的游戏账号吗？确认无误后点“上传到 bdon.moe”。")
        c = Card("card", (20, 18, 20, 18), 14)
        self.avatar = Avatar("M", 56)
        self.name = label("", "h2")
        self.c_server = chip("国际服", "blue")
        self.c_src = chip("✓ 解密成功", "green")
        self.pick = QComboBox()
        self.pick.currentIndexChanged.connect(self.account_changed)
        self.pick.hide()
        c.lay.addWidget(hbox(self.avatar, vbox(self.name, hbox(self.c_server, self.c_src, None, spacing=6), spacing=4), None,
                             self.pick, spacing=14))
        c.lay.addWidget(divider())
        g = QGridLayout()
        g.setHorizontalSpacing(20)
        g.setVerticalSpacing(4)
        self.f = {}
        for i, (k, t) in enumerate([("name", "玩家名"), ("id", "玩家 ID"), ("server", "服务器"), ("time", "存档时间")]):
            g.addWidget(label(t, "muted"), 0, i)
            self.f[k] = label("", "value", sel=True)
            g.addWidget(self.f[k], 1, i)
        c.lay.addLayout(g)
        self.body.addWidget(c)
        tiles = QHBoxLayout()
        tiles.setSpacing(12)
        self.tiles = {"member_cards": StatTile("cards", "成员卡"), "support_cards": StatTile("layers", "支援卡"),
                      "characters": StatTile("users", "角色"), "decks": StatTile("star", "编队")}
        for t in self.tiles.values():
            tiles.addWidget(t)
        self.body.addLayout(tiles)
        self.meta = label("", "muted", wrap=True, sel=True)
        self.body.addWidget(self.meta)
        info = Card("blue", (14, 10, 14, 10), 8, horizontal=True)
        info.lay.addWidget(icon_label("info", T.BLUEINFO, 14))
        info.lay.addWidget(label("导出的 JSON 仅保存在本机，可用于备份或手动导入。上传前不会离开你的电脑。", "small", wrap=True), 1)
        self.body.addWidget(info)
        self.body.addStretch(1)
        b = button("导出 JSON", None, "json")
        b.clicked.connect(lambda: self.action.emit("export"))
        self.footer.addWidget(b)
        b = button("重新提取", "link", "refresh")
        b.clicked.connect(lambda: self.action.emit("retry"))
        self.footer.addWidget(b)
        self.footer.addStretch(1)
        self.btn_next = button("登录并上传", "primary", "upload")
        self.btn_next.clicked.connect(lambda: self.action.emit("next"))
        self.footer.addWidget(self.btn_next)

    def set_logged_in(self, yes):
        self.btn_next.setText("上传到 bdon.moe" if yes else "登录并上传")

    def set_saves(self, saves):
        self.pick.blockSignals(True)
        self.pick.clear()
        for s in saves:
            self.pick.addItem(f"{s['name'] or '?'}（{core.SERVER_NAMES.get(s['server'], s['server'])} {s['account_id']}）")
        self.pick.setVisible(len(saves) > 1)
        self.pick.blockSignals(False)

    def set_stats(self, st, source):
        self.avatar.set_text(st["name"])
        self.name.setText(st["name"] or "（未命名）")
        srv = core.SERVER_NAMES.get(st["server"], st["server"])
        self.c_server.setText(srv)
        self.f["name"].setText(st["name"] or "—")
        self.f["id"].setText(core.format_id(st["profile_id"]))
        self.f["server"].setText(srv)
        self.f["time"].setText(core.format_time(st["mtime"]))
        for k, t in self.tiles.items():
            t.set(st[k])
        self.meta.setText(f"来源：{source} · _player 大小 {human_bytes(st['size'])} · 密钥 {st['key_fp']}")


# ---- 05 登录 -----------------------------------------------------------------------------
class LoginPage(Page):
    def __init__(self):
        super().__init__("登录 StarMoe Passport", "将在系统浏览器中打开登录页，授权完成后会通过 moe.starmoe.box:// 自动返回本软件。")
        self.card = Card("card", (24, 24, 24, 24), 0)
        self.stack = QStackedWidget()
        self.card.lay.addWidget(self.stack)
        self.body.addWidget(self.card, 1)

        # a 未登录
        a = QWidget()
        la = QVBoxLayout(a)
        la.setSpacing(12)
        la.addStretch(1)
        la.addWidget(hbox(None, IconBadge("user", T.PURPLE, T.PURPLE_SOFT, 64, 30, circle=True), None))
        t = label("尚未登录", "h2"); t.setAlignment(Qt.AlignCenter); la.addWidget(t)
        s = label("用 StarMoe 通行证账号登录（没有账号可以在登录页注册），授权后就能上传存档", "small"); s.setAlignment(Qt.AlignCenter)
        la.addWidget(s)
        b = button("在浏览器中登录", "primary", "external")
        b.setMinimumWidth(160)
        b.clicked.connect(lambda: self.action.emit("login"))
        la.addWidget(hbox(None, b, None))
        la.addWidget(hbox(None, icon_label("shield", T.MUTED, 12), label("密码只在浏览器中输入，本软件不会接触你的密码", "muted"),
                          None, spacing=4))
        la.addStretch(1)
        self.stack.addWidget(a)

        # b 等待浏览器
        bw = QWidget()
        lb = QVBoxLayout(bw)
        lb.setSpacing(12)
        lb.addStretch(1)
        lb.addWidget(hbox(None, Spinner(64), None))
        t = label("正在等待浏览器完成登录…", "h2"); t.setAlignment(Qt.AlignCenter); lb.addWidget(t)
        s = label("请在刚打开的浏览器里登录并点“授权”，完成后会自动回到这里并开始上传。", "small"); s.setAlignment(Qt.AlignCenter)
        lb.addWidget(s)
        r = button("重新打开浏览器", None, "external")
        r.clicked.connect(lambda: self.action.emit("reopen"))
        c = button("取消")
        c.clicked.connect(lambda: self.action.emit("cancel_login"))
        lb.addWidget(hbox(None, r, c, None, spacing=10))
        self.wait_l = label("", "muted"); self.wait_l.setAlignment(Qt.AlignCenter)
        lb.addWidget(self.wait_l)
        self.paste_toggle = button("浏览器没有跳回来？手动粘贴回调地址", "link")
        self.paste_toggle.clicked.connect(lambda: self.paste_row.setVisible(not self.paste_row.isVisible()))
        lb.addWidget(hbox(None, self.paste_toggle, None))
        self.paste = QLineEdit()
        self.paste.setPlaceholderText("moe.starmoe.box://moe.starmoe.box/callback?code=…&state=…")
        ok = button("提交", "soft")
        ok.clicked.connect(lambda: self.action.emit("paste"))
        self.paste.returnPressed.connect(lambda: self.action.emit("paste"))
        self.paste_row = hbox(40, self.paste, ok, 40, spacing=8)
        self.paste_row.hide()
        lb.addWidget(self.paste_row)
        lb.addStretch(1)
        self.stack.addWidget(bw)

        # c 已登录
        cw = QWidget()
        lc = QVBoxLayout(cw)
        lc.setSpacing(12)
        lc.addStretch(1)
        self.avatar = Avatar("M", 64)
        lc.addWidget(hbox(None, self.avatar, None))
        lc.addWidget(hbox(None, label("已登录", "h2"), chip("✓ 授权成功", "green"), None, spacing=8))
        self.user = label("", "value")
        lc.addWidget(hbox(None, icon_label("user", T.TEXT2, 14), self.user, chip("StarMoe Passport", "purple"), None, spacing=6))
        self.tok_info = label("", "muted"); self.tok_info.setAlignment(Qt.AlignCenter)
        lc.addWidget(self.tok_info)
        sw = button("切换账号")
        sw.clicked.connect(lambda: self.action.emit("switch"))
        lo = button("退出登录", "link")
        lo.clicked.connect(lambda: self.action.emit("logout"))
        lc.addWidget(hbox(None, sw, lo, None, spacing=8))
        lc.addStretch(1)
        self.stack.addWidget(cw)

        back = button("上一步")
        back.clicked.connect(lambda: self.action.emit("back"))
        self.footer.addWidget(back)
        self.footer.addStretch(1)
        self.btn_upload = button("上传到 bdon.moe", "primary", "upload")
        self.btn_upload.clicked.connect(lambda: self.action.emit("upload"))
        self.footer.addWidget(self.btn_upload)
        self._t0 = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self.set_state("a")

    def _tick(self):
        self.wait_l.setText(f"等待回调 moe.starmoe.box://…/callback · 已等待 {mmss(time.time() - self._t0)}")

    def set_state(self, s, user=None, info="", can_upload=False, uploading=False):
        self.clear_error()
        self.stack.setCurrentIndex("abc".index(s))
        self.subtitle.setText("已通过浏览器完成授权，可以上传存档了。" if s == "c" else
                              "将在系统浏览器中打开登录页，授权完成后会通过 moe.starmoe.box:// 自动返回本软件。")
        if s == "b":
            self._t0 = time.time()
            self._tick()
            self._timer.start(1000)
            self.paste.clear()
        else:
            self._timer.stop()
        if s == "c":
            self.avatar.set_text(user or "?")
            self.user.setText(user or "")
            self.tok_info.setText(info)
        self.btn_upload.setEnabled(s == "c" and can_upload and not uploading)
        self.btn_upload.setText("正在上传…" if uploading else "上传到 bdon.moe")

    def show_error(self, code, message=None, detail=None, index=0):
        super().show_error(code, message, detail, index)
        self.card.hide()

    def clear_error(self):
        super().clear_error()
        self.card.show()


# ---- 06 上传完成 -------------------------------------------------------------------------
class DonePage(Page):
    def __init__(self):
        super().__init__("上传完成", "存档已成功上传到 Moenotes（bdon.moe）。")
        c = Card("card", (24, 24, 24, 24), 12)
        c.lay.addStretch(1)
        c.lay.addWidget(hbox(None, IconBadge("check", T.GREEN, T.GREEN_BG, 72, 34, circle=True), None))
        t = label("上传成功！", "h2"); t.setAlignment(Qt.AlignCenter); c.lay.addWidget(t)
        s = label("前往 bdon.moe 即可导入并查看你的成员卡、支援卡与编队数据。", "small"); s.setAlignment(Qt.AlignCenter)
        c.lay.addWidget(s)
        grid = Card("grey", (18, 12, 18, 12), 0, horizontal=True)
        self.f = {}
        for k, title in [("size", "文件大小"), ("time", "上传时间"), ("account", "账号"), ("server", "服务器")]:
            self.f[k] = label("", "value")
            grid.lay.addWidget(vbox(label(title, "muted"), self.f[k], spacing=2), 1)
        c.lay.addWidget(hbox(30, grid, 30))
        self.changed = label("", "muted"); self.changed.setAlignment(Qt.AlignCenter)
        c.lay.addWidget(self.changed)
        b = button("去 bdon.moe 导入", "primary", "external")
        b.setMinimumWidth(180)
        b.clicked.connect(lambda: self.action.emit("open_deck"))
        c.lay.addWidget(hbox(None, b, None))
        c.lay.addStretch(1)
        self.body.addWidget(c, 1)
        b = button("导出 JSON 备份", None, "json")
        b.clicked.connect(lambda: self.action.emit("export"))
        self.footer.addWidget(b)
        self.footer.addStretch(1)
        b = button("再提取一次", None, "refresh")
        b.clicked.connect(lambda: self.action.emit("again"))
        self.footer.addWidget(b)
        b = button("完成", "soft")
        b.clicked.connect(lambda: self.action.emit("finish"))
        self.footer.addWidget(b)

    def set_result(self, size, when, account, server, changed):
        self.f["size"].setText(human_bytes(size))
        self.f["time"].setText(core.format_time(when))
        self.f["account"].setText(account)
        self.f["server"].setText(core.SERVER_NAMES.get(server, server))
        self.changed.setText("" if changed is None else ("服务器上的存档已更新" if changed else "服务器上已是相同的存档（无变化）"))
