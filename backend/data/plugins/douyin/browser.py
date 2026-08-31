"""抖音浏览器自动化：同步好友列表、发送消息（文本 / 抖音自定义表情）。

发消息与同步好友统一使用抖音网页版 IM（www.douyin.com/chat）：
- 会话列表 = 有聊天记录的好友（续火花对象通常都在其中）
- 文本：在输入框（Slate 编辑器）输入后回车发送
- 自定义表情（如「续火花」）：消息里写 `[表情名]`，打开表情面板点击对应表情，
  点击即直接发送（自定义表情不走输入框）

登录见 login_session.py（www.douyin.com 扫码登录，Cookie 全域名通用）。
页面 DOM / 类名随抖音改版会变化，失败时返回可读错误。
"""

import logging
import os
import re
import threading

from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)

# 同一时间只允许一个浏览器自动化任务（同步好友/签到）
browser_guard = threading.Semaphore(1)

DEFAULT_TIMEOUT_MS = 120_000
CHAT_URL = "https://www.douyin.com/chat"
HOME_URL = "https://www.douyin.com/"

# ---- www.douyin.com/chat 页面选择器（抖音改版需同步维护）----
CONV_ITEM = "[data-e2e='conversation-item']"
CONV_TITLE = ".conversationConversationItemtitle"
CONV_SCROLL = ".conversationConversationListwrapper"
EDITOR = ".messageEditorinputArea[contenteditable='true']"
EMOJI_BTN = "svg.messageMsgInputiconAction"
EMOJI_ITEM = ".emojiEmojiItememojiItem"
EMOJI_DESC = ".emojiEmojiItememojiItemDesc"


def _launch_kwargs() -> dict:
    """Chromium 启动参数；Linux 服务器以 root 运行时需关闭沙箱（PUNCHCARD_CHROME_NO_SANDBOX=1）。

    Returns:
        Playwright launch 参数字典。
    """
    kwargs: dict = {
        "headless": True,
        "args": ["--disable-blink-features=AutomationControlled"],
    }
    if os.getenv("PUNCHCARD_CHROME_NO_SANDBOX") == "1":
        kwargs["args"] += ["--no-sandbox", "--disable-dev-shm-usage"]
    return kwargs


# 伪装成真实 Chrome，降低被识别为自动化浏览器的概率
CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

_STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
window.chrome = window.chrome || { runtime: {} };
Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en'] });
Object.defineProperty(navigator, 'plugins', { get: () => [
  { name: 'Chrome PDF Plugin' }, { name: 'Chrome PDF Viewer' }, { name: 'Native Client' }
] });
Object.defineProperty(navigator, 'maxTouchPoints', { get: () => 0 });
"""


def _new_context(browser):
    """创建带反检测伪装的新上下文（真实 UA + 隐藏自动化特征）。"""
    ctx = browser.new_context(
        locale="zh-CN",
        timezone_id="Asia/Shanghai",
        viewport={"width": 1400, "height": 900},
        user_agent=CHROME_UA,
    )
    ctx.add_init_script(_STEALTH_JS)
    return ctx


def sanitize_cookies(cookies: list[dict]) -> list[dict]:
    """去掉 Playwright 不支持的 sameSite 字段，避免 add_cookies 报错。

    Args:
        cookies: 原始 Cookie 列表。

    Returns:
        清洗后的 Cookie 列表。
    """
    out = []
    for c in cookies:
        c = dict(c)
        c.pop("sameSite", None)
        out.append(c)
    return out


def _open_chat(cookies: list[dict]):
    """打开注入 Cookie 后的抖音网页版 IM。

    Args:
        cookies: 登录 Cookie 列表。

    Returns:
        (playwright, browser, page) 三元组。
    """
    playwright = sync_playwright().start()
    browser = playwright.chromium.launch(**_launch_kwargs())
    context = _new_context(browser)
    context.set_default_timeout(DEFAULT_TIMEOUT_MS)
    page = context.new_page()
    page.goto(HOME_URL, wait_until="domcontentloaded")
    context.add_cookies(sanitize_cookies(cookies))
    page.goto(CHAT_URL, wait_until="domcontentloaded")
    # 等待会话列表容器出现，比固定等待更可靠；超时降级到固定等待
    try:
        page.wait_for_selector(CONV_SCROLL, timeout=20_000)
    except Exception:  # noqa: BLE001
        page.wait_for_timeout(6000)
    return playwright, browser, page


def _check_logged_in(page) -> None:
    """检测是否被重定向到登录页（Cookie 失效）。

    Args:
        page: Playwright 页面对象。

    Raises:
        RuntimeError: 已跳转到登录相关页面时抛出。
    """
    if any(k in page.url for k in ("login", "passport")):
        raise RuntimeError("Cookie 已失效，请重新登录后再试")


def _scroll_conversations(page, scroller) -> None:
    """在会话列表中滚动一步，加载更多。

    Args:
        page: Playwright 页面对象。
        scroller: 可滚动的会话列表元素。
    """
    try:
        scroller.evaluate("(e) => e.scrollTop += 600")
        page.wait_for_timeout(800)
    except Exception:  # noqa: BLE001
        pass


def _scroll_and_check_stop(page, scroller) -> bool:
    """滚动一步加载更多，并判断是否已到达列表底部。

    Args:
        page: Playwright 页面对象。
        scroller: 可滚动的会话列表元素。

    Returns:
        True 表示滚动后位置未前进（已到底部），调用方可提前终止。
    """
    before = 0
    try:
        before = scroller.evaluate("(e) => e.scrollTop")
    except Exception:  # noqa: BLE001
        pass
    _scroll_conversations(page, scroller)
    try:
        after = scroller.evaluate("(e) => e.scrollTop")
    except Exception:  # noqa: BLE001
        return True
    return after <= before


def _find_conversation(page, target: str) -> None:
    """按标题滚动查找目标会话并点击，到底后提前终止。

    Args:
        page: Playwright 页面对象。
        target: 目标好友昵称。

    Raises:
        RuntimeError: 未在会话列表中找到目标时抛出。
    """
    scroller = page.locator(CONV_SCROLL).first
    try:
        scroller.evaluate("(e) => e.scrollTop = 0")
    except Exception:  # noqa: BLE001
        pass
    page.wait_for_timeout(500)
    for _ in range(30):
        items = page.locator(CONV_ITEM)
        for i in range(items.count()):
            try:
                title = items.nth(i).locator(CONV_TITLE).inner_text(timeout=1500).strip()
                if title == target:
                    items.nth(i).click()
                    page.wait_for_timeout(2500)
                    return
            except Exception:  # noqa: BLE001
                continue
        if _scroll_and_check_stop(page, scroller):
            break
    raise RuntimeError(f"未在会话列表中找到「{target}」")


def _send_text(page, text: str) -> None:
    """在输入框中输入文本并回车发送。

    Args:
        page: Playwright 页面对象。
        text: 待发送的文本。
    """
    ed = page.locator(EDITOR).first
    ed.click(timeout=8000)
    page.wait_for_timeout(300)
    ed.press_sequentially(text)
    page.wait_for_timeout(500)
    ed.press("Enter")
    page.wait_for_timeout(1500)


def _send_emoji(page, name: str) -> None:
    """打开表情面板点击指定自定义表情（点击即发送）。

    Args:
        page: Playwright 页面对象。
        name: 表情名称。

    Raises:
        RuntimeError: 面板中未找到该表情或发送失败时抛出。
    """
    page.locator(EMOJI_BTN).first.click()
    page.wait_for_timeout(2500)
    items = page.locator(EMOJI_ITEM)
    for i in range(items.count()):
        desc = ""
        try:
            desc = items.nth(i).locator(EMOJI_DESC).inner_text(timeout=1500).strip()
        except Exception:  # noqa: BLE001
            continue
        if desc == name:
            items.nth(i).click()
            page.wait_for_timeout(2500)
            # 自定义表情点击即直接发送，面板应随之关闭
            if page.locator(EMOJI_ITEM).count() > 0:
                raise RuntimeError(f"发送表情「{name}」失败（面板未关闭）")
            return
    raise RuntimeError(f"表情面板中未找到「{name}」")


def _parse_message(message: str) -> list[tuple[str, str]]:
    """把消息拆成片段：文本 或 [表情名]。

    Args:
        message: 原始消息文本。

    Returns:
        (类型, 内容) 片段列表，类型为 ``text`` 或 ``emoji``。
    """
    segments: list[tuple[str, str]] = []
    for part in re.split(r"(\[[^\[\]]+\])", message or ""):
        if not part:
            continue
        if part.startswith("[") and part.endswith("]"):
            segments.append(("emoji", part[1:-1]))
        elif part.strip():
            segments.append(("text", part.strip()))
    return segments


def _send_to_one(page, target: str, segments: list[tuple[str, str]]) -> None:
    """向单个好友发送完整消息（按片段依次发送）。

    Args:
        page: Playwright 页面对象。
        target: 目标好友昵称。
        segments: _parse_message 返回的消息片段。
    """
    _find_conversation(page, target)
    for kind, value in segments:
        if kind == "text":
            _send_text(page, value)
        else:
            _send_emoji(page, value)


def list_friends(cookies: list[dict]) -> list[str]:
    """无头浏览器滚动会话列表，收集好友昵称。

    Args:
        cookies: 登录 Cookie 列表。

    Returns:
        好友昵称列表（去重）。
    """
    with browser_guard:
        names: list[str] = []
        seen: set[str] = set()
        playwright, browser, page = None, None, None
        try:
            playwright, browser, page = _open_chat(cookies)
            _check_logged_in(page)
            scroller = page.locator(CONV_SCROLL).first
            for _ in range(40):
                items = page.locator(CONV_ITEM)
                for i in range(items.count()):
                    try:
                        title = items.nth(i).locator(CONV_TITLE).inner_text(timeout=1500).strip()
                        if title and title not in seen:
                            seen.add(title)
                            names.append(title)
                    except Exception:  # noqa: BLE001
                        continue
                if _scroll_and_check_stop(page, scroller):
                    break
            logger.info("同步好友完成，共 %d 个", len(names))
            return names
        finally:
            if browser is not None:
                browser.close()
            if playwright is not None:
                playwright.stop()


def send_messages(cookies: list[dict], targets: list[str], message: str):
    """给每个目标好友发送消息（文本 + [表情名]），返回 CheckinResult。

    Args:
        cookies: 登录 Cookie 列表。
        targets: 目标好友昵称列表。
        message: 待发送的消息文本。

    Returns:
        发送结果 CheckinResult。
    """
    from app.plugins.base import CheckinResult

    if not cookies:
        return CheckinResult(success=False, message="缺少 Cookie，请先完成登录")
    if not targets:
        return CheckinResult(success=False, message="未选择目标好友")
    segments = _parse_message(message)
    if not segments:
        return CheckinResult(success=False, message="消息内容为空")

    if not browser_guard.acquire(blocking=False):
        return CheckinResult(success=False, message="另一个浏览器任务正在执行，请稍后再试")

    sent: list[str] = []
    failed: list[str] = []
    playwright, browser, page = None, None, None
    try:
        playwright, browser, page = _open_chat(cookies)
        _check_logged_in(page)
        for target in targets:
            try:
                _send_to_one(page, target, segments)
                sent.append(target)
                logger.info("已向 %s 发送消息", target)
            except Exception as exc:  # noqa: BLE001
                failed.append(f"{target}: {exc}")
                logger.warning("向 %s 发送失败: %s", target, exc)
        if sent:
            msg = f"已发送给 {len(sent)} 个好友"
            if failed:
                msg += f"；失败 {len(failed)} 个"
            return CheckinResult(success=True, message=msg)
        detail = "；".join(failed) if failed else "未找到任何目标好友"
        return CheckinResult(success=False, message=f"发送失败：{detail}")
    finally:
        if browser is not None:
            browser.close()
        if playwright is not None:
            playwright.stop()
        browser_guard.release()
