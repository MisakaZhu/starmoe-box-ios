"""读取 iTunes/Finder 备份（加密或未加密），列出游戏 App 容器内的文件。"""
import os, plistlib, sqlite3
from .errors import StarMoeError, ERR_PASSWORD

BUNDLES = {"intl": ["com.bilibili.sirius"], "jp": ["com.bushiroad.sirius"]}
SKIP = {"EncryptedBundles", "Addressables", "Master", "RemoteCatalog", "il2cpp", "Unity", "UnityCache",
        "cache", "Caches", "tmp", "com.unity3d.player"}
MAX_FILE = 16 << 20


def default_backup_roots():
    home = os.path.expanduser("~")
    c = [os.path.join(home, "Library/Application Support/MobileSync/Backup"),
         os.path.join(os.environ.get("APPDATA", ""), "Apple Computer/MobileSync/Backup"),
         os.path.join(home, "Apple/MobileSync/Backup"),  # Microsoft Store 版 iTunes
         os.path.join(os.environ.get("USERPROFILE", home), "Apple/MobileSync/Backup")]
    out = []
    for r in c:
        if os.path.isdir(r):
            out += [os.path.join(r, d) for d in os.listdir(r) if os.path.isfile(os.path.join(r, d, "Manifest.plist"))]
    return out


def _skip(path):
    return any(p in SKIP for p in path.split("/"))


class Backup:
    def __init__(self, path, password=None):
        self.path = path
        self.manifest = plistlib.load(open(os.path.join(path, "Manifest.plist"), "rb"))
        self.encrypted = bool(self.manifest.get("IsEncrypted"))
        if self.encrypted:
            if not password:
                raise StarMoeError(ERR_PASSWORD, "该备份已加密，需要提供备份密码（--password / 密码输入框）")
            from iphone_backup_decrypt import EncryptedBackup
            self.eb = EncryptedBackup(backup_directory=path, passphrase=password)
            try:
                self.eb._read_and_unlock_keybag()
            except Exception as e:  # 密码错误时 keybag 解锁失败
                raise StarMoeError(ERR_PASSWORD, "备份密码不正确，无法解开加密备份。", repr(e))

    def installed(self):
        apps = self.manifest.get("Applications", {}) or {}
        return {srv: [b for b in bs if b in apps] for srv, bs in BUNDLES.items()}

    def _rows(self, domain):
        if self.encrypted:
            for fid, dom, rel, fp in self.eb._get_manifest_rows_generator(domain_like=domain):
                yield fid, rel, fp.filesize, fp.mtime, fp
        else:
            con = sqlite3.connect(os.path.join(self.path, "Manifest.db"))
            for fid, rel, flags, blob in con.execute(
                    "SELECT fileID, relativePath, flags, file FROM Files WHERE domain=? AND flags=1", (domain,)):
                p = plistlib.loads(blob)
                o = p["$objects"][p["$top"]["root"].data]
                yield fid, rel, o.get("Size", 0), o.get("LastModified", 0), None

    def files(self, bundle):
        """遍历 AppDomain-<bundle> 中的小文件 (rel_path, mtime, bytes)。"""
        for fid, rel, size, mtime, fp in self._rows("AppDomain-" + bundle):
            if not rel or _skip(rel) or not size or size > MAX_FILE:
                continue
            if self.encrypted:
                if fp is None or fp.encryption_key is None:
                    continue
                try:
                    data = self._dec(fid, fp)
                except FileNotFoundError:
                    continue
            else:
                f = os.path.join(self.path, fid[:2], fid)
                if not os.path.exists(f):
                    f = os.path.join(self.path, fid)
                if not os.path.exists(f):  # 过滤备份/中断的备份里可能缺文件
                    continue
                data = open(f, "rb").read()
            yield rel, mtime or 0, data

    def _dec(self, fid, fp):
        from iphone_backup_decrypt import utils
        self.eb._read_and_unlock_keybag()
        key = self.eb.keybag.unwrap_key_for_class(fp.protection_class, fp.encryption_key)
        raw = open(utils.backup_file_path(self.eb._backup_directory, fid), "rb").read()
        return utils.remove_cbc_padding(utils.aes_decrypt_cbc(data=raw, key=key))[: fp.filesize]

    def all_paths(self, bundle):
        for fid, rel, size, mtime, fp in self._rows("AppDomain-" + bundle):
            yield rel, size
