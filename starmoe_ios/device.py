"""USB 直连（pymobiledevice3 >= 11，async API）。CLI 与 GUI 共用。

1. probe/pull：house_arrest。VendDocuments 只对开启“文件共享”的 App 有效；VendContainer 对
   App Store 安装的 App 通常被拒绝。成功的话直接把容器拉到本地文件夹，不需要备份。
2. filtered_backup：走 mobilebackup2 协议做“过滤备份”（类似 iMazing）。设备照常把整机数据
   流过来，但只有目标 App 容器（及其 App Group 容器）里的文件和备份元数据会写盘，其余字节
   读完即丢弃并照常回 ACK，让设备正常完成备份。
   - 向设备报告的空闲空间被放大（fake_free），否则设备会按整机大小检查电脑空间而拒绝备份。
   - 若设备开启了“加密本地备份”，收到的文件和 Manifest.db 都是加密的；需要备份密码才能 scan。
   - USB 上仍要传输整机数据，1TB 手机可能需要数小时；只占用很少磁盘。
"""
import asyncio, logging, os, shutil, time
from pathlib import Path
from .errors import (StarMoeError, ERR_NO_DEVICE, ERR_NOT_TRUSTED, ERR_NOT_INSTALLED, ERR_DISK,
                     ERR_BACKUP_DENIED, ERR_DISCONNECTED)

log = logging.getLogger("starmoe.device")
MIN_HOST_FREE = 2 << 30


def _exc_names(e):
    return {c.__name__ for c in type(e).__mro__}


DISCONNECT_ERRORS = {"ConnectionTerminatedError", "ConnectionAbortedError", "ConnectionResetError",
                     "BrokenPipeError", "IncompleteReadError", "NoDeviceConnectedError",
                     "ConnectionFailedError", "DeviceNotFoundError", "MuxException"}


def is_idle_timeout(e):
    """读超时：手机做快照时可能几分钟不发数据，不等于线断了。"""
    return "TimeoutError" in _exc_names(e)


def is_disconnect(e):
    if is_idle_timeout(e):
        return False
    return bool(_exc_names(e) & DISCONNECT_ERRORS) or (isinstance(e, OSError) and not isinstance(e, FileNotFoundError))


async def list_serials():
    from pymobiledevice3.usbmux import list_devices
    try:
        return [d.serial for d in await list_devices() if getattr(d, "is_usb", True)]
    except Exception as e:
        if "ConnectionFailedToUsbmuxdError" in _exc_names(e) or isinstance(e, (FileNotFoundError, ConnectionRefusedError)):
            raise StarMoeError(ERR_NO_DEVICE, "无法连接 usbmuxd：Windows 需安装 Apple Devices（或 iTunes）以提供 USB 驱动。",
                               repr(e))
        raise


async def lockdown(serial=None):
    from pymobiledevice3.lockdown import create_using_usbmux
    serials = await list_serials()
    if not serials:
        raise StarMoeError(ERR_NO_DEVICE, "没有检测到 USB 连接的 iPhone：请用数据线连接并解锁手机。")
    try:
        return await create_using_usbmux(serial=serial or serials[0], connection_type="USB")
    except Exception as e:  # PairingDialogResponsePendingError / PasswordRequiredError / UserDeniedPairingError …
        n = _exc_names(e)
        if "UserDeniedPairingError" in n:
            msg = "你在手机上点了“不信任”。请拔插数据线，在弹窗中点“信任”并输入锁屏密码。"
        elif "PasswordRequiredError" in n:
            msg = "手机处于锁定状态：请解锁 iPhone 后重试。"
        else:
            msg = "等待你在 iPhone 上点击“信任此电脑”并输入锁屏密码。"
        raise StarMoeError(ERR_NOT_TRUSTED, msg, f"{type(e).__name__}: {e}")


async def app_info(ld, bundle):
    from pymobiledevice3.services.installation_proxy import InstallationProxyService
    async with InstallationProxyService(ld) as ip:
        r = await ip.lookup({"BundleIDs": [bundle], "ReturnAttributes": [
            "CFBundleIdentifier", "CFBundleShortVersionString", "Container", "GroupContainers",
            "UIFileSharingEnabled", "EnvironmentVariables"]}) or {}
    return r.get(bundle, {})


