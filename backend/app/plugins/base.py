"""插件抽象基类：定义平台插件需实现的接口与字段描述结构。

新增平台时，继承 :class:`BasePlugin` 并实现 :meth:`BasePlugin.checkin`。
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class FieldSpec:
    """插件对外暴露的一个字段（凭证或配置项），前端据此渲染表单。"""

    key: str
    label: str
    type: str = "text"  # text / password / textarea / number
    required: bool = True
    placeholder: str = ""
    hint: str = ""
    #: 是否敏感字段；False 的凭证值会随账户接口返回（前端回显），如登录手机号
    sensitive: bool = True


@dataclass
class CheckinResult:
    """一次签到执行的结果。"""

    success: bool
    message: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


class BasePlugin(ABC):
    """所有平台插件的基类。

    子类需声明 ``platform`` / ``name`` 并实现 :meth:`checkin`；
    :meth:`validate` 可按需覆写以做更严格的校验。
    """

    #: 平台唯一标识（存库用），如 "douyin"
    platform: str = ""
    #: 展示名称，如 "抖音"
    name: str = ""
    #: 平台描述
    description: str = ""
    #: 凭证字段：新增账户时前端据此渲染表单
    credential_fields: list[FieldSpec] = []
    #: 可选配置字段（签到之外的自定义项）
    config_fields: list[FieldSpec] = []
    #: 默认每日签到时间 HH:MM
    default_schedule_time: str = "08:00"
    #: 是否支持交互式登录（如验证码登录后自动抓取 Cookie）
    login_supported: bool = False
    #: 交互式登录方式，前端据此渲染对应登录面板：
    #: "qr" 扫码登录 / "geetest_sms" 极验+短信验证码 / 空串表示无交互登录
    login_mode: str = ""
    #: 是否支持同步好友列表（供前端勾选目标）
    friends_supported: bool = False

    def validate(self, credentials: dict) -> None:
        """校验凭证完整性；不通过时抛 ValueError。

        Args:
            credentials: 解密后的凭证 dict。

        Raises:
            ValueError: 缺少必填字段时抛出。
        """
        for f in self.credential_fields:
            if f.required and not credentials.get(f.key):
                raise ValueError(f"缺少必填字段: {f.label}")


    def create_login_session(self, account_id: int):
        """创建一次交互式登录会话（如抖音验证码登录）。

        仅在 ``login_supported=True`` 时被调用。

        Args:
            account_id: 所属账户 ID。

        Returns:
            实现了 start/send_code/solve_captcha/submit_code/status/close 的会话对象。
        """
        raise NotImplementedError(f"{self.__class__.__name__} 不支持交互式登录")

    def list_friends(self, credentials: dict) -> list[str]:
        """基于已保存的凭证，返回好友列表（昵称）。

        仅在 ``friends_supported=True`` 时被调用。

        Args:
            credentials: 解密后的凭证 dict。

        Returns:
            好友昵称列表。
        """
        raise NotImplementedError(f"{self.__class__.__name__} 不支持好友列表同步")

    def on_schedule_time_set(self, schedule_time: str, extra: dict) -> dict:
        """设置账户签到时间时的回调钩子（创建/更新/自动签到完成后调用）。

        子类可覆写此方法以在 extra 中规划实际执行时间（如 extra['next_schedule_time']），
        从而实现防风控随机浮动而不修改用户设定的 schedule_time 基准时间。

        Args:
            schedule_time: 用户设定的基准每日签到时间 (HH:MM)。
            extra: 账户当前的 extra_config 字典。

        Returns:
            更新后的 extra 字典。
        """
        return extra

    @abstractmethod
    def checkin(self, credentials: dict, extra: dict) -> CheckinResult:
        """执行一次签到。

        Args:
            credentials: 解密后的凭证 dict。
            extra: 插件自定义配置 dict。

        Returns:
            签到结果 CheckinResult。
        """
        raise NotImplementedError

    def describe(self) -> dict:
        """输出插件元信息，供前端渲染与管理页面使用。

        Returns:
            包含平台标识、名称、字段定义及能力开关的 dict。
        """
        return {
            "platform": self.platform,
            "name": self.name,
            "description": self.description,
            "credential_fields": [f.__dict__ for f in self.credential_fields],
            "config_fields": [f.__dict__ for f in self.config_fields],
            "default_schedule_time": self.default_schedule_time,
            "login_supported": self.login_supported,
            "login_mode": self.login_mode,
            "friends_supported": self.friends_supported,
        }
