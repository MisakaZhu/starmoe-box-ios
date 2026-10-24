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
print("GUI TESTS OK")
