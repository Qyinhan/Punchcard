"""抖音扫码登录会话：无头浏览器打开抖音主站，获取二维码并监听手机确认。

流程：
1. show_qr()：后台线程拉起 Chromium 打开 https://www.douyin.com/；
2. 触发登录弹窗并定位二维码元素，提取 Base64 图片，更新 stage="qr"；
3. 循环轮询探测：
   - 若出现「需在手机上进行确认」等文本，标记 scanned=True，通知前端提示用户手机端确认；
   - 若检测到上下文 Cookie 中出现 .douyin.com 域的 sessionid，标记 stage="success" 并返回清洗后的 Cookies；
4. 超时（默认 180s）或用户取消时，自动销毁 Chromium 实例与后台线程。

调试文件说明：
- 截图 (login_debug_*.png)：失败时自动保存在 data/debug/ 下，最多保留 10 个，超限自动清理最旧的。
- HTML dump (login_debug_*.html)：仅在设置 PUNCHCARD_DEBUG_LOGIN=1 时保存。
- 截图路径只写入服务端日志，不暴露给前端（避免泄露服务器文件系统结构）。
"""

import base64
import logging
import os
import queue
import threading
import time

from playwright.sync_api import sync_playwright

from .browser import _launch_kwargs, _new_context, sanitize_cookies

logger = logging.getLogger(__name__)

LOGIN_URL = "https://www.douyin.com/"
DEFAULT_TIMEOUT_MS = 60_000
QR_WAIT_SECONDS = 180  # 扫码与确认的最长等待时间（秒）

# 二维码元素候选选择器
QR_IMG_SELECTORS = (
    '#animate_qrcode_container img',
    '#douyin_login_comp_scan_code img',
    'img[aria-label="二维码"]',
    'img[aria-label*="二维码"]',
    'img[aria-label*="扫码"]',
    'img[src*="qrcode"]',
    'img[src*="qr-code"]',
    'img[src*="qr_code"]',
    '[class*="qrcode"] img',
    '[class*="qr-code"] img',
)
QR_TAB_TEXTS = ("扫码登录",)


