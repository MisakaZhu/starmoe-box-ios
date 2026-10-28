"""设计稿 token（Figma rTDh0PfNKtHYPE90unfYzy）：浅色主题，主色淡紫 #8B7CF6 → 蓝 #5B9BF8 渐变。

图标为 Lucide（ISC 许可）路径的内嵌 SVG，按需着色。
"""
import sys
from PySide6.QtCore import Qt, QByteArray, QRectF
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor
from PySide6.QtSvg import QSvgRenderer

PURPLE = "#8B7CF6"
BLUE = "#5B9BF8"
PURPLE_DARK = "#6E5CE6"
PURPLE_SOFT = "#F1EEFF"
TEXT = "#1F1D2E"
TEXT2 = "#5E5B70"
MUTED = "#9A97AA"
BORDER = "#ECEAF3"
BG = "#F6F5FB"
SIDEBAR = "#FBFAFE"
GREEN, GREEN_BG = "#1FA463", "#E4F6EC"
ORANGE, ORANGE_BG, ORANGE_BORDER = "#E58A0C", "#FFF6E6", "#F8DFAE"
RED, RED_BG = "#E5484D", "#FDECEC"
BLUEINFO, BLUE_BG = "#3E7BE6", "#EAF2FE"

if sys.platform == "darwin":
    FONTS = '"PingFang SC", "Helvetica Neue", sans-serif'
elif sys.platform == "win32":
    FONTS = '"Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", sans-serif'
else:
    FONTS = '"Noto Sans CJK SC", "Noto Sans SC", "WenQuanYi Micro Hei", sans-serif'

GRAD = f"qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {PURPLE}, stop:1 {BLUE})"
GRAD_OFF = "qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #CFC7FB, stop:1 #BCD5FC)"

