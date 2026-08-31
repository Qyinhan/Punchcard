"""抖音自动续火花插件：扫码登录后，每日向勾选的好友发送固定消息。"""
import json

from app.plugins.base import BasePlugin, CheckinResult, FieldSpec

from . import browser


class DouyinPlugin(BasePlugin):
    """抖音续火花签到插件（扫码登录会话 + 无头浏览器发消息）。"""

    platform = "douyin"
    name = "抖音"
    description = "抖音自动续火花：扫码登录后，每日向勾选的好友发送固定消息"
    builtin = True
    credential_fields = [
        FieldSpec(key="cookies", label="Cookie（扫码登录后自动保存）", type="textarea", required=False,
                  placeholder="由扫码登录功能自动填写，也可直接粘贴浏览器 Cookie"),
    ]
    config_fields = [
        FieldSpec(key="targets", label="目标好友", type="textarea", required=False,
                  placeholder="好友昵称，每行一个（也可用同步好友功能勾选）"),
    ]
    login_supported = True
    login_mode = "qr"
    friends_supported = True
    default_schedule_time = "10:00"

    def login(self, phone: str = "", **kwargs) -> dict:
        raise NotImplementedError("抖音登录请使用 create_login_session 会话")

    def create_login_session(self, account_id: int):
        """创建抖音扫码登录会话（无头浏览器 + 扫码确认交互）。

        Args:
            account_id: 所属账户 ID。
        """
        from .login_session import LoginSession

        return LoginSession(account_id)

    def list_friends(self, credentials: dict) -> list[str]:
        """滚动会话列表收集好友昵称。

        Args:
            credentials: 凭证 dict，含登录保存的 cookies。

        Returns:
            好友昵称列表。

        Raises:
            ValueError: 缺少 Cookie 时抛出。
        """
        cookies = self._cookies(credentials)
        if not cookies:
            raise ValueError("缺少 Cookie，请先完成登录")
        return browser.list_friends(cookies)

    def checkin(self, credentials: dict, extra: dict) -> CheckinResult:
        """向目标好友发送固定续火花消息。

        Args:
            credentials: 凭证 dict，含登录保存的 cookies。
            extra: 配置 dict，含 targets（目标好友昵称列表）。

        Returns:
            发送结果；缺少 Cookie / 未选择目标时返回失败结果。
        """
        cookies = self._cookies(credentials)
        if not cookies:
            return CheckinResult(success=False, message="缺少 Cookie，请先在账户中完成扫码登录")

        targets = extra.get("targets") or []
        if isinstance(targets, str):
            targets = [t.strip() for t in targets.replace("\n", ",").split(",") if t.strip()]
        else:
            targets = [t.strip() for t in targets if str(t).strip()]
        if not targets:
            return CheckinResult(success=False, message="未选择目标好友，请同步好友列表并勾选")

        message = "[续火花]"  # 固定发送续火花表情
        return browser.send_messages(cookies, targets, message)

    @staticmethod
    def _cookies(credentials: dict) -> list:
        """从凭证中解析 Cookie 列表，兼容两种格式：
        1. JSON 数组：[{"name","value","domain","path"}, ...]（登录功能自动保存的格式）
        2. Cookie 头字符串："name=value; name=value; ..."（浏览器复制 / 扩展导出，直接粘贴）

        Args:
            credentials: 凭证 dict。

        Returns:
            Cookie 列表；缺失或格式非法时返回空列表。
        """
        raw = credentials.get("cookies")
        if not raw:
            return []
        raw = str(raw).strip()
        # 格式 1：JSON 数组
        if raw.startswith("["):
            try:
                data = json.loads(raw)
                if isinstance(data, list):
                    return [c for c in data if isinstance(c, dict) and c.get("name")]
            except (ValueError, TypeError):
                pass
        # 格式 2：Cookie 头字符串
        out = []
        for part in raw.split(";"):
            part = part.strip()
            if "=" not in part:
                continue
            name, value = part.split("=", 1)
            name, value = name.strip(), value.strip()
            if name:
                out.append({"name": name, "value": value, "domain": ".douyin.com", "path": "/"})
        return out


plugin = DouyinPlugin()
