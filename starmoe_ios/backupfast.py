"""过滤备份时不要为丢弃的文件创建空占位 inode。

pymobiledevice3 对 filter 拒绝的文件会 touch() 一个空文件，结束阶段再逐个
move/remove。一台手机上这会是几十万个 inode，整理要十几分钟。
SHA1 文件名的空 touch 改成只记在内存里；对应的 move/remove 不再访问磁盘。
真正要保留的文件仍走原来的写入和移动。
"""
import contextlib
from pathlib import Path

_HEX = set("0123456789abcdefABCDEF")


def is_backup_blob(path):
    name = Path(path).name
    return len(name) == 40 and all(c in _HEX for c in name)


def blob_name(path):
    return Path(path).name.lower()


@contextlib.contextmanager
def placeholder_bypass(stats, device_link_cls):
    """在一次 backup() 期间生效。device_link_cls 是 DeviceLink 类（测试可传入替身）。"""
    skipped = set()
    orig_touch = Path.touch
    orig_move = device_link_cls.move_items
    orig_remove = device_link_cls.remove_items

    def touch(self, mode=0o666, exist_ok=True):
        if is_backup_blob(self) and not self.exists():
            skipped.add(blob_name(self))
            return None
        return orig_touch(self, mode=mode, exist_ok=exist_ok)

    def _skipped(path):
        return blob_name(path) in skipped

    async def move_items(self, message):
        items = message[1]
        stats.phase = "finalizing"
        stats.finalize_items += len(items)
        pending = {}
        for src, dst in items.items():
            if _skipped(src):
                continue
            pending[src] = dst
        if not pending:
            await self.status_response(0)
            return
        cloned = list(message)
        cloned[1] = pending
        await orig_move(self, cloned)

    async def remove_items(self, message):
        paths = list(message[1])
        stats.phase = "finalizing"
        stats.finalize_items += len(paths)
        pending = [p for p in paths if not _skipped(p)]
        if not pending:
            await self.status_response(0)
            return
        cloned = list(message)
        cloned[1] = pending
        await orig_remove(self, cloned)

    Path.touch = touch
    device_link_cls.move_items = move_items
    device_link_cls.remove_items = remove_items
    try:
        yield skipped
    finally:
        Path.touch = orig_touch
        device_link_cls.move_items = orig_move
        device_link_cls.remove_items = orig_remove