QSS = f"""
* {{ font-family: {FONTS}; font-size: 13px; color: {TEXT}; }}
QMainWindow, QDialog, QWidget#root {{ background: {BG}; }}
QWidget#sidebar {{ background: {SIDEBAR}; border-right: 1px solid {BORDER}; }}
QWidget#page, QStackedWidget, QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; }}
QFrame[card="true"] {{ background: #FFFFFF; border: 1px solid {BORDER}; border-radius: 16px; }}
QFrame[tile="true"] {{ background: #FFFFFF; border: 1px solid {BORDER}; border-radius: 14px; }}
QFrame[banner="purple"] {{ background: {PURPLE_SOFT}; border: 1px solid #E2DCFF; border-radius: 14px; }}
QFrame[banner="orange"] {{ background: {ORANGE_BG}; border: 1px solid {ORANGE_BORDER}; border-radius: 14px; }}
QFrame[banner="blue"] {{ background: {BLUE_BG}; border: none; border-radius: 12px; }}
QFrame[banner="grey"] {{ background: #F6F5FA; border: none; border-radius: 12px; }}
QFrame[option="true"] {{ background: #FFFFFF; border: 1px solid #E6E3EF; border-radius: 12px; }}
QFrame[option="true"][selected="true"] {{ background: #F3F0FF; border: 1.5px solid {PURPLE}; }}
QFrame#divider {{ background: {BORDER}; border: none; max-height: 1px; min-height: 1px; }}
QLabel {{ background: transparent; }}
QLabel[role="h1"] {{ font-size: 22px; font-weight: 700; }}
QLabel[role="h2"] {{ font-size: 18px; font-weight: 700; }}
QLabel[role="sub"] {{ color: {TEXT2}; }}
QLabel[role="muted"] {{ color: {MUTED}; font-size: 12px; }}
QLabel[role="small"] {{ color: {TEXT2}; font-size: 12px; }}
QLabel[role="cardtitle"] {{ font-size: 14px; font-weight: 600; }}
QLabel[role="big"] {{ font-size: 26px; font-weight: 700; }}
QLabel[role="stat"] {{ font-size: 20px; font-weight: 700; }}
QLabel[role="huge"] {{ font-size: 34px; font-weight: 700; color: {PURPLE_DARK}; }}
QLabel[role="value"] {{ font-size: 14px; font-weight: 600; }}
QLabel[chip="green"] {{ background: {GREEN_BG}; color: {GREEN}; border-radius: 10px; padding: 2px 9px; font-size: 12px; }}
QLabel[chip="blue"] {{ background: {BLUE_BG}; color: {BLUEINFO}; border-radius: 10px; padding: 2px 9px; font-size: 12px; }}
QLabel[chip="purple"] {{ background: {PURPLE_SOFT}; color: {PURPLE_DARK}; border-radius: 10px; padding: 2px 9px; font-size: 12px; }}
QLabel[chip="orange"] {{ background: #FFF1D9; color: {ORANGE}; border-radius: 10px; padding: 2px 9px; font-size: 12px; }}
QLabel[chip="white"] {{ background: #FFFFFF; color: {PURPLE_DARK}; border: 1px solid #E2DCFF; border-radius: 10px; padding: 2px 9px; font-size: 12px; }}
QPushButton {{ background: #FFFFFF; border: 1px solid #E3E0EE; border-radius: 10px; padding: 9px 16px;
              font-weight: 600; color: {TEXT}; }}
QPushButton:hover {{ background: #F8F6FF; border-color: #D6D0F5; }}
QPushButton:pressed {{ background: #EFEBFF; }}
QPushButton:disabled {{ color: #B9B6C6; }}
QPushButton#primary {{ background: {GRAD}; color: #FFFFFF; border: none; padding: 10px 18px; }}
QPushButton#primary:hover {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #7F6EF3, stop:1 #4E90F5); }}
QPushButton#primary:disabled {{ background: {GRAD_OFF}; color: #FFFFFF; }}
QPushButton#soft {{ background: {PURPLE_SOFT}; color: {PURPLE_DARK}; border: none; }}
QPushButton#link {{ background: transparent; border: none; color: {PURPLE_DARK}; padding: 4px 6px; font-weight: 500; }}
QPushButton#link:hover {{ text-decoration: underline; }}
QPushButton#side {{ background: transparent; border: none; text-align: left; padding: 6px 8px; font-weight: 500; }}
QPushButton#side:hover {{ background: #F1EFF8; }}
QLineEdit {{ background: #FFFFFF; border: 1px solid #E3E0EE; border-radius: 10px; padding: 9px 12px; }}
QLineEdit:focus {{ border: 1.5px solid {PURPLE}; }}
QComboBox {{ background: #FFFFFF; border: 1px solid #E3E0EE; border-radius: 8px; padding: 5px 10px; }}
QProgressBar {{ background: #ECEAF6; border: none; border-radius: 4px; max-height: 8px; min-height: 8px; }}
QProgressBar::chunk {{ border-radius: 4px; background: {GRAD}; }}
QToolTip {{ background: #FFFFFF; color: {TEXT}; border: 1px solid {BORDER}; padding: 4px; }}
QTextBrowser {{ background: #FFFFFF; border: 1px solid {BORDER}; border-radius: 10px; padding: 8px; }}
"""

