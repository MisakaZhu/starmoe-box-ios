"""主窗口与流程控制。启动：python -m starmoe_ios.gui"""
import getpass, hashlib, logging, os, subprocess, sys, time
from PySide6.QtCore import Qt, QEvent, QObject, QPoint, QSettings, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QIcon, QPixmap, QRegion
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QHBoxLayout, QStackedWidget, QFileDialog, QMessageBox,
                               QInputDialog, QLineEdit, QProgressDialog)
from . import theme as T, paths, APP_NAME, APP_DISPLAY, VERSION, HELP_URL
from .auth import TokenStore, register_url_scheme
from .pages import WelcomePage, DevicePage, ExtractPage, ConfirmPage, LoginPage, DonePage, AppleSupportPage
from .settings_dialog import SettingsDialog, resource_path
from .widgets import Sidebar, Logo
from .workers import Task, BackupWorker, run_async
from .. import api, core, device, savecodec, keyfetch, winsupport
from ..errors import StarMoeError, ERR_AUTH, ERR_AUTH_EXPIRED, ERR_PASSWORD, ERR_NETWORK, ERR_DECRYPT, ERR_KEYS, ERR_NO_DEVICE

log = logging.getLogger("starmoe.gui")
SERVER_ID = "StarMoeBox-iOS-" + hashlib.sha1(getpass.getuser().encode()).hexdigest()[:8]
MAX_RETRIES = 5
PASSCODE_NOTICE = "请解锁 iPhone 并输入锁屏密码，备份才会继续"


