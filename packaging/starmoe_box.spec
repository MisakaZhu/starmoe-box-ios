# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 配置：macOS → "StarMoe Box.app"（onedir + BUNDLE），Windows → dist\\StarMoeBox\\（onedir，交给 Inno Setup 打安装包；
# 设 STARMOE_ONEFILE=1 则生成单文件 StarMoeBox.exe），Linux → onedir（仅供测试）
# 用法（在仓库根目录）：pyinstaller --noconfirm --clean packaging/starmoe_box.spec
import os, re, sys
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules, copy_metadata

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
VERSION = re.search(r'VERSION\s*=\s*"([^"]+)"', open(os.path.join(ROOT, "starmoe_ios", "gui", "__init__.py"), encoding="utf-8").read()).group(1)
ICONS = os.path.join(ROOT, "packaging", "icons")
SCHEME = "moe.starmoe.box"
BUNDLE_ID = "moe.starmoe.box.ios-desktop"

datas = [(os.path.join(ROOT, f), ".") for f in ("LICENSE", "NOTICE", "README.md")]
binaries, hiddenimports = [], []
# pymobiledevice3 大量使用延迟导入，并带有资源文件，整体收集最稳妥
for pkg in ("pymobiledevice3",):
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hiddenimports += h
hiddenimports += collect_submodules("keyring.backends")
hiddenimports += ["iphone_backup_decrypt", "certifi", "truststore"]
# cacert.pem 不是 Python 模块。不收进包的话，冻结后的 keyfetch/OAuth 会 CERTIFICATE_VERIFY_FAILED。
datas += collect_data_files("certifi")
for dist in ("keyring", "pymobiledevice3"):   # entry points / 版本号依赖 dist-info
    try:
        datas += copy_metadata(dist)
    except Exception:
        pass
if sys.platform == "win32":
    hiddenimports += ["win32ctypes.pywin32", "win32ctypes.pywin32.win32cred", "win32ctypes.core"]
    # 自由线程构建（3.13t / 3.15 的 abi3t wheel）依赖 python3t.dll，PyInstaller 解析不到，
    # cryptography._rust 在冻结后的进程里会 DLL load failed。打包必须用带 GIL 的 CPython。
    if "t" in getattr(sys, "abiflags", ""):
        raise SystemExit("打包不支持自由线程 Python（abiflags 含 t）。请用常规 CPython 3.12。")
    for name in ("python3.dll", "vcruntime140.dll", "vcruntime140_1.dll"):
        src = os.path.join(sys.base_prefix, name)
        if os.path.isfile(src):
            binaries.append((src, "."))

excludes = ["tkinter", "matplotlib", "IPython", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore",
            "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtMultimedia", "PySide6.QtPdf"]

a = Analysis([os.path.join(ROOT, "packaging", "entry.py")], pathex=[ROOT], binaries=binaries, datas=datas,
             hiddenimports=hiddenimports, excludes=excludes, noarchive=False)
pyz = PYZ(a.pure)

ENT = os.path.join(ROOT, "packaging", "macos", "entitlements.plist")
if sys.platform == "win32" and os.environ.get("STARMOE_ONEFILE") == "1":
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="StarMoeBox", console=False, upx=False,
              icon=os.path.join(ICONS, "app.ico"), version=None)
elif sys.platform == "win32":
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="StarMoeBox", console=False, upx=False,
              icon=os.path.join(ICONS, "app.ico"), version=None)
    coll = COLLECT(exe, a.binaries, a.datas, name="StarMoeBox", upx=False)
else:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="StarMoeBox", console=False, upx=False,
              argv_emulation=False,   # URL 回调由 Qt 的 QFileOpenEvent 处理，不能让 argv 模拟吞掉 Apple Event
              target_arch=os.environ.get("TARGET_ARCH") or None,
              codesign_identity=os.environ.get("CODESIGN_IDENTITY") or None,
              # 设置了 CODESIGN_IDENTITY（Developer ID）时，PyInstaller 会用 hardened runtime + 时间戳逐个签名，
              # 外层 .app 由 build_mac.sh 再统一签一次
              entitlements_file=ENT if os.environ.get("CODESIGN_IDENTITY") else None, icon=os.path.join(ICONS, "app.icns" if sys.platform == "darwin" else "app.png"))
    coll = COLLECT(exe, a.binaries, a.datas, name="StarMoeBox", upx=False)
    if sys.platform == "darwin":
        app = BUNDLE(coll, name="StarMoe Box.app", icon=os.path.join(ICONS, "app.icns"), bundle_identifier=BUNDLE_ID,
                     version=VERSION,
                     info_plist={
                         "CFBundleDisplayName": "StarMoe Box",
                         "CFBundleName": "StarMoe Box",
                         "CFBundleShortVersionString": VERSION,
                         "CFBundleVersion": VERSION,
                         "CFBundleURLTypes": [{"CFBundleURLName": SCHEME, "CFBundleTypeRole": "Viewer",
                                               "CFBundleURLSchemes": [SCHEME]}],
                         "NSHighResolutionCapable": True,
                         # 窗口被挡住时 App Nap 会把备份线程降到十几 MB/s
                         "NSAppSleepDisabled": True,
                         "LSAppNapIsDisabled": True,
                         "LSMinimumSystemVersion": "11.0",
                         "LSApplicationCategoryType": "public.app-category.utilities",
                         "NSHumanReadableCopyright": "Apache License 2.0 · 非官方工具",
                     })
