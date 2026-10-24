"""Windows：检查 Apple 移动设备支持（usbmuxd）。iPhone 的 USB 通信依赖 Apple 的驱动和服务，
来自 Microsoft Store 的「Apple Devices」应用或 iTunes。"""
import socket, subprocess, sys

STORE_URL = "ms-windows-store://pdp/?ProductId=9NP83LWLPZ9K"          # Apple Devices（Apple Inc.）
STORE_WEB = "https://apps.microsoft.com/detail/9NP83LWLPZ9K"
USBMUXD_PORT = 27015
_NO_WINDOW = 0x08000000


def _port_open(port=USBMUXD_PORT, timeout=0.5):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def _service_state(name):
    try:
        out = subprocess.run(["sc", "query", name], capture_output=True, text=True, timeout=5,
                             creationflags=_NO_WINDOW).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    if "RUNNING" in out:
        return "running"
    if "STATE" in out:
        return "stopped"
    return None


def _store_app_installed():
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command",
                              "(Get-AppxPackage -Name AppleInc.AppleDevices).Version"],
                             capture_output=True, text=True, timeout=15, creationflags=_NO_WINDOW).stdout
        return bool(out.strip())
    except (OSError, subprocess.SubprocessError):
        return False


def _itunes_driver_installed():
    try:
        import winreg
        for key in (r"SOFTWARE\Apple Inc.\Apple Mobile Device Support", r"SOFTWARE\WOW6432Node\Apple Inc.\Apple Mobile Device Support"):
            try:
                winreg.CloseKey(winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key))
                return True
            except OSError:
                pass
    except ImportError:
        pass
    return False


def check(platform=None):
    """返回 {"ok": bool, "state": "ok"|"missing"|"stopped"|"n/a", "detail": str}。"""
    if (platform or sys.platform) != "win32":
        return {"ok": True, "state": "n/a", "detail": ""}
    if _port_open():
        return {"ok": True, "state": "ok", "detail": "usbmuxd 端口可用"}
    svc = _service_state("Apple Mobile Device Service")
    if svc == "running":   # 服务在跑但端口没开：多半是刚启动，按正常处理
        return {"ok": True, "state": "ok", "detail": "Apple Mobile Device Service 运行中"}
    if svc == "stopped" or _store_app_installed() or _itunes_driver_installed():
        return {"ok": False, "state": "stopped", "detail": "已安装 Apple 设备支持，但服务未运行"}
    return {"ok": False, "state": "missing", "detail": "未找到 Apple Devices / iTunes"}