def alert_passcode(window, notify=None):
    """把用户叫回来：macOS 程序坞弹跳 + 通知，Windows 任务栏闪烁。notify 供测试替换系统通知。"""
    QApplication.alert(window, 0)
    if notify is not None:
        notify()
        return
    if sys.platform == "darwin":
        try:
            subprocess.Popen(
                ["osascript", "-e", f'display notification "{PASSCODE_NOTICE}" with title "StarMoe Box"'],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass


class Bridge(QObject):
    """把后台线程里的进度安全地送回界面线程。"""
    progress = Signal(int, int)
    status = Signal(str)


class MainWindow(QMainWindow):
    W, D, X, C, L, F, A = range(7)   # welcome / device / extract / confirm / login / done / apple-support(Windows)

    def __init__(self, store=None, settings=None, first_run=True):
        super().__init__()
        self.setWindowTitle(APP_DISPLAY)
        self.setMinimumSize(960, 640)
        self.resize(960, 640)
        self.settings = settings or QSettings("StarMoe", "StarMoeBox-iOS")
        self.store = store or TokenStore()
        self.codec = None
        self.key_info = None
        self.server = self.settings.value("server", "intl")
        self.saves, self.save = [], None
        self.source_desc = ""
        self.auth_req = None
        self.worker = None
        self.tasks = set()
        self.detecting = False
        self.last_backup_dir = None
        self.fetching = False
        self.auto_upload = False
        self.refetched = False
        self.apple_ok = sys.platform != "win32"
        self._passcode_alerted = False

        root = QWidget()
        root.setObjectName("root")
        h = QHBoxLayout(root)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        self.sidebar = Sidebar()
        h.addWidget(self.sidebar)
        self.stack = QStackedWidget()
        h.addWidget(self.stack, 1)
        self.setCentralWidget(root)
        self.p = [WelcomePage(), DevicePage(), ExtractPage(), ConfirmPage(), LoginPage(), DonePage(), AppleSupportPage()]
        for i, p in enumerate(self.p):
            self.stack.addWidget(p)
            p.action.connect(lambda a, i=i: self.on_action(i, a))
        self.p[self.W].server_changed.connect(self.set_server)
        self.p[self.C].account_changed.connect(self.select_save)
        self.sidebar.settings_clicked.connect(self.open_settings)
        self.sidebar.region_clicked.connect(lambda: None if self.busy() else self.go(self.W))

        self.poll = QTimer(self)
        self.poll.timeout.connect(self.poll_device)

        self.set_server(self.server)
        self.load_saved_keys()
        self.go(self.W)
        if first_run:
            QTimer.singleShot(300, self.on_startup)

    # ---------------------------------------------------------------- 通用
    def busy(self):
        return self.worker is not None and self.worker.isRunning()

    def run(self, fn, done, failed=None):
        t = Task(fn, self)
        self.tasks.add(t)
        t.done.connect(done)
        t.failed.connect(failed or self.generic_error)
        t.finished.connect(lambda: self.tasks.discard(t))
        t.start()
        return t

    def generic_error(self, code, msg, detail):
        log.warning("%s %s %s", code, msg, detail)
        QMessageBox.warning(self, APP_DISPLAY, f"{msg}\n\n({code})")

    def go(self, i):
        self.stack.setCurrentIndex(i)
        cur, done = {self.W: (0, 0), self.D: (0, 0), self.X: (1, 1), self.C: (1, 1), self.L: (2, 2),
                     self.F: (-1, 4), self.A: (0, 0)}[i]
        self.sidebar.set_step(cur, done)
        if i == self.D and not self.apple_ok:
            return self.check_apple(then_device=True)
        if i == self.C:
            self.p[self.C].set_logged_in(self.logged_in())
        if i == self.D:
            self.p[self.D].set_searching()
            self.poll.start(3000)
            self.poll_device(force=True)
        else:
            self.poll.stop()
        if i == self.L:
            self.refresh_login()

    def set_server(self, s):
        if s not in core.SERVER_NAMES:
            s = "intl"
        self.server = s
        self.settings.setValue("server", s)
        self.p[self.W].set_server(s)
        self.sidebar.set_region(f"{core.SERVER_NAMES[s]} · {core.BUNDLE_OF[s]}")

    @property
    def bundle(self):
        return core.BUNDLE_OF[self.server]

    # ---------------------------------------------------------------- 密钥
    @property
    def consented(self):
        return str(self.settings.value("auto_keys_consent", "false")).lower() == "true"

    def load_saved_keys(self):
        kind, path = self.settings.value("key_kind"), self.settings.value("key_path")
        if os.environ.get("OURNOTES_SAVE_KEY") and os.environ.get("OURNOTES_SAVE_MAGIC"):
            return self.apply_keys(savecodec.Codec.load(), {"kind": "env", "file": "OURNOTES_SAVE_KEY", "date": ""})
        if kind == "auto":
            meta = keyfetch.cached(paths.data_dir())
            path = meta and meta["path"]
        if kind and path and os.path.isfile(path):
            try:
                self.set_keys_from(kind, path, tag=(keyfetch.cached(paths.data_dir()) or {}).get("tag"))
            except StarMoeError as e:
                log.warning("自动加载密钥失败：%s", e)
        if not self.key_info:
            self.p[self.W].set_keys(None, self.consented)

    def set_keys_from(self, kind, path, tag=None):
        codec = savecodec.Codec.load(keys_file=path) if kind == "keys" else savecodec.Codec.load(apk=path)
        date = time.strftime("%Y-%m-%d", time.localtime(os.path.getmtime(path)))
        self.apply_keys(codec, {"kind": kind, "file": os.path.basename(path), "date": date, "tag": tag or "",
                                "path": path})
        self.settings.setValue("key_kind", kind)
        self.settings.setValue("key_path", path)   # 只记住文件位置，不保存密钥

    def apply_keys(self, codec, info):
        self.codec, self.key_info = codec, info
        self.p[self.W].set_keys(info, self.consented)

    def pick_keys(self, kind):
        flt = "Android 安装包 (*.apk);;所有文件 (*)" if kind == "apk" else "密钥文件 (*.json);;所有文件 (*)"
        title = "选择官方 StarMoe Box APK" if kind == "apk" else "选择密钥文件（JSON：key / magic）"
        path, _ = QFileDialog.getOpenFileName(self, title, os.path.expanduser("~/Downloads"), flt)
        if not path:
            return False
        try:
            self.set_keys_from(kind, path)
        except StarMoeError as e:
            QMessageBox.warning(self, "密钥加载失败", f"{e.message}\n\n({e.code})")
            return False
        self.p[self.W].clear_error()
        return True

    def key_text(self):
        if not self.key_info:
            return "未就绪（首次点“开始”时自动从 GitHub 获取官方 StarMoe Box APK）"
        src = {"auto": f"官方 StarMoe Box {self.key_info.get('tag', '')}（自动获取）",
               "apk": "官方 StarMoe Box APK（手动选择）", "keys": "密钥文件", "env": "环境变量"}[self.key_info["kind"]]
        return f"{src} · {self.key_info['file']}"

    def on_startup(self):
        """首次启动：征得同意后自动获取密钥；之后每次启动静默检查官方是否发布了新版（密钥可能轮换）。"""
        if self.key_info and self.key_info["kind"] in ("apk", "keys", "env"):
            return
        if self.consented:
            return self.auto_fetch(silent=bool(self.key_info))
        if not self.settings.value("consent_asked"):
            self.settings.setValue("consent_asked", True)
            self.ask_consent()

    def consent_box(self):
        box = QMessageBox(self)
        box.setWindowTitle("首次使用：自动获取密钥")
        box.setIcon(QMessageBox.Information)
        box.setText("解密存档需要官方 StarMoe Box 安卓版里的密钥。")
        box.setInformativeText("是否现在从 GitHub（StarMoe-org/StarMoe-box 官方发布页）下载官方安装包（约 1.4 MB）？\n\n"
                               "· 只用来在本机读取密钥，不会安装、不会上传；\n· 以后官方更新时会自动跟进；\n"
                               "· 也可以选择你自己下载好的 APK。")
        yes = box.addButton("同意并自动获取", QMessageBox.AcceptRole)
        manual = box.addButton("手动选择 APK…", QMessageBox.ActionRole)
        box.addButton("稍后", QMessageBox.RejectRole)
        box.setDefaultButton(yes)
        return box, yes, manual

    def ask_consent(self, then=None):
        box, yes, manual = self.consent_box()
        box.exec()
        if box.clickedButton() is yes:
            self.settings.setValue("auto_keys_consent", True)
            self.auto_fetch(then=then)
        elif box.clickedButton() is manual:
            if self.pick_keys("apk") and then:
                then()

    def auto_fetch(self, then=None, silent=False, on_fail=None):
        """后台下载/检查官方 APK。then(fresh) 在成功后调用。"""
        if self.fetching:
            return
        self.fetching = True
        self.settings.setValue("auto_keys_consent", True)
        page = self.p[self.W]
        br = Bridge(self)
        st = {"text": "正在获取密钥…"}
        if not silent:
            page.set_fetching(st["text"])
            br.status.connect(lambda m: (st.__setitem__("text", m), page.set_fetching(m)))
            br.progress.connect(lambda d, t: page.set_fetching(st["text"], d, t))
        base = paths.data_dir()
        cur = self.key_info.get("path") if self.key_info else None

        def work():
            return keyfetch.fetch_apk(base, progress=lambda d, t: br.progress.emit(d, t), status=br.status.emit)

        def ok(res):
            self.fetching = False
            meta, fresh = res
            changed = fresh or meta["path"] != cur
            try:
                if changed or not self.codec:
                    self.set_keys_from("auto", meta["path"], tag=meta["tag"])
                else:
                    self.p[self.W].set_keys(self.key_info, True)
            except StarMoeError as e:
                return bad(e.code, e.message, e.detail)
            log.info("密钥来源：官方 %s（%s）", meta["tag"], "新下载" if fresh else "缓存")
            if then:
                then(changed)

        def bad(code, msg, detail):
            self.fetching = False
            log.warning("自动获取密钥失败：%s %s", code, detail)
            self.p[self.W].set_keys(self.key_info, True)
            if on_fail:
                return on_fail(code, msg, detail)
            if not silent:
                self.go(self.W)
                self.p[self.W].show_error(ERR_KEYS, msg, detail)
        self.run(work, ok, bad)

    def start(self):
        """欢迎页的“开始”：密钥没好就先自动获取，然后进入连接手机。"""
        if self.codec:
            return self.go(self.D)
        if self.consented:
            return self.auto_fetch(then=lambda _c: self.go(self.D))
        self.ask_consent(then=lambda *_: self.go(self.D))

    def retry_with_new_keys(self, retry, code, msg, detail, show):
        """解密失败时：检查官方是否发布了新版 APK（密钥可能已轮换），有就换上并重试一次。"""
        if code != ERR_DECRYPT or self.refetched or not self.consented:
            return show(code, msg, detail)
        self.refetched = True

        def then(changed):
            if changed:
                log.info("密钥已更新，重新解析")
                retry()
            else:
                show(code, msg, detail)
        self.auto_fetch(then=then, silent=True, on_fail=lambda *_: show(code, msg, detail))

    # ---------------------------------------------------------------- Windows：Apple 设备支持
    def check_apple(self, then_device=False):
        def ok(r):
            self.apple_ok = r["ok"]
            if r["ok"]:
                if then_device:
                    self.go(self.D)
            else:
                self.p[self.A].set_state(r["state"])
                self.go(self.A)
        self.run(lambda: winsupport.check(), ok, lambda *a: (setattr(self, "apple_ok", True), self.go(self.D)))

    # ---------------------------------------------------------------- 动作分发
    def on_action(self, page, a):
        log.info("动作 %s @ %d", a, page)
        if a == "auto_keys":
            self.refetched = False
            return self.auto_fetch(then=(lambda c: self.rescan()) if page in (self.X, self.C) else None)
        if a == "reload_keys" or a == "keys_file":
            if self.pick_keys("apk" if a == "reload_keys" else "keys") and page in (self.X, self.C):
                self.rescan()
            return
        if a == "folder":
            return self.import_folder()
        if a == "region":
            return self.go(self.W)
        if a == "help":
            return QDesktopServices.openUrl(QUrl(HELP_URL))
        if a == "dismiss":
            return self.p[page].clear_error()
        if page == self.W and a == "next":
            return self.start()
        if page == self.A:
            if a == "open_store":
                if not QDesktopServices.openUrl(QUrl(winsupport.STORE_URL)):
                    QDesktopServices.openUrl(QUrl(winsupport.STORE_WEB))
                return
            if a == "recheck_apple":
                return self.check_apple(then_device=True)
            if a == "back":
                return self.go(self.W)
        if page == self.D:
            return {"redetect": lambda: self.poll_device(force=True), "back": lambda: self.go(self.W),
                    "validate": self.p[self.D].validate, "start": self.start_backup}.get(a, lambda: None)()
        if page == self.X:
            if a == "cancel":
                return self.cancel_backup()
            if a in ("retry", "back"):
                return self.go(self.D)
            if a == "password":
                self.go(self.D)
                return self.p[self.D].pw.setFocus()
            if a == "rescan":
                return self.rescan(ask_password=True)
        if page == self.C:
            return {"export": self.export_json, "retry": lambda: self.go(self.D), "next": self.upload_or_login}.get(
                a, lambda: None)()
        if page == self.L:
            return {"login": self.start_login, "reopen": self.reopen_browser, "cancel_login": self.cancel_login,
                    "paste": lambda: self.handle_callback(self.p[self.L].paste.text()), "switch": self.switch_account,
                    "logout": self.logout, "relogin": self.start_login, "upload": self.upload,
                    "back": lambda: self.go(self.C)}.get(a, lambda: None)()
        if page == self.F:
            return {"open_deck": lambda: QDesktopServices.openUrl(QUrl(api.DECK_URL)), "export": self.export_json,
                    "again": lambda: self.go(self.D), "finish": lambda: self.go(self.W)}.get(a, lambda: None)()

    # ---------------------------------------------------------------- 设备检测
    def poll_device(self, force=False):
        if self.detecting or self.stack.currentIndex() != self.D:
            return
        page = self.p[self.D]
        if page.info and not force:   # 已连接：只轻量检查是否被拔出
            udid = page.info["udid"]
            self.detecting = True

            def done(serials):
                self.detecting = False
                if udid not in (serials or []):
                    page.set_searching("设备已断开，等待重新连接…")

            def failed(*_):
                self.detecting = False
            return self.run(run_async(device.list_serials), done, failed)
        self.detecting = True
        bundle = self.bundle

        def ok(info):
            self.detecting = False
            if self.stack.currentIndex() == self.D:
                page.set_device(info, core.SERVER_NAMES[self.server])

        def bad(code, msg, detail):
            self.detecting = False
            if self.stack.currentIndex() == self.D:
                page.set_device_error(code, msg, detail)
                if sys.platform == "win32" and code == ERR_NO_DEVICE:
                    self.check_apple()
        self.run(run_async(lambda: device.detect(bundle)), ok, bad)

    # ---------------------------------------------------------------- 提取
    def start_backup(self):
        if not self.codec:
            return self.go(self.W)
        self.poll.stop()
        pw = self.p[self.D].password()
        out = os.path.join(paths.backup_dir(), self.bundle)
        self.worker = w = BackupWorker(self.codec, self.bundle, self.server, out, pw, MAX_RETRIES, parent=self)
        w.retrying.connect(self.p[self.X].set_retrying)
        w.scanning.connect(self.p[self.X].set_scanning)
        w.found.connect(lambda s: self.on_found(s, "USB 过滤备份", str(w.stats.udid_dir)))
        w.failed.connect(self.on_backup_failed)
        w.cancelled.connect(lambda: self.go(self.D))
        w.tick.connect(self.refresh_extract)
        w.finished.connect(self.refresh_extract)
        self.backup_password = pw
        self.p[self.X].reset()
        self.go(self.X)
        w.start()

    def refresh_extract(self):
        w = self.worker
        if not w:
            return
        s = w.stats
        page = self.p[self.X]
        page.update_stats(s.percent, s.received, s.kept, s.kept_bytes, time.time() - s.started, s.phase)
        page.set_passcode(bool(s.passcode_needed))
        if s.passcode_needed and not self._passcode_alerted:
            self._passcode_alerted = True
            alert_passcode(self)
        elif not s.passcode_needed:
            self._passcode_alerted = False

    def cancel_backup(self):
        if self.busy() and QMessageBox.question(
                self, "取消提取", "确定取消提取吗？如果游戏文件已经传完，会尝试直接解析已收到的文件。") == QMessageBox.Yes:
            self.worker.cancel()

    def on_backup_failed(self, code, msg, detail):
        self.last_backup_dir = str(self.worker.stats.udid_dir) if self.worker and self.worker.stats.udid_dir else None
        show = lambda c, m, d: self.p[self.X].show_error(c, m, d, index=0)
        if self.last_backup_dir:
            return self.retry_with_new_keys(self.rescan, code, msg, detail, show)
        show(code, msg, detail)

    def rescan(self, ask_password=False):
        d = self.last_backup_dir or (self.worker and self.worker.stats.udid_dir and str(self.worker.stats.udid_dir))
        if not d:
            return self.go(self.D)
        pw = getattr(self, "backup_password", None)
        if ask_password:
            pw, ok = QInputDialog.getText(self, "备份密码", "加密本地备份的密码：", QLineEdit.Password)
            if not ok:
                return
            self.backup_password = pw
        self.scan_in_background(d, pw, "USB 过滤备份")

    def import_folder(self):
        if not self.codec:
            QMessageBox.information(self, APP_DISPLAY, "请先加载解密密钥。")
            return self.go(self.W)
        d = QFileDialog.getExistingDirectory(self, "选择已导出的游戏文件夹（或 iPhone 备份文件夹）", os.path.expanduser("~"))
        if d:
            self.scan_in_background(d, None, "文件夹导入")

    def scan_in_background(self, path, password, label_text):
        dlg = QProgressDialog("正在解密并查找存档…（大存档约需 10–30 秒）", None, 0, 0, self)
        dlg.setWindowTitle(APP_DISPLAY)
        dlg.setWindowModality(Qt.WindowModal)
        dlg.setMinimumDuration(0)
        dlg.show()
        codec, server = self.codec, self.server

        def done(saves):
            dlg.close()
            self.on_found(saves, label_text, path)

        def failed(code, msg, detail):
            dlg.close()
            if code == ERR_PASSWORD:
                pw, ok = QInputDialog.getText(self, "备份密码", f"{msg}\n请输入“加密本地备份”的密码：", QLineEdit.Password)
                if ok and pw:
                    return self.scan_in_background(path, pw, label_text)
                return
            def show(code, msg, detail):
                page = self.stack.currentIndex()
                if page in (self.W, self.D, self.X, self.C):
                    self.go(self.X if page != self.X else page)
                    self.p[self.X].reset()
                    self.p[self.X].set_scanning()
                    self.last_backup_dir = path
                    self.p[self.X].show_error(code, msg, detail)
                else:
                    self.generic_error(code, msg, detail)
            self.retry_with_new_keys(lambda: self.scan_in_background(path, password, label_text), code, msg, detail, show)
        self.run(lambda: core.scan_path(codec, path, server, password, log=log.info), done, failed)

    def on_found(self, saves, source, path):
        self.refetched = False
        self.saves = sorted(saves, key=lambda s: -s["mtime"])
        self.source_desc = source
        self.p[self.C].set_saves(self.saves)
        self.select_save(0)
        self.go(self.C)

    def select_save(self, i):
        if 0 <= i < len(self.saves):
            self.save = self.saves[i]
            self.stats = core.player_stats(self.save)
            self.p[self.C].set_stats(self.stats, self.source_desc)

    def export_json(self):
        if not self.save:
            return
        name = f"{self.save['server']}_{self.save['account_id']}_player.json"
        path, _ = QFileDialog.getSaveFileName(self, "导出 _player JSON", os.path.join(os.path.expanduser("~"), name),
                                              "JSON (*.json)")
        if path:
            with open(path, "wb") as f:
                f.write(self.save["bytes"])
            QMessageBox.information(self, APP_DISPLAY, f"已导出到\n{path}")

    # ---------------------------------------------------------------- 登录
    def logged_in(self):
        tok = self.store.load()
        return bool(tok and (tok.get("refresh_token") or tok.get("expires_at", 0) > time.time()))

    def upload_or_login(self):
        """存档确认页的主按钮：已登录就直接上传；没登录就打开浏览器登录，登录成功后自动上传。"""
        if self.logged_in():
            self.go(self.L)
            return self.upload()
        self.auto_upload = True
        self.go(self.L)
        self.start_login()

    def refresh_login(self):
        page = self.p[self.L]
        tok = self.store.load()
        if tok and (tok.get("refresh_token") or tok.get("expires_at", 0) > time.time()):
            claims = api.id_claims(tok)
            where = {"darwin": "本机钥匙串", "win32": "Windows 凭据管理器"}.get(sys.platform, "系统密钥环")
            info = (f"上次授权：{core.format_time(tok.get('obtained_at'))} · " +
                    (f"令牌仅保存在{where}中" if self.store.persistent else "系统钥匙串不可用，令牌仅保存在内存中（关闭后需重新登录）"))
            page.set_state("c", api.display_name(claims), info, can_upload=self.save is not None)
        elif self.auth_req:
            page.set_state("b")
        else:
            page.set_state("a")

    def start_login(self):
        try:
            log.info(register_url_scheme())
        except Exception as e:   # 注册失败不影响手动粘贴
            log.warning("注册 URL Scheme 失败：%r", e)
        self.auth_req = api.auth_request()
        QDesktopServices.openUrl(QUrl(self.auth_req["url"]))
        if self.stack.currentIndex() != self.L:
            self.go(self.L)
        self.p[self.L].set_state("b")

    def reopen_browser(self):
        if self.auth_req:
            QDesktopServices.openUrl(QUrl(self.auth_req["url"]))
        else:
            self.start_login()

    def cancel_login(self):
        self.auth_req = None
        self.auto_upload = False
        self.refresh_login()

    def handle_callback(self, url):
        url = (url or "").strip()
        if not url:
            return
        self.raise_window()
        if not api.is_callback(url):
            return self.p[self.L].show_error(ERR_AUTH, "这不是 moe.starmoe.box:// 回调地址。")
        req = self.auth_req
        if not req:
            log.info("收到回调但没有进行中的登录")
            if self.stack.currentIndex() == self.L:
                self.p[self.L].show_error(ERR_AUTH, "收到登录回调，但本次运行中没有发起登录（可能是旧的回调），请重新登录。")
            return
        self.auth_req = None

        def ok(tok):
            self.store.save(tok)
            self.go(self.L)
            if self.auto_upload and self.save:
                self.auto_upload = False
                self.upload()

        def bad(code, msg, detail):
            self.go(self.L)
            self.p[self.L].show_error(ERR_AUTH if code != ERR_NETWORK else code, msg, detail)
        self.run(lambda: api.exchange(url, req), ok, bad)

    def logout(self):
        self.store.clear()
        self.auth_req = None
        self.refresh_login()

    def switch_account(self):
        self.store.clear()
        self.start_login()

    # ---------------------------------------------------------------- 上传
    def upload(self):
        if not self.save:
            return
        save, store = self.save, self.store
        page = self.p[self.L]
        page.btn_upload.setEnabled(False)
        page.btn_upload.setText("正在上传…")

        def do():
            tok = store.access_token()
            try:
                r = api.upload(tok, save["server"], save["bytes"])
            except api.ApiError as e:
                if e.status != 401:
                    raise
                r = api.upload(store.force_refresh(), save["server"], save["bytes"])
            return r

        def ok(r):
            changed = r.get("changed") if isinstance(r, dict) else None
            self.p[self.F].set_result(len(save["bytes"]), time.time(), api.display_name(store.claims()), save["server"],
                                      changed)
            self.go(self.F)

        def bad(code, msg, detail):
            self.refresh_login()
            if code == ERR_AUTH_EXPIRED:
                self.store.clear()
                self.refresh_login()
            page.show_error(code, msg, detail)
        self.run(do, ok, bad)

    # ---------------------------------------------------------------- 其他
    def open_settings(self):
        d = SettingsDialog(self, self.key_text(), f"{core.SERVER_NAMES[self.server]}（{self.bundle}）", self.server)
        d.action.connect(lambda a: self.on_action(self.stack.currentIndex(), a))
        d.server_changed.connect(self.set_server)
        d.exec()

    def raise_window(self):
        self.show()
        self.setWindowState((self.windowState() & ~Qt.WindowMinimized) | Qt.WindowActive)
        self.raise_()
        self.activateWindow()

    def closeEvent(self, e):
        if self.busy():
            if QMessageBox.question(self, APP_DISPLAY, "正在提取存档，确定要退出吗？") != QMessageBox.Yes:
                return e.ignore()
            self.worker.cancel()
            self.worker.wait(5000)
        e.accept()


class App(QApplication):
    """macOS：系统把 moe.starmoe.box:// 交给 .app 时，Qt 以 QFileOpenEvent 投递（含冷启动）。"""

    def __init__(self, argv):
        super().__init__(argv)
        self.window = None
        self.pending = []

    def event(self, e):
        if e.type() == QEvent.FileOpen:
            url = e.url().toString() if not e.url().isEmpty() else e.file()
            self.deliver(url)
            return True
        return super().event(e)

    def deliver(self, url):
        log.info("收到外部 URL（scheme=%s）", url.split(":", 1)[0])
        if self.window:
            self.window.handle_callback(url)
        else:
            self.pending.append(url)


def app_icon():
    w = Logo(256)
    pm = QPixmap(256, 256)
    pm.fill(Qt.transparent)
    w.render(pm, QPoint(0, 0), QRegion(), QWidget.RenderFlag.DrawChildren)
    return QIcon(pm)


def selftest():
    """打包后自检：确认延迟导入的模块都被打进去了（CI 用）。返回进程退出码。"""
    import importlib
    mods = ["pymobiledevice3.usbmux", "pymobiledevice3.lockdown", "pymobiledevice3.services.mobilebackup2",
            "pymobiledevice3.services.device_link", "pymobiledevice3.services.installation_proxy",
            "pymobiledevice3.services.house_arrest", "pymobiledevice3.exceptions", "iphone_backup_decrypt", "keyring",
            "PySide6.QtSvg", "PySide6.QtNetwork", "certifi", "starmoe_ios.tls"]
    bad = []
    for m in mods:
        try:
            importlib.import_module(m)
        except Exception as e:   # noqa: BLE001
            bad.append(f"{m}: {e!r}")
    ca_note = ""
    try:
        from ..tls import ca_bundle, ssl_backend
        p = ca_bundle()
        n = os.path.getsize(p)
        if n < 10000:
            bad.append(f"ca bundle too small: {p} ({n})")
        else:
            ca_note = f"tls: {ssl_backend()} ca={p} ({n} bytes)\n"
    except Exception as e:   # noqa: BLE001
        bad.append(f"ca bundle: {e!r}")
    import keyring
    kb = keyring.get_keyring()
    out = os.path.join(paths.log_dir(), "selftest.txt")
    msg = (f"{APP_DISPLAY} v{VERSION} selftest\nkeyring backend: {type(kb).__module__}.{type(kb).__name__}\n" +
           ca_note + ("OK\n" if not bad else "FAILED\n" + "\n".join(bad) + "\n"))
    with open(out, "w", encoding="utf-8") as f:
        f.write(msg)
    if sys.stdout:
        print(msg, end="")
    return 1 if bad else 0


def main(argv=None):
    argv = list(sys.argv if argv is None else argv)
    if "--selftest" in argv:
        return selftest()
    paths.setup_logging()
    log.info("启动 %s v%s (%s)", APP_DISPLAY, VERSION, sys.platform)
    QApplication.setApplicationName(APP_NAME)
    QApplication.setOrganizationName("StarMoe")
    app = App(argv)
    urls = [a for a in argv[1:] if api.is_callback(a)]

    # 单实例：Windows/Linux 点击回调链接时系统会再启动一个进程，把 URL 转交给正在运行的实例后退出
    sock = QLocalSocket()
    sock.connectToServer(SERVER_ID)
    if sock.waitForConnected(500):
        sock.write(("\n".join(urls) if urls else "SHOW").encode() + b"\n")
        sock.flush()
        sock.waitForBytesWritten(2000)
        sock.disconnectFromServer()
        return 0
    QLocalServer.removeServer(SERVER_ID)
    server = QLocalServer()
    server.listen(SERVER_ID)

    app.setStyleSheet(T.QSS)
    app.setWindowIcon(app_icon())
    win = MainWindow()
    app.window = win

    def on_conn():
        c = server.nextPendingConnection()

        def read():
            for line in bytes(c.readAll()).decode(errors="replace").splitlines():
                if line.strip() == "SHOW":
                    win.raise_window()
                elif line.strip():
                    app.deliver(line.strip())
        c.readyRead.connect(read)
        c.disconnected.connect(c.deleteLater)
    server.newConnection.connect(on_conn)

    if os.environ.get("STARMOE_SMOKE_MS"):   # 冒烟测试：启动后自动退出
        QTimer.singleShot(int(os.environ["STARMOE_SMOKE_MS"]), app.quit)
    win.show()
    for u in app.pending + urls:
        win.handle_callback(u)
    app.pending.clear()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
