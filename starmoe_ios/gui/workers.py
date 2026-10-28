"""后台线程：所有阻塞操作（USB、解密、网络）都不在界面线程里执行。"""
import asyncio, logging, os, shutil, time, traceback
from PySide6.QtCore import QThread, Signal
from .. import core, device
from ..errors import StarMoeError, ERR_DISCONNECTED, ERR_NO_DEVICE, ERR_NOT_TRUSTED, ERR_NETWORK
from ..power import StayAwake

log = logging.getLogger("starmoe.gui")
# 快照阶段没有字节也不当断线；超过这个时间仍是 0 字节，才按断线重试
PREPARE_WAIT_S = 15 * 60


def _err(e):
    if isinstance(e, StarMoeError):
        return e.code, e.message, e.detail
    log.error("未预期的错误：%s", traceback.format_exc())
    return ERR_NETWORK, f"发生未预期的错误：{type(e).__name__}: {e}", traceback.format_exc(limit=3)


class Task(QThread):
    """在线程里执行 fn()，结束后发 done(result) 或 failed(code, message, detail)。"""
    done = Signal(object)
    failed = Signal(str, str, object)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self.fn = fn

    def run(self):
        try:
            r = self.fn()
        except BaseException as e:  # noqa: BLE001 —— 线程里的异常必须回传给界面
            self.failed.emit(*_err(e))
            return
        self.done.emit(r)


def run_async(coro_fn):
    return lambda: asyncio.run(coro_fn())


class BackupWorker(QThread):
    """过滤备份 + 自动重试 + 解析。

    信号：status(str) 文字状态；retrying(n, max)；scanning()；found(list)；failed(code, msg, detail)；cancelled()
    """
    status = Signal(str)
    tick = Signal()          # 最多约 10 次/秒，只通知界面去读 stats
    retrying = Signal(int, int)
    scanning = Signal()
    found = Signal(object)
    failed = Signal(str, str, object)
    cancelled = Signal()

    def __init__(self, codec, bundle, server, out_dir, password=None, max_retries=5, wait_device_s=180,
                 runner=None, parent=None):
        super().__init__(parent)
        self.codec, self.bundle, self.server, self.out_dir = codec, bundle, server, out_dir
        self.password, self.max_retries, self.wait_device_s = password, max_retries, wait_device_s
        self.stats = device.BackupStats()
        self.kept_bytes = 0
        self._cancel = False
        self._loop = None
        self._task = None
        self.runner = runner or device.run_filtered_backup   # 测试时可替换

    # ---- 界面线程调用 ----
    def cancel(self):
        self._cancel = True
        loop, task = self._loop, self._task
        if loop and task:
            loop.call_soon_threadsafe(task.cancel)

    # ---- 线程内 ----
    def _once(self):
        async def main():
            self._task = asyncio.current_task()
            return await self.runner(self.bundle, self.out_dir, self.stats, on_log=lambda m: log.info(m),
                                     on_tick=self.tick.emit)
        self._loop = asyncio.new_event_loop()
        try:
            return self._loop.run_until_complete(main())
        finally:
            self._loop.close()
            self._loop = self._task = None

    def _salvage(self):
        """中断/取消后，先看看已经保留下来的文件里有没有完整存档（未加密备份时有效）。"""
        d = self.stats.udid_dir
        if not d or not os.path.isdir(d) or not self.stats.kept:
            return None
        try:
            return core.scan_path(self.codec, str(d), self.server, self.password, log=log.info) or None
        except StarMoeError:
            return None

    def _wait_device(self):
        def nap(seconds):
            end_at = time.time() + seconds
            while time.time() < end_at:
                if self._cancel:
                    return
                self.tick.emit()
                time.sleep(0.1)

        t0 = time.time()
        nap(2)   # 先等 2 秒，让 usbmuxd 注意到断开
        if self._cancel:
            return False
        while not self._cancel and time.time() - t0 < self.wait_device_s:
            try:
                if asyncio.run(device.list_serials()):
                    return True
            except StarMoeError:
                pass
            except Exception:
                pass
            nap(3)
        return False

    def run(self):
        with StayAwake("StarMoe Box is extracting an iPhone backup"):
            self._run()

    def _run(self):
        # 只在第一次尝试前清理旧数据；重试时保留已收到的游戏文件
        shutil.rmtree(self.out_dir, ignore_errors=True)
        os.makedirs(self.out_dir, exist_ok=True)
        attempt = 0
        while True:
            try:
                self._once()
                break
            except BaseException as e:  # noqa: BLE001
                if self._cancel or isinstance(e, asyncio.CancelledError):
                    self.scanning.emit()
                    saves = self._salvage()
                    if saves:
                        self.found.emit(saves)
                    else:
                        self.cancelled.emit()
                    return
                # 还没收到任何数据时的读超时 = 手机在准备快照，安静地再开一次备份，不弹“连接中断”
                if (device.is_idle_timeout(e) and self.stats.received == 0
                        and time.time() - self.stats.started < PREPARE_WAIT_S):
                    self.stats.phase = "preparing"
                    log.info("手机仍在准备备份（尚无数据），继续等待，不记为断线：%r", e)
                    continue
                # 结束阶段在搬/删临时文件，可能很久没有新字节，不是断线
                if device.is_idle_timeout(e) and self.stats.phase == "finalizing":
                    log.info("整理文件时读超时，继续，不记为断线：%r", e)
                    continue
                preparing_gave_up = (device.is_idle_timeout(e) and self.stats.received == 0
                                     and time.time() - self.stats.started >= PREPARE_WAIT_S)
                retryable = preparing_gave_up or device.is_disconnect(e) or (
                    isinstance(e, StarMoeError) and e.code in (ERR_NO_DEVICE, ERR_NOT_TRUSTED)
                    and self.stats.received > 0)
                log.warning("备份中断（第 %d 次）：%r", attempt + 1, e)
                if not retryable:
                    self.failed.emit(*_err(e))
                    return
                self.scanning.emit()
                saves = self._salvage()
                if saves:   # 游戏文件已经到手，不必再传一遍
                    self.found.emit(saves)
                    return
                attempt += 1
                if attempt > self.max_retries:
                    self.failed.emit(ERR_DISCONNECTED, f"连接中断，已自动重试 {self.max_retries} 次仍未成功。", repr(e))
                    return
                self.retrying.emit(attempt, self.max_retries)
                if not self._wait_device():
                    if self._cancel:
                        self.cancelled.emit()
                    else:
                        self.failed.emit(ERR_DISCONNECTED, "连接中断后没有重新检测到 iPhone。", repr(e))
                    return
                self.stats.percent = 0.0
        self.scanning.emit()
        try:
            saves = core.scan_path(self.codec, str(self.stats.udid_dir), self.server, self.password, log=log.info)
        except BaseException as e:  # noqa: BLE001
            self.failed.emit(*_err(e))
            return
        self.found.emit(saves)
