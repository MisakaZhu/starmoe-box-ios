"""GUI 逻辑测试（无界面）：QT_QPA_PLATFORM=offscreen PYTHONPATH=. python tests/test_gui.py
不连接设备、不访问网络。"""
import asyncio, base64, json, os, pathlib, sys, tempfile, time
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("STARMOE_DATA_DIR", tempfile.mkdtemp(prefix="starmoe-test-"))
from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer, QSettings
from PySide6.QtWidgets import QApplication
from starmoe_ios.rijndael import Rijndael256
from starmoe_ios.savecodec import Codec
from starmoe_ios.errors import StarMoeError
from starmoe_ios import device, api
from starmoe_ios.gui import workers, auth

app = QApplication(sys.argv)
key, magic, iv = os.urandom(32), os.urandom(32), os.urandom(32)
save = b'{"_version":3, "_player": {"_profileId": 987654321, "_name": "Tester", "_memberCards":[1,2]}}'
pad = 32 - len(save) % 32
BLOB = magic + iv + Rijndael256(key).encrypt_cbc(save + bytes([pad]) * pad, iv)
CODEC = Codec(magic, [key])


class ConnectionTerminatedError(Exception):
    pass


def run_worker(runner, **kw):
    out = tempfile.mkdtemp()
    w = workers.BackupWorker(CODEC, "com.bilibili.sirius", "intl", os.path.join(out, "b"), None, runner=runner, **kw)
    ev = {"retrying": [], "found": None, "failed": None, "cancelled": False}
    w.retrying.connect(lambda a, b: ev["retrying"].append((a, b)))
    w.found.connect(lambda s: ev.__setitem__("found", s))
    w.failed.connect(lambda c, m, d: ev.__setitem__("failed", c))
    w.cancelled.connect(lambda: ev.__setitem__("cancelled", True))
    loop = QEventLoop()
    w.finished.connect(loop.quit)
    w.start()
    return w, ev, loop


def finish(loop, w, ms=20000):
    QTimer.singleShot(ms, loop.quit)
    loop.exec()
    w.wait(2000)
    QCoreApplication.processEvents()


def make_runner(plan, calls):
    """plan: 每次调用的行为列表：'drop'（收到一些字节后断开）/'save_drop'（存档已到手后断开）/'ok'/'deny'/'hang'"""
    async def runner(bundle, out_dir, stats, on_log=None, **_):
        step = plan[len(calls)]
        calls.append(step)
        stats.udid_dir = pathlib.Path(out_dir) / "UDID"
        stats.udid_dir.mkdir(parents=True, exist_ok=True)
        stats.received += 1000
        if step == "hang":
            await asyncio.sleep(60)
        if step == "prepare_timeout":
            stats.received = 0
            raise TimeoutError("snapshot")
        if step == "finalize_timeout":
            stats.phase = "finalizing"
            stats.received = 5000
            raise TimeoutError("moving")
        if step == "empty_ok":
            stats.kept = 0
            return stats.udid_dir, False
        if step == "deny":
            raise StarMoeError("ERR_BACKUP_DENIED", "denied")
        if step in ("save_drop", "ok"):
            (stats.udid_dir / "ab").mkdir(exist_ok=True)
            (stats.udid_dir / "ab" / ("ab" + "0" * 38)).write_bytes(BLOB)
            stats.kept += 1
        if step in ("drop", "save_drop"):
            raise ConnectionTerminatedError("cable")
        return stats.udid_dir, False
    return runner


async def fake_serials():
    return ["UDID"]
device.list_serials = fake_serials
workers.device.list_serials = fake_serials

# 1) 断开 → 自动重试 → 成功
calls = []
w, ev, loop = run_worker(make_runner(["drop", "drop", "ok"], calls))
finish(loop, w)
assert calls == ["drop", "drop", "ok"], calls
assert ev["retrying"] == [(1, 5), (2, 5)], ev
assert ev["found"] and ev["found"][0]["account_id"] == "987654321", ev
print("RETRY OK")

# 2) 断开时存档已到手 → 直接解析，不再重传
calls = []
w, ev, loop = run_worker(make_runner(["save_drop", "ok"], calls))
finish(loop, w)
assert calls == ["save_drop"] and ev["found"] and not ev["retrying"], (calls, ev)
print("SALVAGE OK")

