"""keyfetch / winsupport 离线测试（不访问网络）。运行：python tests/test_keyfetch.py"""
import hashlib, io, json, os, sys, tempfile, urllib.error
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from starmoe_ios import keyfetch as K, winsupport
from starmoe_ios.errors import StarMoeError, ERR_KEYS, ERR_NETWORK

APK = b"PK\x03\x04" + os.urandom(300_000)
SHA = hashlib.sha256(APK).hexdigest()
DL = K.DOWNLOAD_PREFIX + "v9.9.9/app-release.apk"


class Resp(io.BytesIO):
    def __init__(self, url, body, status=200, headers=None):
        super().__init__(body)
        self.url, self.status = url, status
        self.headers = {"Content-Length": str(len(body)), **(headers or {})}

    def geturl(self):
        return self.url


def release(digest=SHA, url="https://api.github.com/repos/StarMoe-org/StarMoe-box/releases/1", dl=DL, tag="v9.9.9"):
    return json.dumps({"url": url, "tag_name": tag, "assets": [{"name": "app-release.apk", "browser_download_url": dl,
                                                                "size": len(APK), "digest": digest and "sha256:" + digest}]}).encode()


class Net:
    """按 URL 返回预设响应；值可以是 bytes / Exception / callable(req)。"""
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def open(self, req, timeout=None):
        url = req.full_url
        self.calls.append((url, dict(req.header_items())))
        v = self.routes.get(url)
        if callable(v):
            v = v(req)
        if v is None:
            raise urllib.error.URLError("no route " + url)
        if isinstance(v, Exception):
            raise v
        return v if isinstance(v, Resp) else Resp(url, v)


def run(routes, base=None, **kw):
    net = Net(routes)
    K._opener = net
    base = base or tempfile.mkdtemp()
    return K.fetch_apk(base, sleep=lambda s: None, **kw), net, base


ok = 0
# 1) 正常：查询 → 下载 → 校验 → 缓存
(meta, fresh), net, base = run({K.API_LATEST: release(), DL: APK})
assert fresh and meta["tag"] == "v9.9.9" and meta["sha256"] == SHA and open(meta["path"], "rb").read() == APK
assert K.cached(base)["path"] == meta["path"]
ok += 1
# 2) 已是最新：不重复下载
(meta2, fresh2), net, _ = run({K.API_LATEST: release(), DL: AssertionError("should not download")}, base=base)
assert not fresh2 and meta2["path"] == meta["path"]
ok += 1
# 3) 摘要不一致：删除并报错
try:
    run({K.API_LATEST: release(digest="0" * 64), DL: APK})
    raise SystemExit("digest mismatch not detected")
except StarMoeError as e:
    assert e.code == ERR_KEYS
ok += 1
# 4) Release 不属于官方仓库 / 下载地址不属于官方仓库
for bad in (release(url="https://api.github.com/repos/evil/fork/releases/1"),
            release(dl="https://github.com/evil/fork/releases/download/v1/app-release.apk")):
    try:
        run({K.API_LATEST: bad})
        raise SystemExit("foreign repo accepted")
    except StarMoeError as e:
        assert e.code == ERR_KEYS
ok += 1
# 5) 非 GitHub 主机 / 非 https 一律拒绝（含重定向目标）
for u in ("https://evil.example.com/a.apk", "http://github.com/x", "https://github.com.evil.cn/x"):
    try:
        K._check_url(u)
        raise SystemExit("bad url accepted: " + u)
    except StarMoeError:
        pass
K._check_url("https://release-assets.githubusercontent.com/x")
try:
    K._SafeRedirect().redirect_request(None, None, 302, "", {}, "https://mirror.example.cn/app-release.apk")
    raise SystemExit("redirect to mirror accepted")
except StarMoeError:
    pass
ok += 1
# 6) API 不可用（限流/被墙）→ 走官方直链
(meta, fresh), net, _ = run({K.API_LATEST: urllib.error.URLError("timeout"), K.DIRECT_LATEST: APK}, retries=2)
assert fresh and meta["tag"] == "latest" and meta["sha256"] == SHA
assert sum(1 for u, _ in net.calls if u == K.API_LATEST) == 2
ok += 1
# 7) 全部失败 → 有缓存用缓存，没缓存报网络错误（提示手动选择）
(meta, fresh), net, _ = run({}, base=base, retries=2)
assert not fresh and meta["path"] == K.cached(base)["path"]
try:
    run({}, retries=2)
    raise SystemExit("no error without cache")
except StarMoeError as e:
    assert e.code == ERR_NETWORK and "手动选择" in e.message
ok += 1
# 8) 断点续传：.part 存在时带 Range，206 续写
base = tempfile.mkdtemp()
part = os.path.join(K.cache_dir(base), "StarMoe-box-v9.9.9.apk.part")
open(part, "wb").write(APK[:100_000])
(meta, fresh), net, _ = run({K.API_LATEST: release(), DL: lambda req: Resp(DL, APK[100_000:], 206)}, base=base)
assert dict(net.calls[-1][1]).get("Range") == "bytes=100000-" and meta["sha256"] == SHA
ok += 1
# 9) 发现新版本 → 下载并清理旧版
APK2 = APK + b"new"
SHA2 = hashlib.sha256(APK2).hexdigest()
DL2 = K.DOWNLOAD_PREFIX + "v10/app-release.apk"
(meta3, fresh3), net, _ = run({K.API_LATEST: release(digest=SHA2, dl=DL2, tag="v10"), DL2: APK2}, base=base)
assert fresh3 and meta3["tag"] == "v10" and not os.path.exists(meta["path"])
ok += 1
# 10) winsupport：非 Windows 平台不需要检查
assert winsupport.check(platform="darwin")["state"] == "n/a" and winsupport.check(platform="linux")["ok"]
ok += 1
print(f"KEYFETCH OK ({ok} cases)")