_P = {
    "check": '<path d="M20 6 9 17l-5-5"/>',
    "x": '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
    "globe": '<circle cx="12" cy="12" r="10"/><path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20"/><path d="M2 12h20"/>',
    "sliders": '<line x1="4" x2="4" y1="21" y2="14"/><line x1="4" x2="4" y1="10" y2="3"/><line x1="12" x2="12" y1="21" y2="12"/>'
               '<line x1="12" x2="12" y1="8" y2="3"/><line x1="20" x2="20" y1="21" y2="16"/><line x1="20" x2="20" y1="12" y2="3"/>'
               '<line x1="2" x2="6" y1="14" y2="14"/><line x1="10" x2="14" y1="8" y2="8"/><line x1="18" x2="22" y1="16" y2="16"/>',
    "key": '<circle cx="7.5" cy="15.5" r="5.5"/><path d="m21 2-9.6 9.6"/><path d="m15.5 7.5 3 3L22 7l-3-3"/>',
    "download": '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" x2="12" y1="15" y2="3"/>',
    "upload": '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" x2="12" y1="3" y2="15"/>',
    "lock": '<rect width="18" height="11" x="3" y="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
    "plug": '<path d="M12 22v-5"/><path d="M9 8V2"/><path d="M15 8V2"/><path d="M18 8v5a4 4 0 0 1-4 4h-4a4 4 0 0 1-4-4V8Z"/>',
    "phone": '<rect width="14" height="20" x="5" y="2" rx="2" ry="2"/><path d="M12 18h.01"/>',
    "shield": '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 '
              '6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/><path d="m9 12 2 2 4-4"/>',
    "refresh": '<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/>'
               '<path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/>',
    "eye": '<path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/>',
    "info": '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
    "json": '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/>'
            '<path d="M10 12a1 1 0 0 0-1 1v1a1 1 0 0 1-1 1 1 1 0 0 1 1 1v1a1 1 0 0 0 1 1"/>'
            '<path d="M14 18a1 1 0 0 0 1-1v-1a1 1 0 0 1 1-1 1 1 0 0 1-1-1v-1a1 1 0 0 0-1-1"/>',
    "code": '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/>'
            '<path d="m10 13-2 2 2 2"/><path d="m14 17 2-2-2-2"/>',
    "layers": '<path d="m12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83Z"/>'
              '<path d="m22 17.65-9.17 4.16a2 2 0 0 1-1.66 0L2 17.65"/><path d="m22 12.65-9.17 4.16a2 2 0 0 1-1.66 0L2 12.65"/>',
    "users": '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/>'
             '<path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
    "star": '<polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>',
    "cards": '<rect width="18" height="18" x="3" y="3" rx="2"/><path d="M3 9h18"/><path d="M9 21V9"/>',
    "user": '<path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
    "external": '<path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>',
    "spinner": '<path d="M21 12a9 9 0 1 1-6.219-8.56"/>',
    "clock": '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
    "alert": '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
    "xcircle": '<circle cx="12" cy="12" r="10"/><path d="m15 9-6 6"/><path d="m9 9 6 6"/>',
    "folder": '<path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/>',
    "github": '<path d="M15 22v-4a4.8 4.8 0 0 0-1-3.5c3 0 6-2 6-5.5.08-1.25-.27-2.48-1-3.5.28-1.15.28-2.35 0-3.5 0 0-1 0-3 1.5-2.64-.5-5.36-.5-8 0'
              'C6 2 5 2 5 2c-.3 1.15-.3 2.35 0 3.5A5.403 5.403 0 0 0 4 9c0 3.5 3 5.5 6 5.5-.39.49-.68 1.05-.85 1.65-.17.6-.22 1.23-.15 1.85v4"/>'
              '<path d="M9 18c-4.51 2-5-2-7-2"/>',
    "logout": '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" x2="9" y1="12" y2="12"/>',
}


def pixmap(name, color=PURPLE, size=16, rotate=0.0):
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" '
           f'stroke-linecap="round" stroke-linejoin="round">{_P[name]}</svg>')
    from PySide6.QtGui import QGuiApplication
    dpr = QGuiApplication.instance().devicePixelRatio() if QGuiApplication.instance() else 1.0
    pm = QPixmap(int(size * dpr), int(size * dpr))
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    if rotate:
        p.translate(pm.width() / 2, pm.height() / 2)
        p.rotate(rotate)
        p.translate(-pm.width() / 2, -pm.height() / 2)
    QSvgRenderer(QByteArray(svg.encode())).render(p, QRectF(0, 0, pm.width(), pm.height()))
    p.end()
    pm.setDevicePixelRatio(dpr)
    return pm


def icon(name, color=PURPLE, size=16):
    return QIcon(pixmap(name, color, size))
