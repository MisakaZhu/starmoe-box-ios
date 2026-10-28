"""提取期间禁止系统把进程挂起或让机器睡眠。失败时只记日志，不中断备份。"""
import logging, sys

log = logging.getLogger("starmoe.power")

# NSActivityOptions（NSProcessInfo.h）
NSActivityIdleSystemSleepDisabled = 1 << 20
NSActivityUserInitiated = 0x00FFFFFF | NSActivityIdleSystemSleepDisabled

# Windows SetThreadExecutionState
_ES_CONTINUOUS = 0x80000000
_ES_SYSTEM_REQUIRED = 0x00000001


class StayAwake:
    """with StayAwake(reason): 覆盖整个提取过程，结束时一定配对释放。"""

    def __init__(self, reason="StarMoe Box is extracting an iPhone backup"):
        self.reason = reason
        self._token = None

    def __enter__(self):
        self._token = begin(self.reason)
        return self

    def __exit__(self, *exc):
        end(self._token)
        self._token = None
        return False


def begin(reason):
    try:
        if sys.platform == "darwin":
            return _darwin_begin(reason)
        if sys.platform == "win32":
            return _win_begin()
    except Exception as e:  # noqa: BLE001
        log.warning("无法禁止系统休眠：%s", e)
    return None


def end(token):
    try:
        if sys.platform == "darwin":
            _darwin_end(token)
        elif sys.platform == "win32":
            _win_end()
    except Exception as e:  # noqa: BLE001
        log.warning("无法恢复系统休眠：%s", e)


def _darwin_begin(reason):
    import ctypes
    import ctypes.util
    ctypes.cdll.LoadLibrary("/System/Library/Frameworks/Foundation.framework/Foundation")
    objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc"))
    objc.objc_getClass.restype = ctypes.c_void_p
    objc.objc_getClass.argtypes = [ctypes.c_char_p]
    objc.sel_registerName.restype = ctypes.c_void_p
    objc.sel_registerName.argtypes = [ctypes.c_char_p]

    def sel(name):
        return objc.sel_registerName(name.encode())

    send = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(objc.objc_msgSend)
    info = send(objc.objc_getClass(b"NSProcessInfo"), sel("processInfo"))
    reason_s = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p)(
        objc.objc_msgSend)(objc.objc_getClass(b"NSString"), sel("stringWithUTF8String:"), reason.encode())
    begin_act = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint64, ctypes.c_void_p)(
        objc.objc_msgSend)
    token = begin_act(info, sel("beginActivityWithOptions:reason:"),
                      ctypes.c_uint64(NSActivityUserInitiated | NSActivityIdleSystemSleepDisabled), reason_s)
    if token:
        token = send(token, sel("retain"))
    return (info, token)


def _darwin_end(token):
    if not token:
        return
    import ctypes
    import ctypes.util
    objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc"))
    objc.sel_registerName.restype = ctypes.c_void_p
    objc.sel_registerName.argtypes = [ctypes.c_char_p]
    info, activity = token
    end_act = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(objc.objc_msgSend)
    end_act(info, objc.sel_registerName(b"endActivity:"), activity)
    release = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p)(objc.objc_msgSend)
    release(activity, objc.sel_registerName(b"release"))


def _win_begin():
    import ctypes
    ctypes.windll.kernel32.SetThreadExecutionState(_ES_CONTINUOUS | _ES_SYSTEM_REQUIRED)
    return True


def _win_end():
    import ctypes
    ctypes.windll.kernel32.SetThreadExecutionState(_ES_CONTINUOUS)