# 3) 超过最大重试次数
calls = []
w, ev, loop = run_worker(make_runner(["drop"] * 3, calls), max_retries=2)
finish(loop, w)
assert len(calls) == 3 and ev["failed"] == "ERR_DISCONNECTED", (calls, ev)
print("MAX RETRY OK")

# 4) 不可重试的错误
calls = []
w, ev, loop = run_worker(make_runner(["deny"], calls))
finish(loop, w)
assert ev["failed"] == "ERR_BACKUP_DENIED" and not ev["retrying"], ev
print("DENY OK")

# 5) 取消
calls = []
w, ev, loop = run_worker(make_runner(["hang"], calls))
QTimer.singleShot(500, w.cancel)
finish(loop, w)
assert ev["cancelled"] and not ev["found"], ev
print("CANCEL OK")

# 5b) 快照阶段的读超时不是断线：不弹重试横幅，并继续下一次备份
calls = []
w, ev, loop = run_worker(make_runner(["prepare_timeout", "ok"], calls))
finish(loop, w)
assert calls == ["prepare_timeout", "ok"] and ev["retrying"] == [] and ev["found"], (calls, ev)
print("PREPARE WAIT OK")

# 5c) 准备超过 15 分钟仍是 0 字节，才按断线重试
calls = []


async def late_prepare(bundle, out_dir, stats, on_log=None, **_):
    step = plan_late[len(calls)]
    calls.append(step)
    if step == "late":
        stats.started = time.time() - 16 * 60
        stats.received = 0
        raise TimeoutError("snapshot")
    stats.udid_dir = pathlib.Path(out_dir) / "UDID"
    stats.udid_dir.mkdir(parents=True, exist_ok=True)
    (stats.udid_dir / "ab").mkdir(exist_ok=True)
    (stats.udid_dir / "ab" / ("ab" + "0" * 38)).write_bytes(BLOB)
    stats.kept += 1
    return stats.udid_dir, False


plan_late = ["late", "ok"]
w, ev, loop = run_worker(late_prepare)
finish(loop, w)
assert calls == ["late", "ok"] and ev["retrying"] == [(1, 5)] and ev["found"], (calls, ev)
print("PREPARE TIMEOUT OK")

# 5d) ETA 用最近传输速度，不把准备阶段的空等算进去
from starmoe_ios.gui.pages import ExtractPage, eta_seconds, TransferRate
received = int(17.7 * 1024 ** 3)
rate = 265.4 * 1024 ** 2
elapsed = 10 * 60 + 48
old_minutes = elapsed * (100 - 5) / 5 / 60
assert old_minutes > 180   # 旧算法会得到约 205 分钟
secs = eta_seconds(received, 5, rate)
assert 20 * 60 <= secs <= 23 * 60, secs
page = ExtractPage()
t0 = 1_000_000.0
page._rate.samples = [(t0, int(received - rate * 45))]
page.update_stats(5, received, 3, 0, elapsed, "transferring", now=t0 + 45)
assert page.eta.text().startswith("预计剩余约") and "187" not in page.eta.text(), page.eta.text()
mins = int(page.eta.text().split("约")[1].split("分钟")[0])
assert 20 <= mins <= 23, page.eta.text()
assert page.note.text() == "整机数据需要全部传一遍，只保留游戏文件"
assert "MB/s" in page.t_speed.v.text() or "GB/s" in page.t_speed.v.text(), page.t_speed.v.text()
# 准备阶段：不定进度，且 0 字节样本不拉低速度
page.update_stats(0, 0, 0, 0, 300, "preparing", now=t0 + 50)
assert "准备备份" in page.state.text() and page.bar.maximum() == 0
assert page._rate.rate > 0   # 准备阶段不把速度清成按全程平均
# 重试横幅在再次收到数据后消失
page.set_retrying(1, 5)
assert not page.retry.isHidden()
page.update_stats(5, received, 3, 0, elapsed, "transferring", now=t0 + 46)
assert page.retry.isHidden()
# 纯窗口：更早的 0 字节点若被 observe 在非传输阶段，不应进入样本
r = TransferRate()
r.observe(0, 0, False)
r.observe(600, 0, False)
r.observe(600, received - rate * 45, True)
r.observe(645, received, True)
assert abs(r.rate - rate) / rate < 0.02, r.rate
print("ETA OK", page.eta.text(), page.t_speed.v.text())


