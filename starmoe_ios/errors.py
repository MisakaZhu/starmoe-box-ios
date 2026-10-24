"""统一的错误类型：CLI 打印 message 后退出；GUI 按 code 显示对应的错误卡片（设计稿 07）。"""

ERR_NO_DEVICE = "ERR_NO_DEVICE"          # 没有 USB 设备 / 没有 usbmuxd
ERR_NOT_TRUSTED = "ERR_NOT_TRUSTED"      # 未信任此电脑 / 手机锁屏
ERR_NOT_INSTALLED = "ERR_NOT_INSTALLED"  # 手机上没有安装所选服务器的游戏
ERR_BACKUP_DENIED = "ERR_BACKUP_DENIED"  # 手机拒绝备份
ERR_DISCONNECTED = "ERR_DISCONNECTED"    # 传输中断（可自动重试）
ERR_DISK = "ERR_DISK"                    # 电脑空间不足
ERR_PASSWORD = "ERR_PASSWORD"            # 加密备份需要密码 / 密码错误
ERR_KEYS = "ERR_KEYS"                    # 未加载密钥 / APK 里找不到
ERR_DECRYPT = "ERR_DECRYPT"              # 找到存档文件但解不开（密钥可能已更新）
ERR_NO_SAVE = "ERR_NO_SAVE"              # 没找到任何存档
ERR_AUTH = "ERR_AUTH"                    # 登录回调无效 / 换取令牌失败
ERR_AUTH_EXPIRED = "ERR_AUTH_EXPIRED"    # 令牌过期且刷新失败
ERR_NETWORK = "ERR_NETWORK"              # 网络 / 服务端错误


class StarMoeError(Exception):
    def __init__(self, code, message, detail=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail

    def __str__(self):
        return self.message
