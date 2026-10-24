"""令牌存储（系统钥匙串 / Windows 凭据管理器，经 keyring）、自动刷新、URL Scheme 注册。

令牌绝不写入普通文件或日志。keyring 不可用时只保存在内存中（重启后需重新登录）。
"""
import json, logging, os, sys, time
from .. import api
from ..errors import StarMoeError, ERR_AUTH_EXPIRED

log = logging.getLogger("starmoe.auth")
SERVICE = "StarMoeBox-iOS"
# Windows 凭据管理器单条上限约 2.5KB，所以分条保存
_FIELDS = ("access_token", "refresh_token", "id_token")


class TokenStore:
    def __init__(self, backend=None):
        self._mem = None
        self.kr = backend
        if self.kr is None:
            try:
                import keyring
                from keyring.backends import fail
                kb = keyring.get_keyring()
                self.kr = None if isinstance(kb, fail.Keyring) else keyring
            except Exception as e:  # keyring 未安装/无后端
                log.warning("keyring 不可用：%r", e)
                self.kr = None

    @property
    def persistent(self):
        return self.kr is not None and self.kr is not False

    def load(self):
        if self._mem is not None:
            return dict(self._mem)
        if not self.persistent:
            return None
        try:
            meta = self.kr.get_password(SERVICE, "meta")
            if not meta:
                return None
            tok = json.loads(meta)
            for f in _FIELDS:
                v = self.kr.get_password(SERVICE, f)
                if v:
                    tok[f] = v
            self._mem = tok
            return dict(tok)
        except Exception as e:
            log.warning("读取钥匙串失败：%r", e)
            return None

    def save(self, tok):
        self._mem = dict(tok)
        if not self.persistent:
            return
        meta = {k: v for k, v in tok.items() if k not in _FIELDS}
        try:
            for f in _FIELDS:
                if tok.get(f):
                    self.kr.set_password(SERVICE, f, tok[f])
                else:
                    self._del(f)
            self.kr.set_password(SERVICE, "meta", json.dumps(meta))
        except Exception as e:
            log.warning("写入钥匙串失败（令牌仅保存在内存中）：%r", e)

    def _del(self, f):
        try:
            self.kr.delete_password(SERVICE, f)
        except Exception:
            pass

    def clear(self):
        self._mem = None
        if self.persistent:
            for f in _FIELDS + ("meta",):
                self._del(f)

    def claims(self):
        t = self.load()
        return api.id_claims(t) if t else {}

    def access_token(self, refresh_fn=api.refresh, skew=60):
        """返回可用的 access token；快过期时用 refresh token 刷新（Logto 会轮换 refresh token，需回写）。"""
        t = self.load()
        if not t or not t.get("access_token"):
            raise StarMoeError(ERR_AUTH_EXPIRED, "尚未登录。")
        if t.get("expires_at", 0) - skew > time.time():
            return t["access_token"]
        return self.force_refresh(refresh_fn)

    def force_refresh(self, refresh_fn=api.refresh):
        t = self.load() or {}
        if not t.get("refresh_token"):
            raise StarMoeError(ERR_AUTH_EXPIRED, "登录已过期，请重新登录。")
        new = refresh_fn(t["refresh_token"])
        new.setdefault("refresh_token", t["refresh_token"])
        new.setdefault("id_token", t.get("id_token"))
        self.save(new)
        return new["access_token"]


# ---- URL Scheme：moe.starmoe.box:// ------------------------------------------------------

def launch_command():
    """当前程序的启动命令（注册 URL 处理器用）。打包后是 exe 本身；源码运行时是 python + 入口脚本。"""
    if getattr(sys, "frozen", False):
        return [sys.executable]
    entry = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                         "packaging", "entry.py")
    exe = sys.executable
    if sys.platform == "win32" and exe.lower().endswith("python.exe"):
        w = exe[:-10] + "pythonw.exe"
        exe = w if os.path.exists(w) else exe
    return [exe, entry]


def register_url_scheme():
    """注册 moe.starmoe.box:// → 本程序。返回说明文字。

    - macOS：由打包后 .app 的 Info.plist（CFBundleURLTypes）声明，系统在首次启动 .app 时登记；源码运行无效。
    - Windows：写 HKCU\\Software\\Classes\\moe.starmoe.box（无需管理员）。
    - Linux：写 ~/.local/share/applications/*.desktop 并 xdg-mime default。
    """
    scheme = api.SCHEME
    cmd = launch_command()
    if sys.platform == "win32":
        import winreg
        q = " ".join(f'"{c}"' for c in cmd) + ' "%1"'
        base = rf"Software\Classes\{scheme}"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, base) as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, "URL:StarMoe Box (iOS)")
            winreg.SetValueEx(k, "URL Protocol", 0, winreg.REG_SZ, "")
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, base + r"\DefaultIcon") as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, f'"{cmd[0]}",0')
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, base + r"\shell\open\command") as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, q)
        return "已在当前用户注册 moe.starmoe.box:// 处理器"
    if sys.platform.startswith("linux"):
        import shlex, subprocess
        d = os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"), "applications")
        os.makedirs(d, exist_ok=True)
        name = "starmoe-box-ios.desktop"
        with open(os.path.join(d, name), "w", encoding="utf-8") as f:
            f.write("[Desktop Entry]\nType=Application\nName=StarMoe Box (iOS)\nNoDisplay=true\n"
                    f"Exec={' '.join(shlex.quote(c) for c in cmd)} %u\nMimeType=x-scheme-handler/{scheme};\n")
        try:
            subprocess.run(["xdg-mime", "default", name, f"x-scheme-handler/{scheme}"], timeout=10, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return "已写入 .desktop，但 xdg-mime 不可用"
        return "已通过 xdg-mime 注册 moe.starmoe.box:// 处理器"
    if sys.platform == "darwin" and not getattr(sys, "frozen", False):
        return "源码运行时 macOS 无法接收 moe.starmoe.box:// 回调，请使用粘贴回调地址的方式（打包后的 .app 会自动接收）"
    return "由 Info.plist 注册"