# 6) TokenStore：分字段保存、自动刷新、轮换 refresh token、退出登录
class FakeKR(dict):
    def get_password(self, s, k): return self.get((s, k))
    def set_password(self, s, k, v): self[(s, k)] = v
    def delete_password(self, s, k): self.pop((s, k), None)


kr = FakeKR()
st = auth.TokenStore(backend=kr)
assert st.persistent
now = int(time.time())
st.save({"access_token": "A1", "refresh_token": "R1", "id_token": "x.eyJ1c2VybmFtZSI6Im0ifQ.y", "expires_at": now + 3600,  # gitleaks:allow (fake token)
         "obtained_at": now})
assert ("StarMoeBox-iOS", "access_token") in kr and "A1" not in kr[("StarMoeBox-iOS", "meta")]
st2 = auth.TokenStore(backend=kr)   # 重新启动后从钥匙串读取
assert st2.access_token() == "A1" and st2.claims().get("username") == "m"
seen = []
st2.save(dict(st2.load(), expires_at=now + 10))   # 即将过期
def refresh(rt):
    seen.append(rt)
    return {"access_token": "A2", "refresh_token": "R2", "expires_at": now + 3600, "obtained_at": now}
assert st2.access_token(refresh_fn=refresh) == "A2" and seen == ["R1"]
assert auth.TokenStore(backend=kr).load()["refresh_token"] == "R2"
st2.clear()
assert not kr and auth.TokenStore(backend=kr).load() is None
try:
    st2.access_token()
    raise AssertionError
except StarMoeError as e:
    assert e.code == "ERR_AUTH_EXPIRED"
mem = auth.TokenStore(backend=False)
assert not mem.persistent
mem.save({"access_token": "M", "expires_at": now + 3600})
assert mem.access_token() == "M"
print("TOKENS OK")

# 7) 登录回调：state 校验、错误参数、非本应用地址
req = api.auth_request()
assert req["url"].startswith("https://") and "code_challenge=" in req["url"] and "state=" in req["url"]
assert api.is_callback("moe.starmoe.box://moe.starmoe.box/callback?code=1&state=2")
assert not api.is_callback("https://evil.example/callback?code=1")
for bad, code in [(f"{api.REDIRECT}?code=1&state=WRONG", "ERR_AUTH"),
                  (f"{api.REDIRECT}?error=access_denied&state={req['state']}", "ERR_AUTH")]:
    try:
        api.exchange(bad, req)
        raise AssertionError(bad)
    except StarMoeError as e:
        assert e.code == code, (bad, e.code)


# 8) 主窗口：回调分发（无进行中的登录 / 交换成功）
from starmoe_ios.gui.app import MainWindow
w = MainWindow(store=auth.TokenStore(backend=FakeKR()),
               settings=QSettings(os.path.join(os.environ["STARMOE_DATA_DIR"], "t.ini"), QSettings.IniFormat),
               first_run=False)
w.go(w.L)
w.handle_callback(f"{api.REDIRECT}?code=1&state=x")
assert w.p[w.L].error is not None
w.p[w.L].clear_error()
real_exchange = api.exchange
api.exchange = lambda url, r: {"access_token": "T", "refresh_token": "R", "obtained_at": now, "expires_at": now + 3600,
                               "id_token": "x." + base64.urlsafe_b64encode(b'{"username":"cb"}').decode().rstrip("=") + ".y"}
w.auth_req = {"state": "s", "verifier": "v", "url": "https://x"}
w.handle_callback(f"{api.REDIRECT}?code=1&state=s")
loop = QEventLoop()
QTimer.singleShot(1500, loop.quit)
loop.exec()
api.exchange = real_exchange
assert w.p[w.L].stack.currentIndex() == 2 and w.p[w.L].user.text() == "cb", w.p[w.L].stack.currentIndex()
assert w.auth_req is None
print("CALLBACK OK")


def spin(ms=800):
    l = QEventLoop()
    QTimer.singleShot(ms, l.quit)
    l.exec()


# 9) 自动获取密钥：“开始”→（已同意）后台获取 → 加载 → 进入连接手机
from starmoe_ios import keyfetch, savecodec
from starmoe_ios.errors import ERR_DECRYPT
fake_apk = os.path.join(os.environ["STARMOE_DATA_DIR"], "fake.apk")
open(fake_apk, "wb").write(b"x")
real_fetch, real_load = keyfetch.fetch_apk, savecodec.Codec.load
calls = []


