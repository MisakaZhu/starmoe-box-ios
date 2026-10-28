"""08 设置与关于。"""
import os, sys
from PySide6.QtCore import Qt, Signal, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog, QVBoxLayout, QTextBrowser, QDialogButtonBox
from . import theme as T, paths, SOURCE_URL, VERSION
from .widgets import label, chip, button, Card, divider, hbox, vbox, IconBadge, Logo, SegmentedControl
from .. import core


def resource_path(*p):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    return os.path.join(base, *p)


class SettingsDialog(QDialog):
    action = Signal(str)
    server_changed = Signal(str)

    def __init__(self, parent, key_text, server_text, server="intl"):
        super().__init__(parent)
        self.setWindowTitle("设置与关于")
        self.setFixedWidth(600)
        l = QVBoxLayout(self)
        l.setContentsMargins(24, 22, 24, 20)
        l.setSpacing(14)
        l.addWidget(hbox(Logo(52), vbox(label("StarMoe Box（iOS 版）", "h2"),
                                         label(f"版本 v{VERSION} · macOS / Windows · Python + PySide6", "small"), spacing=2),
                         None, chip("开源", "green"), spacing=14))
        c = Card("card", (18, 6, 18, 6), 0)
        rows = [("code", "开源许可", "Apache License 2.0", [("查看", "license", "link")]),
                ("github", "源代码", SOURCE_URL.replace("https://", "") + ("（占位链接）" if "<" in SOURCE_URL else ""),
                 [("打开", "source", "link")]),
                ("key", "密钥来源", key_text, [("自动获取", "auto_keys", None), ("选择 APK", "reload_keys", "link"),
                                         ("密钥文件", "keys_file", "link")]),
                ("folder", "日志目录", paths.log_dir(), [("打开目录", "logs", None)]),
                ("globe", "默认服务器", server_text, [("更改", "region", "link")])]
        for i, (ic, title, sub, btns) in enumerate(rows):
            if i:
                c.lay.addWidget(divider())
            bs = []
            seg = None
            if title == "默认服务器":
                seg = SegmentedControl([("intl", "国际服"), ("jp", "日服")], server)
                bs.append(seg)
                btns = []
            for text, act, kind in btns:
                b = button(text, kind, "external" if act == "source" else None)
                b.clicked.connect(lambda _=False, a=act: self._do(a))
                bs.append(b)
            s = label(sub, "small", wrap=True, sel=True)
            if seg is not None:
                def on_server(key, lab=s):
                    lab.setText(f"{core.SERVER_NAMES.get(key, key)}（{core.BUNDLE_OF.get(key, '')}）")
                    self.server_changed.emit(key)
                seg.changed.connect(on_server)
                self._server_seg = seg
            c.lay.addWidget(hbox(IconBadge(ic, T.PURPLE, T.PURPLE_SOFT, 34, 17, 10),
                                 vbox(label(title, "value"), s, spacing=2), *bs, spacing=12, margins=(0, 12, 0, 12)))
            hbox_w = c.lay.itemAt(c.lay.count() - 1).widget()
            hbox_w.layout().setStretch(1, 1)
        l.addWidget(c)
        l.addWidget(label("非官方工具，与 Bushiroad、bilibili 及 StarMoe 官方无关。存档仅在本机处理，只有在你登录并确认后才会上传到 bdon.moe。",
                          "muted", wrap=True))

    def _do(self, a):
        if a == "license":
            d = QDialog(self)
            d.setWindowTitle("Apache License 2.0")
            d.resize(620, 520)
            v = QVBoxLayout(d)
            t = QTextBrowser()
            try:
                t.setPlainText(open(resource_path("LICENSE"), encoding="utf-8").read())
            except OSError:
                t.setPlainText("Apache License 2.0 — https://www.apache.org/licenses/LICENSE-2.0")
            v.addWidget(t)
            bb = QDialogButtonBox(QDialogButtonBox.Close)
            bb.rejected.connect(d.reject)
            v.addWidget(bb)
            d.exec()
        elif a == "source":
            QDesktopServices.openUrl(QUrl(SOURCE_URL))
        elif a == "logs":
            QDesktopServices.openUrl(QUrl.fromLocalFile(paths.log_dir()))
        else:
            self.accept()
            self.action.emit(a)
