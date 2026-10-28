"""自动获取密钥来源：从 GitHub 下载官方 StarMoe Box 安卓版的发布包（app-release.apk）。

- 只从 github.com/StarMoe-org/StarMoe-box 的 Release 下载；所有跳转都必须是 HTTPS 且落在 GitHub 自己的域名上；
  如果 GitHub API 给出了文件的 sha256 摘要，下载后逐字节核对。
- 不使用任何第三方镜像。网络不好时：重试（支持断点续传）→ 退回到 releases/latest/download 直链 → 使用本地缓存 →
  交给用户手动选择 APK。
- 下载的 APK 缓存在应用数据目录；密钥依旧在运行时从 APK 中解出，不写入磁盘。
"""
import hashlib, json, logging, os, time, urllib.error, urllib.parse, urllib.request
from .errors import StarMoeError, ERR_NETWORK, ERR_KEYS
from .tls import build_opener

log = logging.getLogger("starmoe.keyfetch")
REPO = "StarMoe-org/StarMoe-box"
ASSET = "app-release.apk"
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
DIRECT_LATEST = f"https://github.com/{REPO}/releases/latest/download/{ASSET}"
DOWNLOAD_PREFIX = f"https://github.com/{REPO}/releases/download/"
ALLOWED_HOSTS = {"github.com", "api.github.com", "objects.githubusercontent.com",
                 "release-assets.githubusercontent.com", "github-releases.githubusercontent.com"}
MAX_SIZE = 64 * 1024 * 1024
UA = "StarMoeBox-iOS-desktop (+https://github.com/MisakaZhu/starmoe-box-ios)"


class Cancelled(Exception):
    pass


def _check_url(url):
    p = urllib.parse.urlsplit(url)
    if p.scheme != "https" or (p.hostname or "").lower() not in ALLOWED_HOSTS:
        raise StarMoeError(ERR_KEYS, "下载地址不是 GitHub 官方地址，已拒绝。", url)


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = build_opener(_SafeRedirect)   # HTTPS 使用系统证书库或 certifi；仍走系统/环境变量里的代理


def _open(url, timeout, headers=None):
    _check_url(url)
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    r = _opener.open(req, timeout=timeout)
    _check_url(r.geturl())
    return r


def latest_release(timeout=15):
    """查询最新 Release。返回 {tag, url, size, sha256(可能为 None), published}。"""
    with _open(API_LATEST, timeout, {"Accept": "application/vnd.github+json"}) as r:
        d = json.load(r)
    if not str(d.get("url", "")).startswith(f"https://api.github.com/repos/{REPO}/releases/"):
        raise StarMoeError(ERR_KEYS, "GitHub 返回的 Release 不属于官方仓库。", d.get("url"))
    for a in d.get("assets", []):
        if a.get("name") == ASSET:
            url = a["browser_download_url"]
            if not url.startswith(DOWNLOAD_PREFIX):
                raise StarMoeError(ERR_KEYS, "安装包地址不属于官方仓库。", url)
            dg = a.get("digest") or ""
            return {"tag": d.get("tag_name") or "latest", "url": url, "size": a.get("size"),
                    "sha256": dg[7:].lower() if dg.startswith("sha256:") else None, "published": d.get("published_at")}
    raise StarMoeError(ERR_KEYS, f"最新版官方 StarMoe Box Release 中没有 {ASSET}。", d.get("html_url"))


def cache_dir(base):
    d = os.path.join(base, "keysource")
    os.makedirs(d, exist_ok=True)
    return d


def cached(base):
    """返回本地缓存 {path, tag, sha256, fetched_at} 或 None。"""
    try:
        meta = json.load(open(os.path.join(cache_dir(base), "meta.json"), encoding="utf-8"))
        if os.path.isfile(meta["path"]):
            return meta
    except (OSError, ValueError, KeyError):
        pass
    return None