def fake_fetch(base, progress=None, status=None, **kw):
    calls.append(1)
    status("正在下载官方安装包 v1…")
    progress(50, 100)
    return {"path": fake_apk, "tag": "v%d" % len(calls), "sha256": "x"}, True


keyfetch.fetch_apk = fake_fetch
savecodec.Codec.load = staticmethod(lambda apk=None, keys_file=None: CODEC)
device.detect = lambda bundle: (_ for _ in ()).throw(StarMoeError("ERR_NO_DEVICE", "无设备"))
w.codec = w.key_info = None
w.settings.setValue("auto_keys_consent", True)
w.go(w.W)
w.on_action(w.W, "next")
spin()
assert calls and w.codec is CODEC and w.key_info["kind"] == "auto" and w.key_info["tag"] == "v1"
assert w.stack.currentIndex() == w.D, w.stack.currentIndex()
assert w.settings.value("key_kind") == "auto"
print("AUTO KEYS OK")

# 10) 解密失败 → 自动检查新版密钥 → 有新版则重试一次；仍失败则显示错误
ev = {"retry": 0, "shown": 0}
w.refetched = False
w.retry_with_new_keys(lambda: ev.__setitem__("retry", ev["retry"] + 1), ERR_DECRYPT, "m", "d",
                      lambda *a: ev.__setitem__("shown", ev["shown"] + 1))
spin()
assert ev == {"retry": 1, "shown": 0} and len(calls) == 2, (ev, calls)
w.retry_with_new_keys(lambda: ev.__setitem__("retry", ev["retry"] + 1), ERR_DECRYPT, "m", "d",
                      lambda *a: ev.__setitem__("shown", ev["shown"] + 1))
spin(200)
assert ev == {"retry": 1, "shown": 1} and len(calls) == 2, (ev, calls)
print("DECRYPT REFETCH OK")

# 11) 网络失败 → 欢迎页显示错误（含“手动选择 APK”）
def fail_fetch(base, **kw):
    raise StarMoeError("ERR_NETWORK", "无法连接 GitHub")
keyfetch.fetch_apk = fail_fetch
w.codec = w.key_info = None
w.on_action(w.W, "next")
spin()
assert w.stack.currentIndex() == w.W and w.p[w.W].error is not None
print("FETCH FAIL OK")
keyfetch.fetch_apk, savecodec.Codec.load = real_fetch, real_load

# 12) 确认存档 → 已登录直接上传；未登录 → 登录 → 授权成功后自动上传
ups = []
w.upload = lambda: ups.append(1)
w.save = {"server": "intl", "bytes": b"{}"}
w.on_action(w.C, "next")
assert ups == [1] and w.stack.currentIndex() == w.L
w.store.clear()
started = []
w.start_login = lambda: started.append(1)
w.on_action(w.C, "next")
assert started and w.auto_upload and ups == [1]
api.exchange = lambda url, r: {"access_token": "T", "refresh_token": "R", "obtained_at": now, "expires_at": now + 3600}
w.auth_req = {"state": "s2", "verifier": "v", "url": "https://x"}
w.handle_callback(f"{api.REDIRECT}?code=1&state=s2")
spin(1500)
api.exchange = real_exchange
assert ups == [1, 1] and not w.auto_upload, ups
print("AUTO UPLOAD OK")

# 13) 设置里的服务器切换是分段按钮，不是系统 QComboBox；选择会写回并保持
from PySide6.QtWidgets import QComboBox
from starmoe_ios.gui.settings_dialog import SettingsDialog
from starmoe_ios.gui.widgets import SegmentedControl
picked = []
dlg = SettingsDialog(None, "官方 StarMoe Box", "国际服（com.bilibili.sirius）", "jp")
assert dlg.findChildren(QComboBox) == []
seg = dlg.findChild(SegmentedControl)
assert seg is not None and seg.value() == "jp"
dlg.server_changed.connect(picked.append)
seg.set_value("intl")
assert picked == ["intl"] and seg.value() == "intl"
seg.set_value("intl")
assert picked == ["intl"]
print("SERVER SEGMENT OK")

