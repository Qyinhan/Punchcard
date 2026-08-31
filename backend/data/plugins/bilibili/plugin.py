"""
B 站每日登录签到插件

支持两种凭证来源：
  1. 手机号 + 短信验证码登录（推荐）：前端完成极验后自动保存 Cookie
  2. 手动填写 SESSDATA：从浏览器 Cookie 复制

签到逻辑：
  调用 https://api.bilibili.com/x/web-interface/nav 接口，携带 SESSDATA Cookie，
  B 站后端以此记录「今日已登录」（+5 经验值）。无需 WBI 签名。
"""

import json
import logging

import httpx

from app.plugins.base import BasePlugin, CheckinResult, FieldSpec

logger = logging.getLogger(__name__)

_NAV_URL = "https://api.bilibili.com/x/web-interface/nav"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.bilibili.com/",
}


class BilibiliPlugin(BasePlugin):
    """B 站每日登录签到插件。"""

    platform = "bilibili"
    name = "哔哩哔哩"
    description = "每日访问 B 站导航接口，触发登录记录，完成「每日登录」任务（+5 经验）"
    builtin = True
    credential_fields = [
        FieldSpec(
            key="phone",
            label="登录手机号",
            type="text",
            required=False,
            placeholder="填写后可使用下方手机号登录，自动获取 Cookie",
            sensitive=False,
        ),
        FieldSpec(
            key="sessdata",
            label="SESSDATA",
            type="password",
            required=False,
            placeholder="手动填写 SESSDATA Cookie；或使用手机号登录自动获取",
            sensitive=True,
        ),
    ]
    login_supported = True
    default_schedule_time = "08:00"

    def create_login_session(self, account_id: int):
        """创建 B 站短信验证码登录会话（纯 HTTP，无需浏览器）。

        Args:
            account_id: 所属账户 ID。
        """
        from .login_session import LoginSession

        return LoginSession(account_id)

    def checkin(self, credentials: dict, extra: dict) -> CheckinResult:
        """调用 B 站导航接口触发「每日登录」记录。

        Args:
            credentials: 凭证 dict，含 sessdata 或登录保存的 cookies。
            extra: 插件自定义配置（本插件未使用）。

        Returns:
            签到结果；SESSDATA 缺失或请求失败时返回失败结果。
        """
        sessdata = self._get_sessdata(credentials)
        if not sessdata:
            return CheckinResult(
                success=False,
                message="缺少 SESSDATA，请完成手机号登录或手动填写 SESSDATA",
            )
        cookies = {"SESSDATA": sessdata}
        try:
            with httpx.Client(timeout=15, follow_redirects=True) as client:
                resp = client.get(_NAV_URL, headers=_HEADERS, cookies=cookies)
                resp.raise_for_status()
                data = resp.json()
        except httpx.RequestError as exc:
            logger.warning("B站登录请求失败: %s", exc)
            return CheckinResult(success=False, message=f"网络请求失败: {exc}")
        except ValueError:
            return CheckinResult(success=False, message="响应解析失败，可能被风控拦截")

        code = data.get("code", -1)
        if code == 0:
            uname = data.get("data", {}).get("uname", "未知用户")
            level = data.get("data", {}).get("level_info", {}).get("current_level", "?")
            return CheckinResult(
                success=True,
                message=f"登录成功 | 用户：{uname} | 等级：LV{level}",
            )
        elif code == -101:
            return CheckinResult(success=False, message="SESSDATA 已过期，请重新登录")
        elif code == -412:
            return CheckinResult(success=False, message="请求被 B 站风控拦截（-412），请稍后重试")
        else:
            msg = data.get("message", "未知错误")
            return CheckinResult(success=False, message=f"签到失败（code={code}）: {msg}")

    @staticmethod
    def _get_sessdata(credentials: dict) -> str:
        """从凭证中提取 SESSDATA。

        优先从登录保存的 Cookie 列表读取，回退到手动填写的字段。

        Args:
            credentials: 凭证 dict。

        Returns:
            SESSDATA 值；未找到时返回空字符串。
        """
        raw = credentials.get("cookies")
        if raw:
            try:
                cookies = json.loads(raw)
                for c in cookies:
                    if c.get("name") == "SESSDATA":
                        return c.get("value", "")
            except (ValueError, TypeError):
                pass
        return (credentials.get("sessdata") or "").strip()


plugin = BilibiliPlugin()