def _download(url, dest, size_hint, progress, cancel, timeout):
    """下载到 dest（.part 断点续传）。progress(done, total)。"""
    part = dest + ".part"
    have = os.path.getsize(part) if os.path.exists(part) else 0
    headers = {"Range": f"bytes={have}-"} if have else {}
    try:
        r = _open(url, timeout, headers)
    except urllib.error.HTTPError as e:
        if e.code == 416:   # 已经下完
            os.replace(part, dest)
            return
        raise
    with r:
        if have and r.status != 206:
            have = 0
        total = int(r.headers.get("Content-Length") or 0) + have or size_hint or 0
        if total > MAX_SIZE:
            raise StarMoeError(ERR_KEYS, "文件大小异常，已停止下载。", str(total))
        with open(part, "ab" if have else "wb") as f:
            done = have
            while True:
                if cancel and cancel():
                    raise Cancelled()
                chunk = r.read(64 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if done > MAX_SIZE:
                    raise StarMoeError(ERR_KEYS, "文件大小异常，已停止下载。")
                if progress:
                    progress(done, total)
    os.replace(part, dest)


def fetch_apk(base, progress=None, cancel=None, retries=3, force=False, status=None, timeout=20, sleep=time.sleep):
    """确保本地有最新的官方 APK。返回 (meta, fresh)。fresh=True 表示本次新下载。

    force=True：即使缓存已是最新也重新下载（一般不需要，校验失败时用）。"""
    status = status or (lambda m: log.info(m))
    cdir = cache_dir(base)
    old = cached(base)
    info, last_err = None, None
    for i in range(retries):
        try:
            status("正在查询最新版本…")
            info = latest_release(timeout)
            break
        except StarMoeError:
            raise
        except (OSError, ValueError) as e:   # URLError / 超时 / 限流 / JSON 错误
            last_err = e
            log.warning("查询 GitHub Release 失败（第 %d 次）：%r", i + 1, e)
            if cancel and cancel():
                raise Cancelled()
            if i + 1 < retries:
                sleep(2 * (i + 1))
    if info and old and old.get("tag") == info["tag"] and not force and \
            (not info["sha256"] or old.get("sha256") == info["sha256"]):
        status(f"已是最新版本 {info['tag']}")
        return old, False
    url = info["url"] if info else DIRECT_LATEST
    tag = info["tag"] if info else "latest"
    dest = os.path.join(cdir, f"StarMoe-box-{tag}.apk")
    for i in range(retries):
        try:
            status(f"正在下载官方安装包 {tag}…" + (f"（重试 {i}）" if i else ""))
            _download(url, dest, info and info.get("size"), progress, cancel, timeout)
            break
        except (Cancelled, StarMoeError):
            raise
        except (OSError, ValueError) as e:
            last_err = e
            log.warning("下载失败（第 %d 次）：%r", i + 1, e)
            if cancel and cancel():
                raise Cancelled()
            if i + 1 < retries:
                sleep(2 * (i + 1))
    else:
        if old:
            status("网络不可用，使用之前下载的版本")
            return old, False
        raise StarMoeError(ERR_NETWORK, "无法连接 GitHub 下载官方安装包。请检查网络（可稍后重试），"
                                        "或手动选择已下载好的官方 StarMoe Box APK。", repr(last_err))
    h = hashlib.sha256(open(dest, "rb").read()).hexdigest()
    if info and info["sha256"] and h != info["sha256"]:
        os.remove(dest)
        raise StarMoeError(ERR_KEYS, "下载的文件校验失败（sha256 不一致），已删除。请重试。", h)
    fresh = not (old and old.get("sha256") == h)   # 内容与旧缓存一致（例如只是 API 不可用走了直链）就不算更新
    meta = {"path": dest, "tag": tag if not (tag == "latest" and not fresh) else old.get("tag", tag), "sha256": h,
            "fetched_at": int(time.time()), "source": url}
    with open(os.path.join(cdir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    for n in os.listdir(cdir):   # 清理旧版本
        p = os.path.join(cdir, n)
        if n.endswith(".apk") and p != dest:
            try:
                os.remove(p)
            except OSError:
                pass
    status(f"已下载 {meta['tag']}")
    return meta, fresh
