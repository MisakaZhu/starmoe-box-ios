"""无界面渲染每个页面为 PNG（QT_QPA_PLATFORM=offscreen）。
用法：PYTHONPATH=. python tests/render_screenshots.py [--apk box.apk] [--folder sirius_files] [--out screenshots]
不会连接设备、不会登录、不会上传：设备/登录/上传状态均为模拟数据；存档确认页使用真实的文件夹导入 + 解密结果。"""
import argparse, base64, json, os, sys, tempfile, time
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("STARMOE_DATA_DIR", tempfile.mkdtemp(prefix="starmoe-shot-"))
from PySide6.QtCore import QSettings, QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QWidget, QGridLayout, QVBoxLayout
from starmoe_ios.gui import theme as T
from starmoe_ios.gui.app import MainWindow
from starmoe_ios.gui.auth import TokenStore
from starmoe_ios.gui.settings_dialog import SettingsDialog
from starmoe_ios.gui.widgets import ErrorCard, label
from starmoe_ios import core


def pump(ms=150):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def wait(cond, timeout=180):
    t = time.time()
    while not cond():
        if time.time() - t > timeout:
            raise TimeoutError
        pump(100)


def fake_jwt(claims):
    b = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
    return f"{b({'alg': 'none'})}.{b(claims)}.x"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apk", default=os.environ.get("STARMOE_APK", "app-release.apk"))
    ap.add_argument("--folder", default=os.environ.get("STARMOE_REAL_FOLDER", ""),
                    help="真实存档文件夹（可选；只用于生成 screenshots/private/ 下的私有截图）")
    ap.add_argument("--out", default="screenshots")
    ap.add_argument("--tag", default="v0.1.4", help="欢迎页显示的官方 APK 版本（仅显示用）")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    app = QApplication(sys.argv)
    app.setStyleSheet(T.QSS)
    settings = QSettings(os.path.join(os.environ["STARMOE_DATA_DIR"], "settings.ini"), QSettings.IniFormat)
    class FakeKeyring(dict):   # 不碰系统钥匙串
        def get_password(self, s, k): return self.get((s, k))
        def set_password(self, s, k, v): self[(s, k)] = v
        def delete_password(self, s, k): self.pop((s, k), None)
    store = TokenStore(backend=FakeKeyring())
    w = MainWindow(store=store, settings=settings, first_run=False)
    w.poll_device = lambda force=False: None   # 截图时不访问 usbmuxd
    w.show()
    shots = []

    def shot(name, widget=None):
        pump()
        p = os.path.join(a.out, name + ".png")
        (widget or w).grab().save(p)
        shots.append(p)
        print("saved", p)

    shot("01b_welcome_first_run")
    box = w.consent_box()[0]
    box.show()
    shot("00_consent_dialog", box)
    box.close()
    w.p[w.W].set_fetching("正在下载官方安装包 v0.1.4…", 655_360, 1_393_316)
    shot("01c_welcome_fetching")
    w.p[w.W].set_keys(None, True)
    w.p[w.W].show_error("ERR_KEYS", "无法连接 GitHub 下载官方安装包。请检查网络（可稍后重试），或手动选择已下载好的官方 StarMoe Box APK。")
    shot("01d_welcome_fetch_failed")
    w.p[w.W].clear_error()
    if os.path.exists(a.apk):
        w.set_keys_from("auto", a.apk, tag=a.tag)
    shot("01_welcome")
    w.p[w.W].srv_opts.show()
    shot("01e_welcome_server")
    w.p[w.W].srv_opts.hide()

    w.go(w.D)
    dev = {"udid": "00008110-000000000000001E", "name": "我的 iPhone", "model": "iPhone 15 Pro", "ios": "18.6",
           "capacity": 1_000_000_000_000, "installed": True, "app_version": "1.4.0", "will_encrypt": True,
           "bundle": "com.bilibili.sirius"}
    w.p[w.D].set_device(dict(dev, will_encrypt=False), "国际服")
    shot("02_device_ready_countdown")
    w.p[w.D].stop_countdown()
    w.p[w.D].set_device(dev, "国际服")
    shot("02b_device_encrypted")
    w.p[w.D].set_device_error("ERR_NO_DEVICE", None)
    shot("02c_device_none")
    w.go(w.A)
    shot("02d_windows_apple_support")

    x = w.p[w.X]
    w.go(w.X)
    x.reset()
    now = time.time()
    base = 9_400_000_000
    x._rate.samples = [(now - 30, base)]
    x.update_stats(68, base + 41_000_000 * 30, 37, 12_400_000, 754, "transferring", now=now)
    shot("03_extracting")
    x.set_retrying(2, 5)
    shot("03b_extracting_retry")
    x.retry.hide()
    x.set_passcode(True)
    shot("03d_passcode")
    x.set_passcode(False)
    x.show_error("ERR_BACKUP_DENIED", None)
    shot("03c_extract_error")

    # 真实数据：文件夹导入 → 解密 → 存档确认（通过与界面相同的后台任务）
    if w.codec and os.path.isdir(a.folder):
        t0 = time.time()
        w.scan_in_background(a.folder, None, "文件夹导入")
        wait(lambda: w.stack.currentIndex() == w.C)
        st = w.stats
        os.makedirs(os.path.join(a.out, "private"), exist_ok=True)
        shot("private/04_confirm_real")   # 含真实玩家信息，已在 .gitignore 中排除
        print(f"REAL folder import: {time.time() - t0:.1f}s name={st['name']} id={st['profile_id']} member={st['member_cards']} "
              f"support={st['support_cards']} chars={st['characters']} decks={st['decks']} size={st['size']}")
    # 公开截图使用示例数据
    sample = {"name": "示例玩家", "profile_id": "123456789012", "server": "intl", "mtime": time.time() - 3600,
              "member_cards": 128, "support_cards": 96, "characters": 25, "decks": 12, "size": 2_900_000,
              "key_fp": "候选#1 sha256:xxxxxxxx"}
    w.p[w.C].set_saves([])
    w.p[w.C].set_stats(sample, "USB 提取")
    w.p[w.C].set_logged_in(False)
    w.stack.setCurrentIndex(w.C)
    shot("04_confirm")

    w.go(w.L)
    w.p[w.L].set_state("a")
    shot("05a_login")
    w.p[w.L].set_state("b")
    w.p[w.L]._t0 = time.time() - 12
    w.p[w.L]._tick()
    shot("05b_login_waiting")
    w.p[w.L].paste_row.show()
    shot("05b2_login_paste")
    now = int(time.time())
    store.save({"access_token": "demo", "refresh_token": "demo", "expires_in": 3600, "token_type": "Bearer",
                "obtained_at": now - 120, "expires_at": now + 3480,
                "id_token": fake_jwt({"sub": "demo", "username": "player_demo", "name": "Demo"})})
    w.refresh_login()
    shot("05c_login_done")
    w.p[w.L].show_error("ERR_AUTH_EXPIRED", None)
    shot("05d_login_expired")
    w.p[w.L].clear_error()

    w.p[w.F].set_result(2_900_000, time.time(), "示例玩家", "intl", True)
    w.go(w.F)
    shot("06_done_mock")

    g = QWidget()
    g.setObjectName("page")
    g.setStyleSheet(f"QWidget#page {{ background: {T.BG}; }}")
    v = QVBoxLayout(g)
    v.setContentsMargins(24, 20, 24, 20)
    v.addWidget(label("错误状态", "h1"))
    grid = QGridLayout()
    grid.setSpacing(14)
    for i, code in enumerate(["ERR_NO_DEVICE", "ERR_BACKUP_DENIED", "ERR_DECRYPT", "ERR_AUTH_EXPIRED"]):
        grid.addWidget(ErrorCard(code), i // 2, i % 2)
    v.addLayout(grid)
    g.resize(960, 520)
    g.show()
    shot("07_errors", g)

    d = SettingsDialog(w, w.key_text(), "国际服（com.bilibili.sirius）")
    d.show()
    shot("08_settings", d)
    d.close()
    print(len(shots), "screenshots")


if __name__ == "__main__":
    main()
