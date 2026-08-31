"""B 站短信验证码登录会话（纯 HTTP，无需浏览器）。

流程：
1. send_code(phone)            → 调 Bilibili captcha API，获取极验参数返给前端
2. solve_captcha(validate,...) → 前端完成极验后，调 Bilibili 发短信接口
3. submit_code(code)           → 提交短信验证码，调 Bilibili 登录接口，保存 Cookie
"""

import logging
import threading

import httpx

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.bilibili.com/",
    "Origin": "https://www.bilibili.com",
}

_CAPTCHA_URL = "https://passport.bilibili.com/x/passport-login/captcha"
_SMS_SEND_URL = "https://passport.bilibili.com/x/passport-login/web/sms/send"
_SMS_LOGIN_URL = "https://passport.bilibili.com/x/passport-login/web/sms/login"


class LoginSession:
    """B 站短信验证码登录会话（每个实例对应一次登录流程）。

    对外接口均为异步触发（后台线程执行），立即返回；前端通过 status() 轮询进度。
    """

    def __init__(self, account_id: int) -> None:
        self.account_id = account_id
        self._state: dict = {"stage": "initializing"}
        self._lock = threading.Lock()
        self._phone: str = ""
        self._captcha_key: str = ""

    # ---------- 外部调用接口（任意线程均可调用，立即返回）----------

    def start(self) -> None:
        pass  # HTTP 方式无需预启动

    def send_code(self, phone: str) -> None:
        """后台获取极验参数，完成后 stage 变为 captcha。

        Args:
            phone: 登录手机号。
        """
        threading.Thread(target=self._do_send_code, args=(phone,), daemon=True).start()

    def solve_captcha(self, validate: str = "", seccode: str = "",
                      challenge: str = "", token: str = "", **_) -> None:
        """前端极验通过后调用，后台发送短信，完成后 stage 变为 code。

        Args:
            validate: 极验 validate 参数。
            seccode: 极验 seccode 参数。
            challenge: 极验 challenge 参数。
            token: 获取极验参数时返回的 token。
        """
        threading.Thread(
            target=self._do_send_sms,
            args=(validate, seccode, challenge, token),
            daemon=True,
        ).start()

    def submit_code(self, code: str) -> None:
        """提交短信验证码，后台执行登录，完成后 stage 变为 success/failed。

        Args:
            code: 短信验证码。
        """
        threading.Thread(target=self._do_login, args=(code,), daemon=True).start()

    def close(self) -> None:
        pass

    def status(self) -> dict:
        """返回当前会话状态副本（线程安全）。"""
        with self._lock:
            return dict(self._state)

    # ---------- 后台工作线程 ----------

    def _set_state(self, state: dict) -> None:
        """线程安全地更新会话状态。"""
        with self._lock:
            self._state = state

    def _do_send_code(self, phone: str) -> None:
        """获取极验参数并保存到状态，供前端渲染滑块。"""
        phone = str(phone).strip()
        if not phone:
            self._set_state({"stage": "failed", "error": "请填写手机号"})
            return
        self._phone = phone
        try:
            with httpx.Client(timeout=15, headers=_HEADERS) as client:
                resp = client.get(_CAPTCHA_URL, params={"source": "main_web"})
                resp.raise_for_status()
                data = resp.json()
            if data.get("code") != 0:
                raise RuntimeError(data.get("message") or "获取极验参数失败")
            d = data.get("data") or {}
            # Bilibili 返回字段名有两套：gee_gt/gee_challenge 或 gt/challenge
            gt = d.get("gee_gt") or d.get("gt", "")
            challenge = d.get("gee_challenge") or d.get("challenge", "")
            token = d.get("token", "")
            if not gt or not challenge:
                raise RuntimeError("极验参数缺失，请重试")
            self._set_state({
                "stage": "captcha",
                "geetest": {"gt": gt, "challenge": challenge, "token": token},
            })
            logger.info("账户 %s 极验参数已获取", self.account_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("账户 %s 获取极验参数失败: %s", self.account_id, exc)
            self._set_state({"stage": "failed", "error": f"获取验证码失败: {exc}"})

    def _do_send_sms(self, validate: str, seccode: str,
                     challenge: str, token: str) -> None:
        """携带极验结果发送短信验证码。"""
        try:
            with httpx.Client(timeout=15, headers=_HEADERS) as client:
                resp = client.post(
                    _SMS_SEND_URL,
                    data={
                        "cid": "86",
                        "tel": self._phone,
                        "source": "main_web",
                        "token": token,
                        "challenge": challenge,
                        "validate": validate,
                        "seccode": seccode,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
            if data.get("code") != 0:
                raise RuntimeError(data.get("message") or "发送短信失败")
            self._captcha_key = ((data.get("data") or {}).get("captcha_key") or "")
            self._set_state({"stage": "code", "sent": True})
            logger.info("账户 %s 短信验证码已发送", self.account_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("账户 %s 发送短信失败: %s", self.account_id, exc)
            self._set_state({"stage": "failed", "error": f"发送短信失败: {exc}"})

    def _do_login(self, code: str) -> None:
        """提交短信验证码完成登录，成功后把 Cookie 写入状态。"""
        code = str(code).strip()
        if not code:
            self._set_state({"stage": "failed", "error": "请输入验证码"})
            return
        try:
            with httpx.Client(timeout=15, headers=_HEADERS, follow_redirects=True) as client:
                resp = client.post(
                    _SMS_LOGIN_URL,
                    data={
                        "cid": "86",
                        "tel": self._phone,
                        "code": code,
                        "source": "main_web",
                        "captcha_key": self._captcha_key,
                        "keep": "true",
                    },
                )
                resp.raise_for_status()
                data = resp.json()
            if data.get("code") != 0:
                raise RuntimeError(data.get("message") or "登录失败，请检查验证码")
            cookies = [
                {"name": name, "value": value, "domain": ".bilibili.com", "path": "/"}
                for name, value in resp.cookies.items()
            ]
            if not any(c["name"] == "SESSDATA" for c in cookies):
                raise RuntimeError("登录成功但未获取到 SESSDATA，请重试")
            self._set_state({"stage": "success", "cookies": cookies})
            logger.info("账户 %s B站登录成功", self.account_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("账户 %s B站登录失败: %s", self.account_id, exc)
            self._set_state({"stage": "failed", "error": f"登录失败: {exc}"})
