"""python -m tests.test_all —— 用随机测试密钥构造假存档与假备份，端到端验证。"""
import hashlib, json, os, plistlib, sqlite3, sys, tempfile, time
from starmoe_ios.savecodec import Codec, extract_player, json_member
from starmoe_ios.rijndael import Rijndael256
from starmoe_ios import cli

key, magic, iv = os.urandom(32), os.urandom(32), os.urandom(32)
save = b'{"_version":3, "_player": {"_profileId": 123456789, "_name": "\\u82b1", "_cards":[{"id":1,"s":"a}"}]}, "_other": 1.50}'
pad = 32 - len(save) % 32
blob = magic + iv + Rijndael256(key).encrypt_cbc(save + bytes([pad]) * pad, iv)
c = Codec(magic, [os.urandom(32), key])
plain = c.decrypt(blob); assert plain == save
p = extract_player(plain); assert p["account_id"] == "123456789"
assert p["bytes"] == b'{"_profileId": 123456789, "_name": "\\u82b1", "_cards":[{"id":1,"s":"a}"}]}'
assert json_member(save, "_other") == b"1.50"

# 伪造未加密备份
d = tempfile.mkdtemp()
rel = "Documents/0123456789abcdef0123/save.bin"
fid = hashlib.sha1(b"AppDomain-com.bilibili.sirius-" + rel.encode()).hexdigest()
os.makedirs(os.path.join(d, fid[:2])); open(os.path.join(d, fid[:2], fid), "wb").write(blob)
plistlib.dump({"IsEncrypted": False, "Applications": {"com.bilibili.sirius": {}}}, open(os.path.join(d, "Manifest.plist"), "wb"))
from plistlib import UID
fp = plistlib.dumps({"$top": {"root": UID(1)}, "$objects": ["$null", {"Size": len(blob), "LastModified": int(time.time()), "ProtectionClass": 3}]}, fmt=plistlib.FMT_BINARY)
con = sqlite3.connect(os.path.join(d, "Manifest.db"))
con.execute("CREATE TABLE Files (fileID TEXT, domain TEXT, relativePath TEXT, flags INT, file BLOB)")
con.execute("INSERT INTO Files VALUES (?,?,?,?,?)", (fid, "AppDomain-com.bilibili.sirius", rel, 1, fp)); con.commit()
kf = os.path.join(d, "k.json"); json.dump({"key": key.hex(), "magic": magic.hex()}, open(kf, "w"))
out = os.path.join(d, "out")
cli.main(["scan", "--backup", d, "--keys", kf, "--out", out])
assert open(os.path.join(out, "intl_123456789_player.json"), "rb").read() == p["bytes"]
print("ALL OK")

# 普通文件夹（例如拷出来的 AppDomain-com.bilibili.sirius 树），含要跳过的缓存目录
f = tempfile.mkdtemp()
os.makedirs(os.path.join(f, "AppDomain-com.bilibili.sirius/Documents/abcdef0123456789abcd"))
os.makedirs(os.path.join(f, "AppDomain-com.bilibili.sirius/Documents/EncryptedBundles"))
open(os.path.join(f, "AppDomain-com.bilibili.sirius/Documents/abcdef0123456789abcd/x"), "wb").write(blob)
open(os.path.join(f, "AppDomain-com.bilibili.sirius/Documents/EncryptedBundles/y"), "wb").write(blob)
out2 = os.path.join(f, "out")
cli.main(["scan", "--backup", f, "--keys", kf, "--out", out2])
cli.main(["scan", "--file", f, "--keys", kf, "--out", out2])
assert open(os.path.join(out2, "intl_123456789_player.json"), "rb").read() == p["bytes"]
print("FOLDER OK")

# 真机实测布局：Documents/<64hex>/<64hex> 与同名 _bk 副本，mtime 相同 -> 应选主文件
from starmoe_ios.cli import _order, _better
assert _order(["a/x_bk", "a/x", "a/w"]) == ["a/w", "a/x", "a/x_bk"]
assert _better(5, "a/x", {"mtime": 5, "path": "a/x_bk"}) and not _better(5, "a/x_bk", {"mtime": 5, "path": "a/x"})
assert _better(6, "a/x_bk", {"mtime": 5, "path": "a/x"})
g = tempfile.mkdtemp(); acc = os.path.join(g, "Documents", "ab" * 32); os.makedirs(acc)
for n in ("cd" * 32, "cd" * 32 + "_bk"):
    open(os.path.join(acc, n), "wb").write(blob); os.utime(os.path.join(acc, n), (1e9, 1e9))
import io, contextlib
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    cli.main(["scan", "--backup", g, "--keys", kf, "--out", os.path.join(g, "out")])
assert "_bk" not in buf.getvalue(), buf.getvalue()
print("BK OK")
