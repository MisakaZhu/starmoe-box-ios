"""生成应用图标（用界面里同一个 Logo 绘制）：python packaging/make_icons.py
输出 packaging/icons/{app.png, app.ico, app.icns, dmg_background.png, dmg_background@2x.png}。需要 PySide6 + Pillow。"""
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QPixmap, QRegion, QPainter, QColor, QFont, QPen, QLinearGradient, QPainterPath
from PySide6.QtWidgets import QApplication, QWidget
from PIL import Image
from starmoe_ios.gui.widgets import Logo

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons")
app = QApplication([])
os.makedirs(OUT, exist_ok=True)
w = Logo(824)   # macOS 图标留边：1024 画布里放 824 的圆角方块
pm = QPixmap(1024, 1024)
pm.fill(Qt.transparent)
w.render(pm, QPoint(100, 100), QRegion(), QWidget.RenderFlag.DrawChildren)
png = os.path.join(OUT, "app.png")
pm.save(png)
im = Image.open(png).convert("RGBA")
im.save(os.path.join(OUT, "app.ico"), sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
im.save(os.path.join(OUT, "app.icns"))


def dmg_background(scale):
    """DMG 窗口背景（660×400）：左边放 App，右边是“应用程序”，中间画一个箭头。"""
    W, H = 660, 400
    pm = QPixmap(W * scale, H * scale)
    pm.setDevicePixelRatio(1)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(scale, scale)
    g = QLinearGradient(0, 0, 0, H)
    g.setColorAt(0, QColor("#F7F6FD"))
    g.setColorAt(1, QColor("#ECEBFA"))
    p.fillRect(0, 0, W, H, g)
    p.setPen(QColor("#1F1B2E"))
    f = QFont()
    f.setPixelSize(22)
    f.setBold(True)
    p.setFont(f)
    p.drawText(0, 30, W, 40, Qt.AlignHCenter, "把 StarMoe Box 拖进“应用程序”")
    f.setPixelSize(13)
    f.setBold(False)
    p.setFont(f)
    p.setPen(QColor("#6B6880"))
    p.drawText(0, 300, W, 60, Qt.AlignHCenter,
               "然后在“应用程序”里双击打开\n首次打开若提示无法验证开发者：右键 → 打开")
    pen = QPen(QColor("#8B7CF6"), 5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    p.drawLine(275, 190, 380, 190)
    path = QPainterPath()
    path.moveTo(366, 176)
    path.lineTo(384, 190)
    path.lineTo(366, 204)
    p.drawPath(path)
    p.end()
    return pm


dmg_background(1).save(os.path.join(OUT, "dmg_background.png"))
dmg_background(2).save(os.path.join(OUT, "dmg_background@2x.png"))
print("icons ->", OUT)
