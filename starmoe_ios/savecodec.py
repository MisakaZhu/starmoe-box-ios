"""Our Notes 存档格式：magic[32] ‖ iv[32] ‖ Rijndael-256-CBC(key, iv, PKCS#7(json))。

密钥与 magic 不写在本仓库里。来源（任选其一）：
  1. 环境变量 OURNOTES_SAVE_KEY / OURNOTES_SAVE_MAGIC（64 位十六进制）
  2. --keys keys.json  {"key": "...", "magic": "..."}
  3. --from-apk StarMoe-Box 官方 APK：按其 BuildConfig 的 XOR 混淆规则在运行时解出候选值
"""
import json, os, re, zipfile
from .rijndael import Rijndael256, BLOCK
from .errors import StarMoeError, ERR_KEYS

HEADER = 64
_ACCOUNT = re.compile(r"^[1-9][0-9]{0,18}$")


def _xor_decode(enc: str) -> bytes:
    return bytes(int(enc[2 * i:2 * i + 2], 16) ^ ((i * 17 + 93) & 0xFF) for i in range(32))


def candidates_from_apk(apk_path):
    """返回 APK 中所有可能的 32 字节常量（已按 StarMoe Box 规则去混淆）。"""
    out = []
    with zipfile.ZipFile(apk_path) as z:
        for n in z.namelist():
            if n.startswith("classes") and n.endswith(".dex"):
                for m in re.finditer(rb"(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])", z.read(n)):
                    b = _xor_decode(m.group().decode())
                    if b not in out:
                        out.append(b)
    return out


class Codec:
    def __init__(self, magic: bytes, keys):
        self.magic = magic
        import hashlib
        self.ciphers = [Rijndael256(k) for k in keys]
        self.fps = [f"候选#{i + 1} sha256:{hashlib.sha256(k).hexdigest()[:8]}" for i, k in enumerate(keys)]
        self.last_fp = None
        self.source = (None, None)

    @classmethod
    def load(cls, keys_file=None, apk=None):
        """按 密钥文件 > 环境变量 > APK 的顺序加载。返回的 Codec.source 说明来源（不含密钥本身）。"""
        k, m = os.environ.get("OURNOTES_SAVE_KEY"), os.environ.get("OURNOTES_SAVE_MAGIC")
        src = ("env", None)
        if keys_file:
            try:
                d = json.load(open(keys_file, encoding="utf-8"))
                k, m = d["key"], d["magic"]
            except (OSError, ValueError, KeyError, TypeError) as e:
                raise StarMoeError(ERR_KEYS, "密钥文件无法读取：需要 JSON {\"key\": \"<64位hex>\", \"magic\": \"<64位hex>\"}", repr(e))
            src = ("keys", keys_file)
        if k and m:
            try:
                c = cls(bytes.fromhex(m), [bytes.fromhex(k)])
            except ValueError as e:
                raise StarMoeError(ERR_KEYS, "密钥格式不正确（应为 64 位十六进制）", repr(e))
            c.source = src
            return c
        if apk:
            try:
                cands = candidates_from_apk(apk)
            except (OSError, zipfile.BadZipFile) as e:
                raise StarMoeError(ERR_KEYS, "无法读取所选文件：请选择官方 StarMoe Box 的 .apk 文件", repr(e))
            # 已知 magic 以 b50b23a5 开头、以 10b8e30 结尾（README 公开的指纹）
            magic = next((x for x in cands if x.hex().startswith("b50b23a5") and x.hex().endswith("10b8e30")), None)
            if not magic:
                raise StarMoeError(ERR_KEYS, "所选 APK 中没有找到存档 magic：请确认是官方 StarMoe Box APK，或游戏/工具版本已变化。")
            c = cls(magic, [x for x in cands if x != magic])
            c.source = ("apk", apk)
            return c
        raise StarMoeError(ERR_KEYS, "缺少存档密钥：请设置环境变量、--keys 或 --from-apk")

    def looks_like_save(self, b):
        return len(b) >= HEADER + BLOCK and (len(b) - HEADER) % BLOCK == 0 and b[:32] == self.magic

    def decrypt(self, b):
        if not self.looks_like_save(b):
            return None
        iv, body = b[32:64], b[64:]
        for c, fp in zip(self.ciphers, self.fps):
            # 先解第一块判断是否像 JSON，避免对错误密钥全量解密
            if c.decrypt_cbc(body[:BLOCK], iv).lstrip()[:1] not in (b"{", b"["):
                continue
            p = c.decrypt_cbc(body, iv)
            n = p[-1]
            if 0 < n <= BLOCK and p[-n:] == bytes([n]) * n:
                self.last_fp = fp
                return p[:-n]
        return None


def json_member(text: bytes, name: str):
    """从顶层 JSON 对象中按字节原样切出成员值（等价于 JsonSlice.kt）。"""
    i, n = 0, len(text)

    def ws(i):
        while i < n and text[i] in b" \t\r\n":
            i += 1
        return i

    def skip_str(i):
        i += 1
        while text[i] != 0x22:
            i += 2 if text[i] == 0x5C else 1
        return i + 1

    def skip_val(i):
        c = text[i]
        if c == 0x22:
            return skip_str(i)
        if c in b"{[":
            depth = 0
            while True:
                c = text[i]
                if c == 0x22:
                    i = skip_str(i); continue
                if c in b"{[":
                    depth += 1
                elif c in b"}]":
                    depth -= 1
                    if depth == 0:
                        return i + 1
                i += 1
        while i < n and text[i] not in b",}] \t\r\n":
            i += 1
        return i

    i = ws(i)
    if i >= n or text[i] != 0x7B:
        return None
    i = ws(i + 1)
    key = json.dumps(name).encode()
    while i < n and text[i] != 0x7D:
        s = i; i = skip_str(i); k = text[s:i]
        i = ws(i); i = ws(i + 1)  # ':'
        v0 = i; i = skip_val(i)
        if json.loads(k) == name:
            return text[v0:i]
        i = ws(i)
        if i < n and text[i] == 0x2C:
            i = ws(i + 1)
    return None


def extract_player(plain: bytes):
    raw = json_member(plain, "_player")
    if not raw or raw[:1] != b"{":
        return None
    try:
        p = json.loads(raw)
    except ValueError:
        return None
    acc = str(p.get("_profileId", "")).strip()
    if not _ACCOUNT.match(acc) or (len(acc) == 19 and acc > "9223372036854775807"):
        return None
    return {"account_id": acc, "name": p.get("_name"), "bytes": raw}
