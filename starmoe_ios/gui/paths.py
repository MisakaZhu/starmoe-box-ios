"""日志 / 数据目录（不保存任何密钥；令牌只进系统钥匙串）。"""
import logging, logging.handlers, os, sys
from . import APP_NAME


def _home(*p):
    return os.path.join(os.path.expanduser("~"), *p)


def data_dir():
    if os.environ.get("STARMOE_DATA_DIR"):
        d = os.environ["STARMOE_DATA_DIR"]
    elif sys.platform == "darwin":
        d = _home("Library", "Application Support", APP_NAME)
    elif sys.platform == "win32":
        d = os.path.join(os.environ.get("LOCALAPPDATA") or _home("AppData", "Local"), APP_NAME)
    else:
        d = os.path.join(os.environ.get("XDG_DATA_HOME") or _home(".local", "share"), APP_NAME)
    os.makedirs(d, exist_ok=True)
    return d


def log_dir():
    if os.environ.get("STARMOE_DATA_DIR"):
        d = os.path.join(os.environ["STARMOE_DATA_DIR"], "logs")
    elif sys.platform == "darwin":
        d = _home("Library", "Logs", APP_NAME)
    elif sys.platform == "win32":
        d = os.path.join(os.environ.get("LOCALAPPDATA") or _home("AppData", "Local"), APP_NAME, "logs")
    else:
        d = os.path.join(os.environ.get("XDG_STATE_HOME") or _home(".local", "state"), APP_NAME, "logs")
    os.makedirs(d, exist_ok=True)
    return d


def backup_dir():
    d = os.path.join(data_dir(), "backup")
    os.makedirs(d, exist_ok=True)
    return d


def setup_logging():
    h = logging.handlers.RotatingFileHandler(os.path.join(log_dir(), "starmoe-box.log"), maxBytes=2 << 20,
                                             backupCount=3, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(h)
    # pymobiledevice3 很啰嗦；只保留警告
    logging.getLogger("pymobiledevice3").setLevel(logging.WARNING)
