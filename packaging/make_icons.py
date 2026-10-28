"""生成应用图标：python packaging/make_icons.py
输出 packaging/icons/{app.png, app.icns, dmg_background.png, dmg_background@2x.png}。
macOS 图标按系统图标网格绘制（1024 画布、824 圆角方、约 100px 边距、超椭圆圆角、内边距里的浅阴影）。
Windows 的 app.ico 保持铺满画布，本脚本不覆盖它。DMG 背景需要 PySide6。"""
import io, os, struct, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PIL import Image, ImageDraw, ImageFilter, ImageFont

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons")
CANVAS = 1024
BODY = 824
MARGIN = (CANVAS - BODY) // 2   # 100
PURPLE = (0x8B, 0x7C, 0xF6)
BLUE = (0x5B, 0x9B, 0xF8)


def _squircle_mask(size=CANVAS, body=BODY, n=5.0, samples=3):
    """Apple 图标那种连续曲率：以 body 为外接正方形的超椭圆。n=5 时对角圆角约等于半径 185。"""
    mask = Image.new("L", (size, size), 0)
    px = mask.load()
    a = body / 2.0
    cx = cy = (size - 1) / 2.0
    pad = MARGIN - 2
    ss = samples * samples
    for y in range(pad, size - pad):
        for x in range(pad, size - pad):
            hit = 0
            for j in range(samples):
                for i in range(samples):
                    dx = abs(x + (i + 0.5) / samples - cx) / a
                    dy = abs(y + (j + 0.5) / samples - cy) / a
                    if dx ** n + dy ** n <= 1.0:
                        hit += 1
            if hit:
                px[x, y] = int(round(hit * 255 / ss))
    return mask


def _gradient(mask):
    img = Image.new("RGBA", (CANVAS, CANVAS))
    px = img.load()
    mp = mask.load()
    x0 = y0 = MARGIN
    for y in range(CANVAS):
        for x in range(CANVAS):
            a = mp[x, y]
            if not a:
                continue
            t = ((x - x0) + (y - y0)) / (2.0 * BODY)
            if t < 0:
                t = 0.0
            elif t > 1:
                t = 1.0
            px[x, y] = (
                int(PURPLE[0] + (BLUE[0] - PURPLE[0]) * t),
                int(PURPLE[1] + (BLUE[1] - PURPLE[1]) * t),
                int(PURPLE[2] + (BLUE[2] - PURPLE[2]) * t),
                a,
            )
    return img


def _letter():
    """与界面 Logo 相同：粗体 S，字号约为图标边长的一半，放在 824 方块中央。"""
    layer = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    font_path = next(p for p in (
        "/usr/share/fonts/truetype/macos/Inter-Bold.ttf",
        "/System/Library/Fonts/SFNS.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ) if os.path.isfile(p))
    font = ImageFont.truetype(font_path, int(BODY * 0.50))
    draw.text((CANVAS / 2, CANVAS / 2), "S", font=font, fill=(255, 255, 255, 255), anchor="mm")
    return layer


def macos_master():
    mask = _squircle_mask()
    # 只往下偏的浅阴影，落在 100px 边距里，避免四周一圈描边
    shadow_a = mask.point(lambda v: int(v * 0.45))
    shifted = Image.new("L", (CANVAS, CANVAS), 0)
    shifted.paste(shadow_a, (0, 16))
    shifted = shifted.filter(ImageFilter.GaussianBlur(14))
    shadow = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 255))
    shadow.putalpha(shifted)
    out = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    out.alpha_composite(shadow)
    out.alpha_composite(_gradient(mask))
    out.alpha_composite(_letter())
    return out


def save_icns(path, master):
    """iconutil 会写出的全部尺寸：16/32/64/128/256/512/1024，含 @2x 的 OSType。"""
    types = (
        (b"icp4", 16), (b"icp5", 32), (b"ic11", 32), (b"icp6", 64), (b"ic12", 64),
        (b"ic07", 128), (b"ic08", 256), (b"ic13", 256), (b"ic09", 512), (b"ic14", 512),
        (b"ic10", 1024),
    )
    chunks = []
    for ostype, size in types:
        buf = io.BytesIO()
        master.resize((size, size), Image.Resampling.LANCZOS).save(buf, format="PNG")
        data = buf.getvalue()
        chunks.append(ostype + struct.pack(">I", 8 + len(data)) + data)
    toc = b"".join(c[:8] for c in chunks)
    toc_chunk = b"TOC " + struct.pack(">I", 8 + len(toc)) + toc
    body = toc_chunk + b"".join(chunks)
    with open(path, "wb") as f:
        f.write(b"icns" + struct.pack(">I", 8 + len(body)) + body)


def write_mac_icons(out_dir=OUT):
    os.makedirs(out_dir, exist_ok=True)
    master = macos_master()
    master.save(os.path.join(out_dir, "app.png"))
    save_icns(os.path.join(out_dir, "app.icns"), master)
    return master


def dmg_background(scale):
    """DMG 窗口背景（660×400）：左边放 App，右边是“应用程序”，中间画一个箭头。"""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPixmap, QPainter, QColor, QFont, QPen, QLinearGradient, QPainterPath
    from PySide6.QtWidgets import QApplication
    if QApplication.instance() is None:
        QApplication([])
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


if __name__ == "__main__":
    write_mac_icons()
    if "--dmg" in sys.argv:
        dmg_background(1).save(os.path.join(OUT, "dmg_background.png"))
        dmg_background(2).save(os.path.join(OUT, "dmg_background@2x.png"))
    print("icons ->", OUT)