# 14) 速度卡片在默认内容宽度里放下「84.5 MB/s」，四张卡等宽
from PySide6.QtWidgets import QWidget, QHBoxLayout
from starmoe_ios.gui.widgets import StatTile
box = QWidget()
box.resize(698, 100)   # 960 窗口减去 210 侧栏和页边距
row = QHBoxLayout(box)
row.setContentsMargins(0, 0, 0, 0)
row.setSpacing(12)
cards = [StatTile("download", "已接收", "17.7 GB"), StatTile("json", "已保留游戏文件", "12 个"),
         StatTile("refresh", "速度", "84.5 MB/s"), StatTile("clock", "已用时间", "10:48")]
for c in cards:
    row.addWidget(c, 1)
box.show()
spin()
assert "MB/s" in cards[2].v.text(), cards[2].v.text()
widths = [c.width() for c in cards]
assert max(widths) - min(widths) <= 4, widths
print("STAT TILE OK", cards[2].v.text(), widths)

# 15) 防休眠调用成对出现
import starmoe_ios.power as power
marks = []
real_begin, real_end = power.begin, power.end
power.begin = lambda reason: marks.append(reason) or "tok"
power.end = lambda token: marks.append(token)
try:
    with power.StayAwake("extracting"):
        pass
finally:
    power.begin, power.end = real_begin, real_end
assert marks == ["extracting", "tok"], marks
print("STAY AWAKE OK")

# 16) 锁屏日志 → 醒目横幅；再次收到字节后收起。断线横幅同样在有新数据时收起。
import logging
from starmoe_ios.device import BackupStats, PasscodeLogHandler
st = BackupStats()
rec = logging.LogRecord("pymobiledevice3.services.mobilebackup2", logging.WARNING, __file__, 0,
                        "Please enter the device passcode to continue the backup", (), None)
PasscodeLogHandler(st).emit(rec)
assert st.passcode_needed
PasscodeLogHandler(st).emit(logging.LogRecord("pymobiledevice3.services.mobilebackup2", logging.WARNING,
                                              __file__, 0, "something else", (), None))
assert st.passcode_needed
page2 = ExtractPage()
page2.update_stats(99, 1000, 1, 0, 60, "transferring", now=2_000_000)
page2.set_passcode(True)
assert not page2.passcode.isHidden()
labels = [w.text() for w in page2.passcode.findChildren(type(page2.state))]
assert any("请解锁 iPhone 并输入锁屏密码，备份才会继续" in t for t in labels), labels
page2.set_retrying(1, 5)
assert not page2.retry.isHidden()
page2.update_stats(99, 1000 + 50_000, 1, 0, 61, "transferring", now=2_000_001)
assert page2.passcode.isHidden() and page2.retry.isHidden()
alerts = []
from starmoe_ios.gui.app import alert_passcode
real_alert = QApplication.alert
QApplication.alert = lambda *a, **k: alerts.append(a)
try:
    alert_passcode(page2, notify=lambda: alerts.append("notify"))
finally:
    QApplication.alert = real_alert
assert alerts and alerts[-1] == "notify"
print("PASSCODE BANNER OK")

# 17) 整理阶段的读超时不是断线
calls = []
w, ev, loop = run_worker(make_runner(["finalize_timeout", "ok"], calls))
finish(loop, w)
assert calls == ["finalize_timeout", "ok"] and ev["retrying"] == [] and ev["found"], (calls, ev)
print("FINALIZE WAIT OK")

# 18) 整理阶段 UI：条目数而不是 0 B/s；锁屏横幅在没有新字节时保留
page3 = ExtractPage()
page3.update_stats(99, 5000, 171, 0, 900, "finalizing", now=3_000_000, finalize_items=900_000)
assert page3.state.text() == "正在整理文件，请保持连接（不要拔线）"
assert page3.t_speed.v.text() == "900000 项"
assert page3.t_speed._title.text() == "已整理"
assert "B/s" not in page3.t_speed.v.text()
page3.set_passcode(True)
page3.update_stats(99, 5000, 171, 0, 901, "finalizing", now=3_000_001, finalize_items=900_100)
assert not page3.passcode.isHidden()
page3.update_stats(99, 5000 + 10, 171, 0, 902, "transferring", now=3_000_002)
assert page3.passcode.isHidden()
assert page3.t_speed._title.text() == "速度"
print("FINALIZE UI OK")

# 19) 不创建占位文件；move/remove 命中这些名字时不访问磁盘。Manifest 计数。
import asyncio, sqlite3
from pathlib import Path
from starmoe_ios.backupfast import placeholder_bypass
from starmoe_ios.device import count_target_entries, file_matches

