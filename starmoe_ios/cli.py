import argparse, json, os, sys
from . import backup as bk, savecodec, api, core
from .errors import StarMoeError

# 兼容旧测试/调用方
_is_bk, _better, _order = core.is_bk, core.better, core.order


def main(argv=None):
    try:
        return _main(argv)
    except StarMoeError as e:
        raise SystemExit(f"[{e.code}] {e.message}")


def _main(argv=None):
    ap = argparse.ArgumentParser(prog="starmoe-ios", description="从 iPhone 备份读取 Our Notes 存档并上传到 StarMoe")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("backups", help="列出本机的 iPhone 备份")
    s = sub.add_parser("ls", help="列出备份中游戏容器的文件（排查用）")
    s.add_argument("--backup", required=True); s.add_argument("--password")
    for name in ("scan", "upload"):
        s = sub.add_parser(name, help="扫描存档" if name == "scan" else "扫描并上传")
        s.add_argument("--backup", help="备份目录（含 Manifest.plist），或导出的普通文件夹")
        s.add_argument("--file", nargs="*", help="或直接指定存档文件/文件夹")
        s.add_argument("--server", choices=["intl", "jp"], help="--file 模式默认 intl；备份模式默认两个都扫")
        s.add_argument("--password", help="加密备份的密码（也可用环境变量 IOS_BACKUP_PASSWORD）")
        s.add_argument("--keys"); s.add_argument("--from-apk")
        s.add_argument("--auto-key", action="store_true",
                       help="从 GitHub StarMoe-org/StarMoe-box 最新 Release 自动下载官方 APK 并读取密钥（缓存在数据目录）")
        s.add_argument("--out", default="out", help="导出 _player JSON 的目录")
        if name == "upload":
            s.add_argument("--token", help="access token（也可用环境变量 STARMOE_TOKEN）；省略则交互登录")
    s = sub.add_parser("login", help="交互式登录，打印 token JSON")
    s = sub.add_parser("probe-usb", help="USB 探测 house_arrest；加 --pull 目录 则直接拉取容器")
    s.add_argument("--bundle", default="com.bilibili.sirius"); s.add_argument("--pull")
    s = sub.add_parser("filtered-backup", help="过滤备份：只保存游戏 App 的文件（不做整机备份）")
    s.add_argument("--bundle", default="com.bilibili.sirius")
    s.add_argument("--out", default="~/starmoe-ios/backup", help="备份输出目录")
    s.add_argument("--fake-free-gb", type=int, default=8192, help="向手机报告的空闲空间(GiB)")
    s.add_argument("--incremental", action="store_true", help="基于上次备份做增量（默认完整）")
    a = ap.parse_args(argv)

    if a.cmd == "backups":
        import plistlib
        for p in bk.default_backup_roots():
            m = plistlib.load(open(os.path.join(p, "Manifest.plist"), "rb"))
            apps = [x for v in bk.BUNDLES.values() for x in v if x in (m.get("Applications") or {})]
            print(p, "加密" if m.get("IsEncrypted") else "未加密", m.get("Lockdown", {}).get("DeviceName"), apps)
        return
    if a.cmd == "login":
        print(json.dumps(api.login_interactive(), indent=2)); return
    if a.cmd == "probe-usb":
        from . import device
        ok = device.probe(a.bundle, a.pull)
        print("house_arrest 可用" if ok else "house_arrest 不可用，请改用 filtered-backup"); return
    if a.cmd == "filtered-backup":
        from . import device
        d, enc = device.filtered_backup(a.bundle, os.path.expanduser(a.out), a.fake_free_gb << 30, not a.incremental)
        print("下一步: python -m starmoe_ios scan --backup", d, "--from-apk app-release.apk",
              "--password <备份密码>" if enc else "")
        return
    pw = getattr(a, "password", None) or os.environ.get("IOS_BACKUP_PASSWORD")
    if a.cmd == "ls":
        b = bk.Backup(a.backup, pw)
        print("已安装:", b.installed())
        for bs in bk.BUNDLES.values():
            for bundle in bs:
                for rel, size in b.all_paths(bundle):
                    print(bundle, size, rel)
        return

    if getattr(a, "auto_key", False) and not (a.keys or a.from_apk):
        from . import keyfetch
        from .gui import paths as _paths
        meta, fresh = keyfetch.fetch_apk(_paths.data_dir(), status=lambda m: print(m, file=sys.stderr))
        print(f"密钥来源：官方 StarMoe Box {meta['tag']}（{'新下载' if fresh else '缓存'}）", file=sys.stderr)
        a.from_apk = meta["path"]
    codec = savecodec.Codec.load(a.keys, a.from_apk)
    warn = lambda m: print("  !", m, file=sys.stderr)
    if a.file:
        saves = core.scan_folder(codec, a.file, a.server or "intl", warn)
        if not saves:
            core.raise_not_found(saves)
    else:
        if not a.backup:
            roots = bk.default_backup_roots()
            if len(roots) != 1:
                raise SystemExit("请用 --backup 指定备份目录。找到：\n" + "\n".join(roots))
            a.backup = roots[0]
        saves = core.scan_path(codec, a.backup, a.server, pw, warn)
    for s in saves:
        fn = core.write_player(s, a.out)
        print("解密成功，使用的密钥指纹(sha256 前 8 位):", s.get("key_fp", "?"))
        print(f"[{s['server']}] 玩家 {s['name']} ID {s['account_id']}  来源 {s['path']}  -> {fn}")
    if a.cmd == "upload":
        tok = a.token or os.environ.get("STARMOE_TOKEN") or api.login_interactive()["access_token"]
        for s in saves:
            r = api.upload(tok, s["server"], s["bytes"])
            print("已上传:", json.dumps(r, ensure_ascii=False))


if __name__ == "__main__":
    main()