class LoginSession:
    """抖音主站扫码登录会话。

    通过命令队列与独立浏览器线程通信：HTTP 层调用立即返回，
    浏览器线程串行执行并更新状态，前端通过 status() 轮询进度。
    """

    # 2026-08 实测：抖音主站以 sessionid 作为有效登录凭证。
    # 若后续改用 sessionid_ss 等 Cookie 名，在此集合中添加。
    _SESSION_COOKIE_NAMES: frozenset = frozenset({"sessionid"})

    def __init__(self, account_id: int) -> None:
        self.account_id = account_id
        self._cmd: queue.Queue = queue.Queue()
        self._state: dict = {}
        self._state_lock = threading.Lock()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name=f"douyin-login-{account_id}"
        )
        self._created_at = time.time()
        # 取消信号：close() 时立即置位，轮询内检测后提前退出，无需等待最长 180s
        self._cancel = threading.Event()

    # ---------- HTTP 层（任意线程可调用） ----------
    def start(self) -> None:
        """启动浏览器线程。"""
        self._thread.start()

    def show_qr(self) -> None:
        """投递「展示二维码」命令。"""
        self._cmd.put(("qr", {}, None))

    def send_code(self, phone: str = "") -> None:
        """兼容接口：统一走扫码登录。"""
        self.show_qr()

    def solve_captcha(self, **_) -> None:
        """兼容接口：扫码登录无需滑块验证。"""
        pass

    def submit_code(self, code: str = "") -> None:
        """投递「提交验证码」命令（二次验证「收验证码」路线）。"""
        self._cmd.put(("code", {"code": code}, None))

    def close(self) -> None:
        """投递「关闭」命令，结束浏览器线程。"""
        self._cancel.set()  # 立即通知长轮询退出，无需等队列空出
        self._cmd.put(("close", {}, None))

    def status(self) -> dict:
        """返回当前会话状态副本（线程安全）。"""
        with self._state_lock:
            return dict(self._state)

    # ---------- 浏览器线程 ----------
    def _run(self) -> None:
        """浏览器线程主循环：初始化浏览器，随后串行消费命令队列。"""
        playwright = sync_playwright().start()
        browser = None
        try:
            browser = playwright.chromium.launch(**_launch_kwargs())
            context = _new_context(browser)
            context.set_default_timeout(DEFAULT_TIMEOUT_MS)
            page = context.new_page()
            page.goto(LOGIN_URL, wait_until="domcontentloaded")
            self._context = context
            self._page = page
            self._set_state({"stage": "initializing"})
            logger.info("抖音登录会话已就绪（账户 %s）", self.account_id)
        except Exception as exc:  # noqa: BLE001
            logger.exception("抖音登录浏览器初始化失败（账户 %s）", self.account_id)
            self._set_state({"stage": "failed", "error": f"浏览器初始化失败: {exc}"})
            if browser is not None:
                try:
                    browser.close()
                except Exception:  # noqa: BLE001
                    pass
            playwright.stop()
            return

        while True:
            command, payload, _ = self._cmd.get()
            if command == "close":
                break
            try:
                result = self._dispatch(command, payload)
            except Exception as exc:  # noqa: BLE001
                logger.exception("登录命令 %s 失败（账户 %s）", command, self.account_id)
                result = {"stage": "failed", "error": f"{command} 失败: {exc}"}
            result.setdefault("stage", "failed")
            self._set_state(result)

        try:
            browser.close()
        except Exception:  # noqa: BLE001
            pass
        playwright.stop()

    def _dispatch(self, command: str, payload: dict) -> dict:
        """按命令名分发到对应流程方法。"""
        if command == "qr":
            return self._do_qr_login()
        if command == "code":
            return self._do_submit_code(payload.get("code", ""))
        raise RuntimeError(f"未知命令: {command}")

    def _set_state(self, state: dict) -> None:
        """线程安全地更新会话状态。"""
        with self._state_lock:
            self._state = state

    # ---------- 扫码主流程 ----------
    def _do_qr_login(self) -> dict:
        """打开主站登录弹窗，获取二维码图片给前端，轮询等待扫码与手机确认完成登录。"""
        page = self._page
        # 确保打开登录弹窗
        self._ensure_login_modal(page)

        deadline = time.time() + QR_WAIT_SECONDS
        last_qr = ""
        popup_first_seen = False   # 用于首次出现弹窗时 dump 调试信息
        confirm_attempts = 0       # 已尝试点击次数
        choice_seen = False        # 选择界面专属文本是否出现过（出现过才允许切输入框）
        MAX_CONFIRM_ATTEMPTS = 40  # 最多重试次数（覆盖整个扫码等待期，避免早期点空后永久停滞）

        while time.time() < deadline:
            if self._cancel.is_set():
                raise RuntimeError("登录已取消")
            cookies = self._context.cookies()
            if self._has_session_cookie(cookies):
                logger.info("抖音扫码登录成功（账户 %s）", self.account_id)
                return {"stage": "success", "cookies": sanitize_cookies(cookies)}
            if page.is_closed():
                raise RuntimeError("页面已关闭，登录中断")

            # 检测验证方式选择弹窗（扫码后出现的「发登录提示/收验证码」选择界面）
            popup_visible = self._has_confirmation_popup(page)
            # 「选择界面」专属文本（排除短信 Tab 的"获取验证码"等通用词）：
            # 只有它出现过，才允许把二维码替换为验证码输入框
            choice_seen = choice_seen or self._has_verify_choice_text(page)

            if popup_visible:
                # 弹窗内已出现验证码输入框（点「收验证码」后）→ 切回前端让用户输入。
                # 三重条件缺一不可：已抓到过二维码 + 选择界面文本出现过 + 检测到输入框。
                # 否则主登录弹窗自带的短信/密码输入框会提前把二维码切成输入框
                if last_qr != "" and choice_seen and self._find_code_input(page) is not None:
                    logger.info("检测到二次验证码输入框（账户 %s）", self.account_id)
                    self._dump_html(page, "code_input")
                    return {"stage": "code", "sent": True, "device_code": True}
                # 首次出现：保存调试快照
                if not popup_first_seen:
                    popup_first_seen = True
                    logger.info("检测到验证方式选择弹窗（账户 %s）", self.account_id)
                    self._save_debug_screenshot(page)
                    self._dump_html(page, "qr_confirm_dialog")

                # 持续重试点击，直到弹窗消失或超出上限
                if confirm_attempts < MAX_CONFIRM_ATTEMPTS:
                    confirm_attempts += 1
                    try:
                        clicked = self._click_device_confirm(page)
                        page.wait_for_timeout(800)
                        if clicked:
                            logger.info(
                                "已点击验证方式选项（第 %d 次，账户 %s）",
                                confirm_attempts, self.account_id,
                            )
                        else:
                            logger.warning(
                                "未找到可点击的验证方式选项（第 %d 次，账户 %s）",
                                confirm_attempts, self.account_id,
                            )
                    except Exception:  # noqa: BLE001
                        logger.warning(
                            "点击验证方式弹窗失败（第 %d 次，账户 %s）",
                            confirm_attempts, self.account_id,
                        )

            # 已扫码状态：仅当确实抓到过二维码且「选择界面」出现过才进入，
            # 避免弹窗误判在二维码未抓到前就锁死"已扫码"（只显示加载动画）
            is_scanned = (
                last_qr != ""
                and (
                    choice_seen
                    or self._page_has_text(page, "需在手机上进行确认")
                    or self._page_has_text(page, "请在手机端确认")
                )
            )
            if is_scanned:
                self._set_state({
                    "stage": "qr",
                    "qr_image": last_qr,
                    "scanned": True,
                    "message": "二维码已扫码，请在手机抖音 APP 中完成确认登录…",
                })
            else:
                # 只认原生二维码元素（data:image Base64），兜底容器截图不算"抓到过二维码"，
                # 否则登录弹窗容器截图会污染 last_qr，导致未扫码就误判已扫码而提前切换输入框
                qr = self._qr_snapshot(page, native_only=True)
                if qr and qr != last_qr:
                    last_qr = qr
                    self._set_state({"stage": "qr", "qr_image": qr})

            page.wait_for_timeout(1500)

        self._save_debug_screenshot(page)
        self._dump_html(page, "qr_timeout")
        scanned_any = popup_first_seen or confirm_attempts > 0
        raise RuntimeError(
            "扫码登录超时" + ("，请重试" if scanned_any else "，二维码可能已过期，请点击重新获取")
        )

    def _has_confirmation_popup(self, page) -> bool:
        """宽松检测扫码后的二次验证选择弹窗（发登录提示 / 收验证码）。

        主站常驻风控 SDK（uc-secure/verifycenter 脚本、uc-ui 容器）的特征
        都会判为"疑似弹窗"，从而让主循环持续尝试点击验证方式选项；
        真实弹窗出现后，点击即可命中「发送验证码/收验证码」按钮。
        （此策略为实测有效的"能收到验证码"版本行为，勿再收紧。）

        Returns:
            True 表示检测到（或疑似）二次验证弹窗。
        """
        # 1. 常驻风控 SDK 特征（几乎恒真，保证持续尝试点击）
        try:
            if "verifycenter" in page.url:
                return True
        except Exception:  # noqa: BLE001
            pass
        try:
            if page.locator('[class*="uc-ui"]').count() > 0:
                return True
        except Exception:  # noqa: BLE001
            pass
        for frame in page.frames:
            try:
                srcs = frame.locator("script[src]").evaluate_all(
                    "els => els.map(e => e.src || '')"
                )
                for src in srcs:
                    if any(k in src for k in ("verifycenter", "uc-secure")):
                        return True
            except Exception:  # noqa: BLE001
                continue
        # 2. 明确弹窗文本（含 iframe）
        popup_keywords = (
            "发登录提示", "发提示", "发送提示", "登录提示",
            "收验证码", "接收验证码", "发送验证码", "获取验证码",
            "需在手机上进行确认", "请在手机端确认", "取消登录",
            "选择验证方式", "验证方式", "短信验证", "手机验证码",
        )
        return any(self._page_has_text(page, kw) for kw in popup_keywords)

    def _has_verify_choice_text(self, page) -> bool:
        """检测「选择验证方式」界面专属文本（扫码后弹出的选择界面）。

        仅匹配选择界面独有的选项文字，刻意排除短信 Tab 的通用按钮词
        （获取验证码/发送验证码/短信验证码等），避免主登录弹窗的短信
        表单被误判成二次验证选择界面。

        Returns:
            True 表示页面可见文本（含 iframe）出现过选择界面文字。
        """
        choice_keywords = (
            "发登录提示", "发提示", "发送提示", "登录提示", "推送通知",
            "收验证码", "接收验证码",
            "需在手机上进行确认", "请在手机端确认", "取消登录",
            "选择验证方式", "验证方式",
        )
        return any(self._page_has_text(page, kw) for kw in choice_keywords)

    def _ensure_login_modal(self, page) -> None:
        """确保主站登录弹窗已打开并处于扫码登录状态。"""
        page.wait_for_timeout(2000)
        # 若已有二维码元素可见，直接返回
        for sel in QR_IMG_SELECTORS:
            try:
                loc = page.locator(sel)
                if loc.count() > 0 and loc.first.is_visible():
                    return
            except Exception:  # noqa: BLE001
                continue

        # 尝试点击「登录」按钮打开弹窗
        try:
            btn = page.get_by_text("登录", exact=True)
            if btn.count() > 0:
                for el in btn.all()[:4]:
                    try:
                        if el.is_visible():
                            el.click(timeout=3000)
                            page.wait_for_timeout(2000)
                            break
                    except Exception:  # noqa: BLE001
                        continue
        except Exception:  # noqa: BLE001
            pass

        # 若弹窗未默认处于扫码Tab，点击「扫码登录」
        try:
            tab = page.get_by_text("扫码登录", exact=False)
            if tab.count() > 0:
                tab.first.click(timeout=2000)
                page.wait_for_timeout(1000)
        except Exception:  # noqa: BLE001
            pass

    def _page_has_text(self, page, text: str) -> bool:
        """页面（含所有 iframe frame）可见文本是否包含指定内容。"""
        try:
            if text in (page.inner_text("body", timeout=2000) or ""):
                return True
        except Exception:  # noqa: BLE001
            pass
        for frame in page.frames:
            try:
                body = frame.locator("body").inner_text(timeout=800)
                if text in (body or ""):
                    return True
            except Exception:  # noqa: BLE001
                continue
        return False

    def _qr_snapshot(self, page, native_only: bool = False) -> str:
        """提取登录二维码，优先读 src 的 Base64，回退为元素截图。

        Args:
            page: Playwright Page 对象。
            native_only: 仅提取二维码元素本身（data:image Base64 或元素截图），
                不包含容器兜底截图。用于主循环判断"是否已抓到过二维码"，
                避免把登录弹窗等容器的截图误当成二维码。
        """
        for sel in QR_IMG_SELECTORS:
            try:
                loc = page.locator(sel)
                for i in range(min(loc.count(), 4)):
                    el = loc.nth(i)
                    try:
                        if el.is_visible():
                            # 1. 优先提取原生 Base64 Data URL (data:image/...)
                            src = el.get_attribute("src") or ""
                            if "data:image/" in src and "base64," in src:
                                return src.split("base64,", 1)[1]
                            # 2. 回退截图
                            box = el.bounding_box()
                            if box and box["width"] > 40:
                                data = el.screenshot(timeout=5000)
                                if data:
                                    return base64.b64encode(data).decode("ascii")
                    except Exception:  # noqa: BLE001
                        continue
            except Exception:  # noqa: BLE001
                continue

        if native_only:
            return ""

        # 弹窗或登录框容器截图兜底
        for sel in (
            '[class*="semi-modal-content"]',
            '[class*="login-modal"]',
            '[class*="login-wrap"]',
            '[class*="modal-content"]',
        ):
            try:
                loc = page.locator(sel)
                for i in range(min(loc.count(), 3)):
                    el = loc.nth(i)
                    try:
                        if el.is_visible():
                            data = el.screenshot(timeout=5000)
                            if data:
                                return base64.b64encode(data).decode("ascii")
                    except Exception:  # noqa: BLE001
                        continue
            except Exception:  # noqa: BLE001
                continue

        return ""

    def _save_debug_screenshot(self, page) -> bool:
        """失败时保存页面截图，便于排查（存到 data/debug/）。

        自动清理超过 10 个的旧截图，避免无限堆积。
        截图路径仅写入服务端日志，不暴露给前端。

        Returns:
            截图是否保存成功。
        """
        try:
            from app.core.config import DATA_DIR

            debug_dir = DATA_DIR / "debug"
            debug_dir.mkdir(exist_ok=True)

            # 清理旧截图：保留最新 10 个（按修改时间排序）
            existing = sorted(
                debug_dir.glob(f"login_debug_{self.account_id}_*.png"),
                key=lambda p: p.stat().st_mtime,
            )
            for old in existing[:-9]:  # 保留 9 个，加上本次共 10 个
                try:
                    old.unlink()
                except OSError:
                    pass

            path = debug_dir / f"login_debug_{self.account_id}_{int(time.time())}.png"
            page.screenshot(path=str(path))
            # 路径仅写日志，不返回给调用方拼入前端消息
            logger.info("已保存登录调试截图: %s", path)
            return True
        except Exception:  # noqa: BLE001
            return False

    @staticmethod
    def _has_session_cookie(cookies: list[dict]) -> bool:
        """判断 Cookie 列表中是否包含 douyin.com 域名的有效登录 Cookie。"""
        return any(
            c.get("name") in LoginSession._SESSION_COOKIE_NAMES
            and "douyin.com" in (c.get("domain") or "")
            for c in cookies
        )

    def _find_code_input(self, page):
        """在所有 frame 中查找可见的验证码输入框（二次验证「收验证码」路线）。

        Args:
            page: Playwright 页面对象。

        Returns:
            匹配的输入框元素；未找到时返回 None。
        """
        selectors = (
            # 二次验证面板（#uc-second-verify）优先：主登录弹窗短信 Tab 里
            # 有同 id/placeholder 的输入框且 DOM 序靠前，曾被误命中（填错框）
            '#uc-second-verify input[placeholder*="验证码"]',
            '#uc-second-verify input[maxlength="6"]',
            'input[placeholder*="验证码"]',
            'input[placeholder*="验证"]',
            'input[maxlength="6"]',
            'input[maxlength="4"]',
        )
        for frame in page.frames:
            for sel in selectors:
                try:
                    loc = frame.locator(sel)
                    for i in range(min(loc.count(), 3)):
                        el = loc.nth(i)
                        try:
                            if el.is_visible():
                                return el
                        except Exception:  # noqa: BLE001
                            continue
                except Exception:  # noqa: BLE001
                    continue
        return None

    def _click_submit_button(self, page, anchor=None) -> bool:
        """点击二次验证弹窗里的提交/确认按钮（优先验证码输入框所在 frame）。

        Args:
            page: Playwright 页面对象。
            anchor: 验证码输入框元素；提供时优先在其所属 frame 内查找，
                避免误点主页面导航栏等处的「登录」按钮。

        Returns:
            是否成功点击了至少一个元素。
        """
        frames = list(page.frames)
        if anchor is not None:
            try:
                owner = anchor.owner_frame()
                if owner is not None and owner in frames:
                    frames.remove(owner)
                    frames.insert(0, owner)
            except Exception:  # noqa: BLE001
                pass

        # ── 策略 1：JS 在各 frame 内点击按钮状元素（覆盖 div 实现的按钮）──
        js = """() => {
            // 「验证」是二次验证面板主按钮的文案，优先匹配；
            // 面板外的「登录」等词是主站导航/登录弹窗的，不能点
            const texts = ['验证', '确认', '下一步', '确定', '登录', '提交'];
            const isVisible = el => el && el.offsetParent !== null;
            const isDisabled = el => el.disabled || el.getAttribute('aria-disabled') === 'true'
                || /disabled|disable/.test((el.className || '').toString());
            // 限定在二次验证面板内找，避免点中主站同名按钮
            const scope = document.querySelector('#uc-second-verify') || document;
            const candidates = [
                ...scope.querySelectorAll('button'),
                ...scope.querySelectorAll('[role="button"]'),
                ...scope.querySelectorAll('[class*="btn"], [class*="Btn"]'),
                ...scope.querySelectorAll('[class*="button"], [class*="Button"]'),
                ...scope.querySelectorAll('[class*="primary"], [class*="Primary"]'),
                ...scope.querySelectorAll('[class*="submit"], [class*="Submit"]'),
                ...scope.querySelectorAll('[class*="confirm"], [class*="Confirm"]'),
            ];
            for (const t of texts) {
                for (const el of candidates) {
                    const txt = (el.textContent || '').trim();
                    // 文本长度 <= 6 既防止点中聚合大量子文本的容器，
                    // 也能过滤「验证码」（3字）之外更长文案的按钮
                    if (txt && txt.length <= 6 && txt.includes(t) && isVisible(el) && !isDisabled(el)) {
                        el.click();
                        return txt;
                    }
                }
            }
            return null;
        }"""
        for frame in frames:
            try:
                clicked = frame.evaluate(js)
                if clicked:
                    logger.info("JS 点击提交按钮「%s」成功（账户 %s）", clicked, self.account_id)
                    return True
            except Exception:  # noqa: BLE001
                continue

        # ── 策略 2：Playwright 角色定位（frame 优先级同序）────────────────
        for text in ("验证", "确认", "下一步", "确定", "登录", "提交"):
            for frame in frames:
                try:
                    loc = frame.get_by_role("button", name=text, exact=False)
                    for btn in loc.all()[:4]:
                        try:
                            if btn.is_visible():
                                btn.click(timeout=2500)
                                logger.info("点击提交按钮「%s」成功（账户 %s）", text, self.account_id)
                                return True
                        except Exception:  # noqa: BLE001
                            continue
                except Exception:  # noqa: BLE001
                    continue
        return False

    def _do_submit_code(self, code: str) -> dict:
        """填入二次验证码并提交，随后轮询等待 sessionid 完成登录。"""
        page = self._page
        code = str(code).strip()
        if not code:
            raise RuntimeError("请输入验证码")
        self._set_state({"stage": "initializing", "message": "正在验证登录…"})
        el = self._find_code_input(page)
        if el is None:
            self._save_debug_screenshot(page)
            raise RuntimeError("未找到验证码输入框，请重试")

        # 用真实键盘输入：React 受控组件只认键盘事件，程序式 fill 可能
        # 写不进组件状态，导致提交被忽略或提交后输入框被清空
        try:
            el.click(timeout=3000)
            page.wait_for_timeout(200)
            page.keyboard.type(code, delay=80)
        except Exception:  # noqa: BLE001
            logger.warning("键盘输入验证码失败，回退 fill（账户 %s）", self.account_id)
            el.fill(code, timeout=5000)
        page.wait_for_timeout(300)
        try:
            typed_len = len(el.input_value() or "")
        except Exception:  # noqa: BLE001
            typed_len = -1
        logger.info("验证码已填入（长度 %s，账户 %s）", typed_len, self.account_id)
        if typed_len == 0:
            self._save_debug_screenshot(page)
            raise RuntimeError("验证码未能填入输入框，请重试")
        if typed_len < 0:
            # input_value() 抛异常通常意味着元素已 detach（页面正在跳转），
            # 记录警告后继续尝试提交，避免因读取失败而放弃已完成的输入
            logger.warning(
                "无法读取输入框当前值（元素可能已 detach），继续尝试提交（账户 %s）",
                self.account_id,
            )

        # 提交方式 1：输入框内回车（部分验证表单直接提交）
        try:
            el.press("Enter", timeout=1500)
        except Exception:  # noqa: BLE001
            pass
        if self._wait_session(page, 3):
            logger.info("抖音登录成功（回车提交，账户 %s）", self.account_id)
            return {"stage": "success", "cookies": sanitize_cookies(self._context.cookies())}

        # 提交方式 2：点击确认/登录按钮（优先输入框所在 frame）
        # Enter 后页面可能重建 DOM，重新定位输入框以获得有效 anchor，
        # 避免 stale ElementHandle 导致 owner_frame() 推断失效
        fresh_el = self._find_code_input(page)
        clicked = self._click_submit_button(page, anchor=fresh_el or el)
        logger.info("提交按钮点击结果=%s（账户 %s）", clicked, self.account_id)
        page.wait_for_timeout(2000)
        self._save_debug_screenshot(page)  # 诊断：提交后的页面状态，路径写入日志

        deadline = time.time() + QR_WAIT_SECONDS
        while time.time() < deadline:
            if self._cancel.is_set():
                raise RuntimeError("登录已取消")
            cookies = self._context.cookies()
            if self._has_session_cookie(cookies):
                logger.info("抖音登录成功（账户 %s）", self.account_id)
                return {"stage": "success", "cookies": sanitize_cookies(cookies)}
            if page.is_closed():
                raise RuntimeError("页面已关闭，登录中断")
            # 抖音明确报错（验证码错误/过期等）时立即抛出真实原因，
            # 不再干等 180s 超时
            err = self._code_error_text(page, fresh_el or el)
            if err:
                self._save_debug_screenshot(page)
                raise RuntimeError(f"抖音提示「{err}」，请重新获取验证码再试")
            page.wait_for_timeout(1500)
        self._save_debug_screenshot(page)
        raise RuntimeError("登录超时，请检查验证码是否正确")

    def _wait_session(self, page, seconds: float) -> bool:
        """在指定秒数内轮询等待 sessionid Cookie 出现。

        Returns:
            True 表示已登录成功。
        """
        deadline = time.time() + seconds
        while time.time() < deadline:
            if self._has_session_cookie(self._context.cookies()):
                return True
            if page.is_closed():
                return False
            page.wait_for_timeout(500)
        return False

    def _code_error_text(self, page, anchor) -> str:
        """在验证码输入框所在 frame 内查找抖音返回的错误提示文本。

        Returns:
            匹配到的错误关键词；无则返回空串。
        """
        keywords = (
            "验证码错误", "验证码不正确", "请输入正确的验证码",
            "验证码已过期", "验证码失效", "验证码已失效",
            "操作频繁", "稍后再试",
        )
        frames = []
        try:
            owner = anchor.owner_frame()
            if owner is not None:
                frames.append(owner)
        except Exception:  # noqa: BLE001
            pass
        # 二次验证面板有专属错误提示区，非空即真实失败原因
        for frame in (frames or page.frames):
            try:
                tip = frame.locator('[class*="err_tip"]').first.inner_text(timeout=800)
                if tip and tip.strip():
                    return tip.strip()
            except Exception:  # noqa: BLE001
                pass
        # 关键词匹配限定在二次验证面板容器内，避免误命中主站通用文案（如"稍后再试"）
        for frame in (frames or page.frames):
            for kw in keywords:
                try:
                    panel = frame.locator("#uc-second-verify")
                    target = panel if panel.count() > 0 else frame.locator("body")
                    text = target.inner_text(timeout=800)
                    if kw in (text or ""):
                        return kw
                except Exception:  # noqa: BLE001
                    continue
        return ""

    def _click_device_confirm(self, page) -> bool:
        """点击字节跳动 MFA 二次验证界面里的验证按钮（短信验证码优先）。

        扫码后出现的 MFA 界面（second_verification_web）由 JS 动态渲染，
        包含「收验证码」（短信）或「发登录提示」（推送）两种验证方式。
        优先点击短信路线：短信会弹出验证码输入框，前端可切换让用户输入；
        推送路线只能干等手机 App 确认，收不到推送时会一直卡住。

        Returns:
            是否成功点击了至少一个元素。
        """
        all_frames = page.frames

        # ── 等待 MFA JS 渲染完成 ────────────────────────────────────────
        page.wait_for_timeout(1500)

        # ── 策略 1：通过 JS 直接点击可见的主要按钮（短信优先，推送兜底）───
        try:
            clicked = page.evaluate("""() => {
                const candidates = [
                    ...document.querySelectorAll('button'),
                    ...document.querySelectorAll('[class*="uc-ui"] [class*="btn"]'),
                    ...document.querySelectorAll('[class*="uc-ui"] [class*="submit"]'),
                    ...document.querySelectorAll('[class*="primary"]'),
                ];
                // 短信优先：短信路线会弹出验证码输入框，前端可切换让用户输入；
                // 只用「验证码」做关键词，避免「发送登录提示」被「发送」误命中。
                const groups = [['验证码'], ['推送', '发提示', '发登录']];
                for (const keys of groups) {
                    for (const el of candidates) {
                        const text = (el.textContent || '').trim();
                        // 长度限制防止误点包含关键词的长文案按钮（如推送授权弹窗）
                        if (text && text.length <= 10 && el.offsetParent !== null && keys.some(k => text.includes(k))) {
                            el.click();
                            return text;
                        }
                    }
                }
                return null;
            }""")
            if clicked:
                logger.info("MFA JS点击按钮「%s」成功（账户 %s）", clicked, self.account_id)
                page.wait_for_timeout(600)
                return True
        except Exception:  # noqa: BLE001
            pass

        # ── 策略 2：文本搜索点击（优先短信验证码 → 推送兜底）──────────────
        option_priority = ("获取验证码", "发送验证码", "收验证码", "短信验证码", "接收验证码")
        option_fallback = ("发登录提示", "发提示", "发送提示", "登录提示", "推送通知")
        submit_texts = ("确认", "下一步", "确定", "发送", "提交")
        option_clicked = False

        for group in (option_priority, option_fallback):
            if option_clicked:
                break
            for frame in all_frames:
                if option_clicked:
                    break
                for text in group:
                    try:
                        loc = frame.get_by_text(text, exact=False)
                        for el in loc.all()[:6]:
                            try:
                                if el.is_visible():
                                    el.click(timeout=3000)
                                    page.wait_for_timeout(400)
                                    option_clicked = True
                                    logger.debug("点击选项「%s」成功", text)
                                    break
                            except Exception:  # noqa: BLE001
                                continue
                    except Exception:  # noqa: BLE001
                        continue
                    if option_clicked:
                        break

        # ── 策略 3：点击提交/确认按钮 ────────────────────────────────────
        submit_clicked = False
        for frame in all_frames:
            if submit_clicked:
                break
            for text in submit_texts:
                try:
                    loc = frame.get_by_role("button", name=text)
                    if loc.count() == 0:
                        loc = frame.get_by_text(text, exact=True)
                    for el in loc.all()[:4]:
                        try:
                            if el.is_visible():
                                el.click(timeout=2000)
                                page.wait_for_timeout(400)
                                submit_clicked = True
                                logger.debug("点击提交按钮「%s」成功", text)
                                break
                        except Exception:  # noqa: BLE001
                            continue
                except Exception:  # noqa: BLE001
                    continue
                if submit_clicked:
                    break

        return option_clicked or submit_clicked

    def _dump_html(self, page, tag: str) -> None:
        """把当前页面 DOM 存到 data/debug/login_debug_*.html，便于排查弹窗结构。

        主文档与各 iframe 分开保存（MFA 弹窗可能渲染在 iframe 内，
        page.content() 只有主文档）。

        仅在 ``PUNCHCARD_DEBUG_LOGIN=1`` 时执行，默认关闭，避免生产环境
        无限累积含敏感信息的 HTML 文件。
        """
        if os.getenv("PUNCHCARD_DEBUG_LOGIN") != "1":
            return
        try:
            from app.core.config import DATA_DIR

            debug_dir = DATA_DIR / "debug"
            debug_dir.mkdir(exist_ok=True)
            ts = int(time.time())
            path = debug_dir / f"login_debug_{self.account_id}_{tag}_{ts}.html"
            path.write_text(page.content(), encoding="utf-8")
            logger.info("已保存页面 HTML: %s", path)
            for idx, frame in enumerate(page.frames):
                if frame == page.main_frame:
                    continue
                try:
                    fpath = debug_dir / f"login_debug_{self.account_id}_{tag}_frame{idx}_{ts}.html"
                    fpath.write_text(frame.content(), encoding="utf-8")
                    logger.info("已保存 iframe HTML: %s", fpath)
                except Exception:  # noqa: BLE001
                    continue
        except Exception:  # noqa: BLE001
            logger.warning("保存页面 HTML 失败")