async def detect(bundle):
    """返回设备与游戏信息，用于“连接设备”页面。"""
    ld = await lockdown()
    try:
        v = ld.all_values
        info = await app_info(ld, bundle)
        try:
            enc = bool(await ld.get_value("com.apple.mobile.backup", "WillEncrypt"))
        except Exception:
            enc = False
        try:
            cap = await ld.get_value("com.apple.disk_usage", "TotalDiskCapacity")
        except Exception:
            cap = None
        return {"udid": ld.udid, "name": v.get("DeviceName") or "iPhone",
                "model": ld.display_name or v.get("ProductType") or "", "ios": v.get("ProductVersion") or "",
                "capacity": cap, "installed": bool(info), "app_version": info.get("CFBundleShortVersionString"),
                "will_encrypt": enc, "bundle": bundle}
    finally:
        try:
            await ld.close()
        except Exception:
            pass


async def _probe(bundle, dest=None):
    from pymobiledevice3.services.house_arrest import HouseArrestService
    ld = await lockdown()
    info = await app_info(ld, bundle)
    if not info:
        raise StarMoeError(ERR_NOT_INSTALLED, f"手机上没有安装 {bundle}")
    print(bundle, info.get("CFBundleShortVersionString"), "UIFileSharingEnabled =", info.get("UIFileSharingEnabled"))
    for docs_only in (False, True):
        name = "VendDocuments" if docs_only else "VendContainer"
        try:
            ha = await HouseArrestService.create(ld, bundle, documents_only=docs_only)
        except Exception as e:
            print(f"house_arrest {name} 失败: {e}")
            continue
        async with ha:
            print(f"house_arrest {name} 成功:", await ha.listdir("/"))
            if dest:
                os.makedirs(dest, exist_ok=True)
                await ha.pull("/" if docs_only else "/Documents", dest, ignore_errors=True, progress_bar=False)
                print("已拉取到", dest, "（可直接 scan --backup", dest, "）")
        return True
    return False


def probe(bundle, dest=None):
    return asyncio.run(_probe(bundle, dest))


def _norm(p):
    p = p.rstrip("/")
    return p[len("/private"):] if p.startswith("/private/") else p


class BackupStats:
    """过滤备份的实时统计。由备份线程写入，GUI 定时读取（只是 int/float，读到旧值也无妨）。"""

    def __init__(self):
        self.received = 0      # 从 USB 收到的字节（含被丢弃的数据）
        self.kept = 0          # 保留（写盘）的游戏文件数
        self.dropped = 0
        self.percent = 0.0     # 手机报告的进度
        self.kept_bytes = 0
        self.started = time.time()
        self.phase = "connecting"   # connecting / preparing / transferring / finishing
        self.will_encrypt = None
        self.udid_dir = None
        self.passcode_needed = False   # pymobiledevice3：手机锁屏，等用户输入锁屏密码


class PasscodeLogHandler(logging.Handler):
    """pymobiledevice3 在锁屏时只打日志：Please enter the device passcode to continue the backup。"""

    def __init__(self, stats):
        super().__init__(logging.WARNING)
        self.stats = stats

    def emit(self, record):
        try:
            msg = record.getMessage()
        except Exception:
            return
        if "passcode" in msg.lower():
            self.stats.passcode_needed = True


def _folder_bytes(path):
    total = 0
    for root, _, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


