"""CLI 与 GUI 共用的扫描、挑选、统计逻辑（不做任何 I/O 以外的副作用，不打印）。"""
import json, os, time
from . import backup as bk, savecodec
from .errors import StarMoeError, ERR_DECRYPT, ERR_NO_SAVE

SERVER_NAMES = {"intl": "国际服", "jp": "日服"}
BUNDLE_OF = {srv: bs[0] for srv, bs in bk.BUNDLES.items()}


def is_bk(path):
    return path.endswith("_bk")


def better(new_mtime, new_path, old):
    """新文件是否应替换旧记录：更新的 mtime 优先；mtime 相同时主文件优先于 _bk 备份副本。"""
    if old is None:
        return True
    if new_mtime != old["mtime"]:
        return new_mtime > old["mtime"]
    return is_bk(old["path"]) and not is_bk(new_path)


def order(paths):
    # 主文件排在 _bk 副本之前；若主文件已成功解出存档，就不必再全量解密 _bk（大存档纯 Python 解密较慢）
    return sorted(paths, key=lambda x: (x[:-3] if is_bk(x) else x, is_bk(x)))


class ScanResult(list):
    """list[save]，另带统计：magic_hits = 形似存档的文件数，failed = 其中解不开的数量。"""
    magic_hits = 0
    failed = 0


def _consider(codec, res, found, rel, mtime, data, srv, extra, done, log):
    if not codec.looks_like_save(data):
        return
    res.magic_hits += 1
    plain = codec.decrypt(data)
    if not plain:
        res.failed += 1
        log and log(f"无法解密 {rel}")
        return
    p = savecodec.extract_player(plain)
    if not p:
        log and log(f"{rel}: 解密成功但不含 _player（设置/界面状态文件）")
        return
    done.add(rel)
    k = (srv, p["account_id"])
    if better(mtime, rel, found.get(k)):
        found[k] = {**p, "server": srv, "path": rel, "mtime": mtime, "key_fp": codec.last_fp, **extra}


def scan_backup(codec, bak, servers, log=None):
    """在 iTunes/Finder 格式的备份（含 Manifest.db）中查找存档。"""
    res, found = ScanResult(), {}
    for srv in servers:
        for bundle in bk.BUNDLES[srv]:
            items = {rel: (mtime, data) for rel, mtime, data in bak.files(bundle)}
            done = set()
            for rel in order(items):
                if is_bk(rel) and rel[:-3] in done:
                    continue
                mtime, data = items[rel]
                _consider(codec, res, found, rel, mtime, data, srv, {"bundle": bundle}, done, log)
    res.extend(found.values())
    return res


def scan_folder(codec, roots, server="intl", log=None):
    """在普通文件夹（导出的容器文件树、过滤备份的哈希文件目录、单个文件）中按内容查找存档。"""
    res, found = ScanResult(), {}
    paths = []
    for f in roots:
        if os.path.isdir(f):
            for r, ds, ns in os.walk(f):
                ds[:] = [x for x in ds if x not in bk.SKIP]
                paths += [os.path.join(r, n) for n in ns]
        elif os.path.isfile(f):
            paths.append(f)
    done = set()
    for p in order(paths):
        if is_bk(p) and p[:-3] in done:
            continue
        try:
            if os.path.getsize(p) > bk.MAX_FILE:
                continue
            with open(p, "rb") as fh:
                if fh.read(32) != codec.magic:  # 先比对 magic，避免把大量无关文件读进内存
                    continue
                data = codec.magic + fh.read()
            mtime = os.path.getmtime(p)
        except OSError:
            continue
        _consider(codec, res, found, p, mtime, data, server, {"bundle": BUNDLE_OF.get(server)}, done, log)
    res.extend(found.values())
    return res


def _has_manifest(path):
    m = os.path.join(path, "Manifest.plist")
    return os.path.isfile(m) and os.path.getsize(m) > 0 and os.path.isfile(os.path.join(path, "Manifest.db"))


def scan_path(codec, path, server=None, password=None, log=None):
    """自动判断：完整的备份目录 → 读 Manifest；否则（导出的文件夹、中断/过滤的备份）→ 按内容扫描。

    没找到时抛出 StarMoeError（ERR_DECRYPT：有形似存档的文件但解不开；ERR_NO_SAVE：没有存档文件）。
    """
    res = ScanResult()
    if _has_manifest(path):
        bak = bk.Backup(path, password)
        res = scan_backup(codec, bak, [s for s in ("intl", "jp") if not server or s == server], log)
    if not res:
        r2 = scan_folder(codec, [path], server or "intl", log)
        r2.magic_hits += res.magic_hits
        r2.failed += res.failed
        res = r2
    if not res:
        raise_not_found(res)
    return res


def raise_not_found(res):
    if res.failed:
        raise StarMoeError(ERR_DECRYPT, f"找到 {res.failed} 个存档文件，但用当前密钥都解不开。游戏更新后密钥可能已变，"
                                        "请下载最新版官方 StarMoe Box APK 重新加载密钥，或手动指定密钥文件。")
    raise StarMoeError(ERR_NO_SAVE, "没有找到游戏存档：请确认所选服务器正确、游戏已登录过，"
                                    "以及所选文件夹/备份包含 Documents/<十六进制>/ 下的文件。")


STAT_KEYS = {"member_cards": "_memberCards", "support_cards": "_supportCards",
             "characters": "_characters", "decks": "_decks", "items": "_items", "live_musics": "_liveMusics"}


def player_stats(save):
    """从切出的 _player 原文统计卡牌/角色等数量（只读，不改原文）。"""
    p = json.loads(save["bytes"])
    out = {k: len(p.get(v) or []) for k, v in STAT_KEYS.items()}
    out.update(name=p.get("_name") or "", profile_id=str(p.get("_profileId", "")), exp=p.get("_exp"),
               size=len(save["bytes"]), server=save.get("server"), mtime=save.get("mtime"),
               key_fp=save.get("key_fp"), path=save.get("path"))
    return out


def write_player(save, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    fn = os.path.join(out_dir, f"{save['server']}_{save['account_id']}_player.json")
    with open(fn, "wb") as f:
        f.write(save["bytes"])
    return fn


def format_id(pid):
    """2151 7519 960 —— 每 4 位一组，方便核对。"""
    return " ".join(pid[i:i + 4] for i in range(0, len(pid), 4))


def format_time(ts):
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts)) if ts else "—"