class _BF:
    def __init__(self, **kw):
        self.device_name = kw.get("device_name")
        self.domain = kw.get("domain")
        self.relative_path = kw.get("relative_path")

doms = ["AppDomain-com.bilibili.sirius"]
assert file_matches(_BF(domain="AppDomain-com.bilibili.sirius", relative_path="Documents/a"), doms, [])
assert file_matches(_BF(device_name="AppDomain-com.bilibili.sirius-Documents/a"), doms, [])
assert not file_matches(_BF(domain="CameraRollDomain", relative_path="a"), doms, [])

class _DL:
    def __init__(self):
        self.moved = None
        self.removed = None
        self.status = None
    async def move_items(self, message):
        self.moved = message
    async def remove_items(self, message):
        self.removed = message
    async def status_response(self, code, *a, **k):
        self.status = code

st = type("S", (), {"phase": "", "finalize_items": 0})()
dl = _DL()
blob = "ab" * 20
real = Path(tempfile.mkdtemp()) / "Manifest.plist"
with placeholder_bypass(st, _DL):
    missing = Path(tempfile.mkdtemp()) / blob
    missing.touch()
    assert not missing.exists()
    real.touch()
    assert real.is_file()
    asyncio.run(dl.move_items(["DLMessageMoveItems", {blob: "UDID/" + blob}, None, 99]))
    assert dl.moved is None and dl.status == 0 and st.phase == "finalizing" and st.finalize_items == 1
    dl.status = None
    asyncio.run(dl.remove_items(["DLMessageRemoveItems", ["UDID/" + blob]]))
    assert dl.removed is None and dl.status == 0 and st.finalize_items == 2
    dl.status = None
    asyncio.run(dl.move_items(["DLMessageMoveItems", {"Info.plist": "UDID/Info.plist"}]))
    assert dl.moved is not None and dl.moved[1] == {"Info.plist": "UDID/Info.plist"}

dbdir = Path(tempfile.mkdtemp())
con = sqlite3.connect(dbdir / "Manifest.db")
con.execute("CREATE TABLE Files (fileID TEXT, domain TEXT, relativePath TEXT, flags INT, file BLOB)")
for i in range(171):
    con.execute("INSERT INTO Files VALUES (?,?,?,?,?)", (f"{i:040x}", "AppDomain-com.bilibili.sirius", f"d/{i}", 1, b""))
con.execute("INSERT INTO Files VALUES (?,?,?,?,?)", ("ff" * 20, "CameraRollDomain", "a", 1, b""))
con.commit(); con.close()
assert count_target_entries(dbdir, doms) == 171
print("PLACEHOLDER OK")

# 20) 11.43.1 上传时的 device_name，以及 Manifest 回调（device_name 为空）
UUID = "8E5C3A21-1111-4222-8333-444455556666"
container = f"/private/var/mobile/Containers/Data/Application/{UUID}/"
dom = "AppDomain-com.bilibili.sirius"
examples = [
    f"/var/mobile/Containers/Data/Application/{UUID}/Documents/x",
    f"/private/var/mobile/Containers/Data/Application/{UUID}/Documents/x/",
    f"{dom}-Documents/x",
    f"{dom}/Documents/x",
    f"AppDomainPlugin-com.bilibili.sirius.widget-Library/x",
]
for name in examples:
    assert file_matches(type("B", (), {"device_name": name, "domain": None, "relative_path": None})(),
                        [dom], [container], "com.bilibili.sirius"), name
# 只有 domain 的第二次调用（prune）
assert file_matches(type("B", (), {"device_name": None, "domain": dom, "relative_path": "Documents/x"})(),
                    [dom], [], "com.bilibili.sirius")
assert not file_matches(type("B", (), {"device_name": "/var/mobile/Media/DCIM/a.jpg", "domain": None,
                                       "relative_path": None})(), [dom], [container], "com.bilibili.sirius")
print("DEVICE NAME MATCH OK")

# 21) 备份结束但一个游戏文件都没留下 → 明确失败，不当成功
calls = []
w, ev, loop = run_worker(make_runner(["empty_ok"], calls))
finish(loop, w)
assert ev["failed"] == "ERR_NO_SAVE" and not ev["found"], ev
print("EMPTY CAPTURE OK")
print("GUI TESTS OK")