async def run_filtered_backup(bundle, out_dir, stats=None, fake_free=8 << 40, full=True, on_log=None, on_tick=None):
    """执行一次过滤备份。返回 (udid_dir, will_encrypt)。异常：StarMoeError 或原始连接异常（见 is_disconnect）。"""
    from pymobiledevice3.services.mobilebackup2 import Mobilebackup2Service
    from pymobiledevice3.services import device_link as dlmod

    say = on_log or (lambda m: log.info(m))
    stats = stats or BackupStats()
    out_dir = Path(out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(out_dir).free
    say(f"电脑可用空间: {free / 2**30:.1f} GiB")
    if free < MIN_HOST_FREE:
        raise StarMoeError(ERR_DISK, "电脑可用空间不足 2 GiB，请先清理。")

    stats.phase = "connecting"
    ld = await lockdown()
    info = await app_info(ld, bundle)
    if not info:
        raise StarMoeError(ERR_NOT_INSTALLED, f"手机上没有安装 {bundle}")
    containers = [_norm(info["Container"])] if info.get("Container") else []
    containers += [_norm(v) for v in (info.get("GroupContainers") or {}).values()]
    domains = ["AppDomain-" + bundle] + ["AppDomainGroup-" + g for g in (info.get("GroupContainers") or {})]
    say(f"目标域: {domains}")
    stats.udid_dir = out_dir / ld.udid

    def keep(bf):
        dn = bf.device_name or ""
        n = _norm(dn)
        ok = any(n == c or n.startswith(c + "/") for c in containers) or any(d in dn for d in domains)
        if ok:
            stats.kept += 1
            log.debug("保留 %s", dn)
        else:
            stats.dropped += 1
        return ok

    # 设备会按整机备份大小检查电脑空闲空间；我们只写极少数据，所以报告一个足够大的数值。
    async def fake_free_space(self, _msg):
        self._reported_free_space = max(fake_free, shutil.disk_usage(self.root_path).free)
        await self.status_response(0, status_dict=self._reported_free_space)

    orig_free, orig_recv = dlmod.DeviceLink.get_free_disk_space, dlmod.DeviceLink._recvall

    async def counting_recv(self, size):
        b = await orig_recv(self, size)
        stats.received += len(b)
        if b:
            stats.passcode_needed = False   # 又有数据了，锁屏提示可以收起
        if stats.phase != "transferring":
            stats.phase = "transferring"
        return b

    def progress(p):
        try:
            stats.percent = float(p)
        except (TypeError, ValueError):
            pass

    async def pulse():
        """界面刷新最多 10 次/秒。目录大小在这条备份线程里算，不占用 GUI。"""
        last_walk = 0.0
        while True:
            await asyncio.sleep(0.1)
            now = time.monotonic()
            if stats.udid_dir and now - last_walk >= 2.0:
                last_walk = now
                stats.kept_bytes = _folder_bytes(stats.udid_dir)
            if on_tick:
                on_tick()

    dlmod.DeviceLink.get_free_disk_space = fake_free_space
    dlmod.DeviceLink._recvall = counting_recv
    pulse_task = asyncio.ensure_future(pulse())
    passcode_log = logging.getLogger("pymobiledevice3.services.mobilebackup2")
    passcode_handler = PasscodeLogHandler(stats)
    passcode_log.addHandler(passcode_handler)
    try:
        async with Mobilebackup2Service(ld) as mb:
            stats.will_encrypt = enc = await mb.get_will_encrypt()
            say(f"手机开启了备份加密: {enc}")
            stats.phase = "preparing"   # 手机先做快照，可能 5–10 分钟都是 0 字节
            try:
                await mb.backup(full=full, backup_directory=out_dir, progress_callback=progress, filter_callback=keep)
            except Exception as e:
                if is_disconnect(e) or isinstance(e, asyncio.CancelledError):
                    raise
                # 已收到游戏文件时，收尾阶段的错误（例如 205）不影响存档提取：交给调用方扫描
                if stats.kept:
                    say(f"备份结束时出现错误（已保留 {stats.kept} 个文件，继续解析）: {e!r}")
                else:
                    raise StarMoeError(ERR_BACKUP_DENIED, "iPhone 拒绝了备份请求。", repr(e))
    finally:
        pulse_task.cancel()
        try:
            await pulse_task
        except asyncio.CancelledError:
            pass
        passcode_log.removeHandler(passcode_handler)
        dlmod.DeviceLink.get_free_disk_space = orig_free
        dlmod.DeviceLink._recvall = orig_recv
        try:
            await ld.close()
        except Exception:
            pass
    stats.phase = "finishing"
    say(f"完成：保留 {stats.kept} 个文件，丢弃 {stats.dropped} 个。备份目录: {stats.udid_dir}")
    return stats.udid_dir, enc


def filtered_backup(bundle, out_dir, fake_free=8 << 40, full=True):
    """CLI 用：带进度打印的同步包装。"""
    stats = BackupStats()

    async def main():
        task = asyncio.ensure_future(run_filtered_backup(bundle, out_dir, stats, fake_free, full, on_log=print))
        while not task.done():
            await asyncio.wait([task], timeout=10)
            print(f"进度 {stats.percent:.0f}%  已接收 {stats.received / 2**30:.2f} GiB  "
                  f"保留 {stats.kept} / 丢弃 {stats.dropped}", flush=True)
        return task.result()

    return asyncio.run(main())
