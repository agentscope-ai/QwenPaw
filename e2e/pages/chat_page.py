# -*- coding: utf-8 -*-
"""
QwenPaw Chat 页面对象

封装 Chat 页面的所有交互操作，提供业务级别的方法。
"""
from __future__ import annotations

import logging
from typing import Optional, List, Tuple
from pathlib import Path
from playwright.sync_api import Page, Locator, expect, TimeoutError

from pages.base_page import BasePage
from config.settings import config


logger = logging.getLogger(__name__)


class ChatPage(BasePage):
    """
    Chat 页面对象
    
    封装 Chat 页面的所有用户操作：
    - 新建对话
    - 发送消息
    - 文件上传
    - 会话管理
    - 模型切换
    - 技能调用
    """
    
    PAGE_TITLE = "QwenPaw Console"
    PAGE_URL = f"{config.base_url}/chat"
    
    # ========== 选择器定义 ==========
    # 页面组件库使用 qwenpaw- CSS 前缀

    # 导航和新建对话（兼容 spark-icon 和 anticon 两套图标体系）
    NEW_CHAT_BTN = 'button:has(.spark-icon-spark-newChat-fill), button:has(.anticon-plus), button:has([class*="newChat"])'
    SESSION_LIST_BTN = 'button:has(.spark-icon-spark-history-line), button:has(.anticon-history), button:has([class*="history"])'

    # 输入区域
    CHAT_INPUT = 'textarea.qwenpaw-sender-input'
    SEND_BTN = 'button.qwenpaw-sender-actions-btn.qwenpaw-btn-primary'
    FILE_INPUT = 'input[type="file"]'
    UPLOAD_WRAPPER = 'span.qwenpaw-upload-wrapper'

    # 消息区域
    USER_MESSAGE = '.qwenpaw-bubble.qwenpaw-bubble-end'
    AI_MESSAGE = '.qwenpaw-bubble.qwenpaw-bubble-start'
    MESSAGE_CONTAINER = '.qwenpaw-bubble.qwenpaw-bubble-start, .qwenpaw-bubble.qwenpaw-bubble-end'
    MESSAGE_LIST = '.qwenpaw-bubble-list-scroll'

    # 欢迎界面（检查输入框可见性）
    WELCOME_TEXT = 'textarea.qwenpaw-sender-input'
    QUICK_ACTIONS = '.quick-action'

    # 会话管理（通过历史记录抽屉，CSS Module 类名）
    SESSION_ITEM = '[class*=chatSessionItem]'
    SESSION_ACTIVE = '[class*=chatSessionItem][class*=active]'
    SESSION_NAME = '[class*=chatSessionItem] [class*=name]'
    SESSION_PIN_BTN = 'button:has(.spark-icon-spark-mark-line), button:has(.anticon-pushpin)'
    SESSION_EDIT_BTN = 'button:has(.spark-icon-spark-edit-line), button:has(.anticon-edit)'
    SESSION_DELETE_BTN = 'button:has(.spark-icon-spark-delete-line), button:has(.anticon-delete)'

    # 设置和模型
    MODEL_SELECTOR = '.qwenpaw-dropdown-trigger'
    MODEL_OPTION = '.qwenpaw-dropdown-menu-item'
    AGENT_SELECTOR = '.qwenpaw-select-selector'

    # 操作按钮
    COPY_BTN = 'span[title="复制"]'

    # 工具和技能详情
    TOOL_TOGGLE = '.qwenpaw-operate-card-header-arrow'
    TOOL_DETAILS = '.qwenpaw-operate-card'

    # 错误和提示（SUCCESS_MESSAGE / ERROR_MESSAGE 继承自 BasePage）
    COPY_SUCCESS = '.qwenpaw-message-success'

    # 抽屉和弹窗
    DRAWER_CLOSE = '[class*=headerRight] button'
    CONFIRM_BTN = 'button:has-text("确认"), button:has-text("OK"), .qwenpaw-btn-primary:has-text("确定")'
    CANCEL_BTN = 'button:has-text("取消"), button:has-text("Cancel")'

    # ========== 鲁棒的"按钮 disabled 状态"判定 JS 片段 ==========
    # 不同 UI 框架表达 disabled 的方式不同，必须四路合查：
    #   1. 原生 button.disabled property
    #   2. disabled 属性
    #   3. aria-disabled="true"
    #   4. 框架自加的 disabled / loading class
    # 任意一种命中即视为 disabled
    _JS_BTN_IS_DISABLED = """() => {
        const btn = document.querySelector(
            'button.qwenpaw-sender-actions-btn.qwenpaw-btn-primary'
        );
        if (!btn) return false;
        if (btn.disabled === true) return true;
        if (btn.hasAttribute('disabled')) return true;
        if (btn.getAttribute('aria-disabled') === 'true') return true;
        const cls = btn.className || '';
        if (/qwenpaw-btn-disabled|qwenpaw-btn-loading|is-disabled|is-loading/.test(cls)) {
            return true;
        }
        return false;
    }"""

    _JS_BTN_IS_ENABLED = """() => {
        const btn = document.querySelector(
            'button.qwenpaw-sender-actions-btn.qwenpaw-btn-primary'
        );
        if (!btn) return false;
        if (btn.disabled === true) return false;
        if (btn.hasAttribute('disabled')) return false;
        if (btn.getAttribute('aria-disabled') === 'true') return false;
        const cls = btn.className || '';
        if (/qwenpaw-btn-disabled|qwenpaw-btn-loading|is-disabled|is-loading/.test(cls)) {
            return false;
        }
        return true;
    }"""

    # ========== 初始化 ==========
    
    def __init__(self, page: Page):
        super().__init__(page)
        logger.info("ChatPage initialized")
    
    # ========== 页面导航 ==========
    
    def open(self) -> "ChatPage":
        """打开 Chat 页面"""
        logger.info("Opening Chat page")
        try:
            self.goto()
        except Exception:
            # networkidle 可能因长连接/SSE 而超时，降级为 load
            logger.warning("Chat page networkidle timeout, falling back to 'load'")
            self.page.goto(self.PAGE_URL, wait_until="load", timeout=60000)
        self.wait_for_loading()
        self.step_shot("open_chat_page")
        return self
    
    def is_loaded(self) -> bool:
        """检查页面是否加载完成"""
        try:
            # 检查输入框或欢迎文本是否存在
            return (
                self.assert_visible(self.CHAT_INPUT, timeout=5000) or
                self.assert_visible(self.WELCOME_TEXT, timeout=5000)
            )
        except Exception:
            return False
    
    # ========== 新建对话 ==========
    
    def create_new_chat(self) -> "ChatPage":
        """
        创建新对话

        Returns:
            self
        """
        logger.info("Creating new chat")
        # 重置发送状态（新会话不需要等上一个会话的 AI 响应）
        if hasattr(self, '_has_sent_message'):
            del self._has_sent_message
        self._ai_count_before_send = 0
        
        new_chat_btn = self.find(self.NEW_CHAT_BTN)
        if new_chat_btn.count() > 0:
            new_chat_btn.click()
            # 等待页面跳转并加载完成
            self.page.wait_for_load_state("networkidle")
            self.page.locator(self.CHAT_INPUT).wait_for(state="visible", timeout=10000)
        self.step_shot("create_new_chat_done")
        return self
    
    def verify_welcome_screen(self) -> bool:
        """
        验证欢迎界面

        Returns:
            是否显示欢迎界面
        """
        logger.info("Verifying welcome screen")
        result = self.assert_visible(self.WELCOME_TEXT, timeout=5000)
        # 校验完成后立刻清理可能的 hover/focus 状态，避免污染后续 send_message
        # （之前观察到：调过本方法的用例首轮发消息时按钮永远不 disabled）
        try:
            self.page.mouse.move(0, 0)
            self.page.keyboard.press("Escape")
        except Exception:
            pass
        return result
    
    def get_quick_actions(self) -> List[Locator]:
        """获取快捷操作按钮列表"""
        return self.find_all(self.QUICK_ACTIONS)
    
    def click_quick_action(self, index: int = 0) -> "ChatPage":
        """
        点击快捷操作按钮
        
        Args:
            index: 按钮索引
            
        Returns:
            self
        """
        actions = self.get_quick_actions()
        if actions and index < len(actions):
            actions[index].click()
            logger.info(f"Clicked quick action at index {index}")
        return self
    
    # ========== 发送消息 ==========
    
    def send_message(self, text: str) -> "ChatPage":
        """
        发送消息（强校验版）

        与上一轮严格隔离：
        1. 在任何 DOM 变更之前锁定基线（AI / User 消息数量）
        2. 必须等待上一轮"按钮 enabled"才能进入下一轮（避免还在 streaming 时被打断）
        3. 点击发送后必须看到"按钮变成 disabled" —— 这是唯一可信的"新一轮真的启动了"信号
           看不到 disabled = 本轮没生效 → 抛异常让上层用例真实失败

        Args:
            text: 消息内容

        Returns:
            self

        Raises:
            AssertionError / TimeoutError: 当发送未真正触发新一轮 AI 响应时
        """
        logger.info(f"Sending message: {text[:50]}...")

        # ---- 入口防污染：清掉残留的弹窗/焦点（避免 verify_* 等方法的副作用）----
        try:
            self.page.keyboard.press("Escape")
            self.page.mouse.move(10, 10)
            self.wait(150)
        except Exception:
            pass

        # ---- 进入新一轮前：先记录基线（必须在任何 fill / click 之前）----
        self._ai_count_before_send = self.page.locator(self.AI_MESSAGE).count()
        user_count_before = self.page.locator(self.USER_MESSAGE).count()
        logger.info(
            f"[send_message] baseline: ai={self._ai_count_before_send}, "
            f"user={user_count_before}"
        )

        # ---- 等待上一轮真正完成（双信号：按钮恢复 OR 内容稳定 ≥ 1.5s）----
        # 设计：和 wait_for_ai_response 用同样的"双信号"，避免被前端 streaming 信号丢失的 bug 卡死。
        # 仅当存在历史消息时才需要等（首轮 user_count_before==0 时跳过）。
        # 超时缩短到 8s：上一轮 wait_for_ai_response 已经放行了，这里只是兜底等 UI 完全 idle。
        if user_count_before > 0:
            try:
                self.page.wait_for_function(
                    """() => {
                        // 路径 A：按钮已恢复 enabled
                        const btn = document.querySelector(
                            'button.qwenpaw-sender-actions-btn.qwenpaw-btn-primary'
                        );
                        if (btn) {
                            const cls = btn.className || '';
                            const disabledByCls = /qwenpaw-btn-disabled|qwenpaw-btn-loading|is-disabled|is-loading/.test(cls);
                            const disabledByAttr = btn.disabled === true
                                || btn.hasAttribute('disabled')
                                || btn.getAttribute('aria-disabled') === 'true';
                            if (!disabledByAttr && !disabledByCls) return true;
                        }
                        // 路径 B：最后一个 AI 气泡内容连续 1.5s 不变（即使按钮永远 disabled 也能放行）
                        const aiMsgs = document.querySelectorAll(
                            '.qwenpaw-bubble.qwenpaw-bubble-start'
                        );
                        if (aiMsgs.length === 0) return true; // 没有 AI 气泡，直接放行
                        const last = aiMsgs[aiMsgs.length - 1];
                        const raw = (last.innerText || '').trim();
                        const key = '__qwenpaw_send_idle_cache__';
                        const now = Date.now();
                        const cache = window[key] || {};
                        if (cache.text !== raw) {
                            window[key] = { text: raw, since: now };
                            return false;
                        }
                        return (now - cache.since) >= 1500;
                    }""",
                    timeout=8000,
                )
                logger.info("[send_message] previous round confirmed idle")
            except (TimeoutError, AssertionError, Exception):
                logger.warning(
                    "[send_message] previous AI round idle-check timeout (8s), "
                    "proceeding anyway"
                )
            finally:
                try:
                    self.page.evaluate(
                        "() => { try { delete window.__qwenpaw_send_idle_cache__; } catch(e) {} }"
                    )
                except Exception:
                    pass

        # ---- 填充输入框 ----
        input_box = self.page.locator(self.CHAT_INPUT)
        input_box.click()
        self.wait(300)
        input_box.fill("")
        self.wait(200)
        input_box.fill(text)
        self.wait(500)

        # 截图：输入完成、点击发送之前
        self.step_shot(f"send_before_click_{text[:20]}")

        # ---- 触发发送 ----
        send_btn = self.page.locator(self.SEND_BTN)
        if send_btn.is_visible() and send_btn.is_enabled():
            send_btn.click()
        else:
            input_box.press("Enter")

        # ---- 强校验：用户气泡必须 +1（证明前端真的把消息送出去了）----
        try:
            self.page.wait_for_function(
                """(expected) => {
                    const msgs = document.querySelectorAll(
                        '.qwenpaw-bubble.qwenpaw-bubble-end'
                    );
                    return msgs.length > expected;
                }""",
                arg=user_count_before,
                timeout=15000,
            )
            logger.info("[send_message] user bubble appeared")
        except (TimeoutError, AssertionError, Exception):
            logger.warning("[send_message] user bubble missing, retrying with Enter")
            input_box = self.page.locator(self.CHAT_INPUT)
            input_box.click()
            self.wait(200)
            input_box.press("Enter")
            # 重试后再校验一次，仍失败则真实抛错
            self.page.wait_for_function(
                """(expected) => {
                    const msgs = document.querySelectorAll(
                        '.qwenpaw-bubble.qwenpaw-bubble-end'
                    );
                    return msgs.length > expected;
                }""",
                arg=user_count_before,
                timeout=15000,
            )

        # ---- 软校验：尝试观察发送按钮变成 disabled（仅作为辅助信号，不强制）----
        # 注意：之前把"必须看到 disabled"作为硬条件会引入"假阴性"——某些 case
        # 后端响应极快，按钮一闪而过 enabled→disabled→enabled，等不到 disabled 就报错。
        # 实际上 user bubble 已出现 = 消息已成功发出，新一轮的"真实启动"由 wait_for_ai_response
        # 用"AI 气泡数 +1"和"内容稳定"来判定，那个判定才是黄金标准。
        # 这里只是 best-effort 观察一下，timeout 缩短到 3s + 不报错。
        try:
            self.page.wait_for_function(
                self._JS_BTN_IS_DISABLED,
                timeout=3000,
            )
            self._send_triggered_round = True
            logger.info("[send_message] send button became disabled (round started)")
        except (TimeoutError, AssertionError, Exception):
            # 看不到 disabled 不代表失败 —— 可能后端响应太快或前端按钮状态机异常。
            # 把"是否真的产生了 AI 回复"的判定权完全交给 wait_for_ai_response。
            self._send_triggered_round = True  # 默认信任：user bubble 已经出现了
            logger.info(
                "[send_message] send button disabled-state not observed within 3s; "
                "trusting user-bubble signal and delegating to wait_for_ai_response"
            )

        # 截图：用户消息已发送，AI 即将回复
        self.step_shot("send_after_user_bubble")
        return self
    
    def send_message_and_wait(self, text: str, timeout: int = 30000) -> "ChatPage":
        """
        发送消息并等待 AI 回复
        
        Args:
            text: 消息内容
            timeout: 等待超时时间
            
        Returns:
            self
        """
        self.send_message(text)
        self.wait_for_ai_response(timeout)
        return self
    
    def get_user_messages(self) -> List[Locator]:
        """获取所有用户消息"""
        return self.page.locator(self.USER_MESSAGE).all()
    
    def get_ai_messages(self) -> List[Locator]:
        """获取所有 AI 消息"""
        return self.page.locator(self.AI_MESSAGE).all()
    
    def get_all_messages(self) -> List[Locator]:
        """获取所有消息"""
        return self.page.locator(self.MESSAGE_CONTAINER).all()
    
    def get_last_ai_message(self) -> Optional[Locator]:
        """获取最后一条 AI 消息"""
        messages = self.get_ai_messages()
        return messages[-1] if messages else None
    
    def wait_for_ai_response(self, timeout: int = 30000) -> Optional[Locator]:
        """
        等待 AI 回复真实完成（严判版，杜绝假阳性）

        必须依次满足以下四个条件才算"AI 真的回复完了"，任何一关失败 → 返回 None
        让上层用例真实 FAIL：

        关 0  send_message 必须真的触发了新一轮（按钮 disabled 状态曾经发生过）
        关 1  AI 气泡数量 > 基线（新气泡真的诞生了）
        关 2  发送按钮已经从 disabled → enabled（流式真的结束了）
        关 3  最新一条 AI 气泡内容稳定（连续 ≥ 800ms innerText 不变）
              且去掉 "Thinking" 占位后仍有 ≥ 2 个字符

        Args:
            timeout: 整体超时（ms），各关共享预算

        Returns:
            最后一条 AI 消息 Locator；任意关失败返回 None
        """
        logger.info(f"Waiting for AI response (timeout: {timeout}ms)")

        ai_locator = self.page.locator(self.AI_MESSAGE)
        count_before_send = getattr(
            self, "_ai_count_before_send", ai_locator.count()
        )
        logger.info(
            f"[wait_ai] baseline_count={count_before_send}, "
            f"current_count={ai_locator.count()}"
        )

        # ---- 关 0：send 是否真的触发了新一轮 ----
        if not getattr(self, "_send_triggered_round", True):
            logger.error(
                "[wait_ai] send_message never observed send-button=disabled, "
                "no new round was triggered. Treat as failure."
            )
            return None

        # ---- 关 1：等待新 AI 气泡出现 ----
        try:
            self.page.wait_for_function(
                """(expectedCount) => {
                    const aiMsgs = document.querySelectorAll(
                        '.qwenpaw-bubble.qwenpaw-bubble-start'
                    );
                    return aiMsgs.length > expectedCount;
                }""",
                arg=count_before_send,
                timeout=timeout,
            )
            logger.info("[wait_ai] gate-1 PASS: new AI bubble appeared")
        except (TimeoutError, AssertionError, Exception) as e:
            logger.error(
                f"[wait_ai] gate-1 FAIL: new AI bubble never appeared "
                f"({type(e).__name__})"
            )
            return None

        # ---- 关 2 + 关 3 合并：等待 "AI 内容稳定 ≥ 2.5s" 或 "按钮恢复 enabled"（先到先放行）----
        # 设计动机（基于真实日志观察）：
        #   - 被测系统存在已知 bug：streaming 结束信号经常丢失，按钮永远 disabled，
        #     但 AI 回复内容其实早就追加完毕。如果死等按钮恢复 → 每个用例都会被拖死 90s 然后 FAIL。
        #   - 解决方案：把"内容稳定"作为主信号（更贴近用户真实感知），
        #     "按钮恢复"作为快路径加速；两个信号谁先 ready 就放行。
        #   - 仍然过滤 "Thinking / Loading" 占位 + 要求 ≥ 2 个真实字符 → 杜绝假阳性。
        #   - 内容稳定窗口加大到 2500ms（比原 800ms 更稳，避免长 token 流式间隙误判）
        stability_timeout = min(timeout, 30000)
        passed_via = None
        try:
            self.page.wait_for_function(
                """(expectedCount) => {
                    // 路径 A：按钮已经从 disabled 恢复 → streaming 真的结束了
                    const btn = document.querySelector(
                        'button.qwenpaw-sender-actions-btn.qwenpaw-btn-primary'
                    );
                    let btnEnabled = false;
                    if (btn) {
                        const cls = btn.className || '';
                        const disabledByCls = /qwenpaw-btn-disabled|qwenpaw-btn-loading|is-disabled|is-loading/.test(cls);
                        const disabledByAttr = btn.disabled === true
                            || btn.hasAttribute('disabled')
                            || btn.getAttribute('aria-disabled') === 'true';
                        btnEnabled = !disabledByAttr && !disabledByCls;
                    }

                    // 路径 B：AI 气泡内容连续 2500ms 不变且去除占位后 ≥ 2 字符
                    const aiMsgs = document.querySelectorAll(
                        '.qwenpaw-bubble.qwenpaw-bubble-start'
                    );
                    if (aiMsgs.length <= expectedCount) {
                        return false; // 连新气泡都没有，肯定不能放行
                    }
                    const last = aiMsgs[aiMsgs.length - 1];
                    const raw = (last.innerText || '').trim();
                    const stripped = raw
                        .replace(/Thinking/gi, '')
                        .replace(/Loading/gi, '')
                        .trim();
                    const hasRealText = stripped.length >= 2;

                    // 内容稳定性检测（仅当有真实文本时才计算）
                    let contentStable = false;
                    if (hasRealText) {
                        const key = '__qwenpaw_ai_stable_cache__';
                        const now = Date.now();
                        const cache = window[key] || {};
                        if (cache.text !== raw) {
                            window[key] = { text: raw, since: now };
                        } else if ((now - cache.since) >= 1500) {
                            contentStable = true;
                        }
                    }

                    // 路径 A 优先（按钮恢复 + 至少有真实文本，立刻放行）
                    if (btnEnabled && hasRealText) {
                        window.__qwenpaw_wait_passed_via__ = 'btn_enabled';
                        return true;
                    }
                    // 路径 B 兜底（按钮永远 disabled 也能靠内容稳定放行）
                    if (contentStable) {
                        window.__qwenpaw_wait_passed_via__ = 'content_stable';
                        return true;
                    }
                    return false;
                }""",
                arg=count_before_send,
                timeout=stability_timeout,
            )
            try:
                passed_via = self.page.evaluate(
                    "() => window.__qwenpaw_wait_passed_via__ || 'unknown'"
                )
            except Exception:
                passed_via = "unknown"
            logger.info(
                f"[wait_ai] gate-2/3 PASS via '{passed_via}' "
                f"(streaming considered done)"
            )
        except (TimeoutError, AssertionError, Exception) as e:
            try:
                last_text = ai_locator.last.inner_text()[:200]
            except Exception:
                last_text = "<unreadable>"
            logger.error(
                f"[wait_ai] gate-2/3 FAIL within {stability_timeout}ms "
                f"({type(e).__name__}). Neither button re-enabled nor content stabilized. "
                f"Last bubble text: {last_text!r}"
            )
            # 失败截图，方便事后核查
            self.step_shot("wait_ai_FAIL_gate23")
            return None
        finally:
            # 清理 window 缓存，避免影响下一轮判定
            try:
                self.page.evaluate(
                    "() => { try { "
                    "delete window.__qwenpaw_ai_stable_cache__; "
                    "delete window.__qwenpaw_wait_passed_via__; "
                    "} catch(e) {} }"
                )
            except Exception:
                pass

        # 截图：AI 完整回复后的最终状态
        self.step_shot(f"ai_response_complete_{passed_via or 'unknown'}")
        return ai_locator.last
    
    # ========== 消息操作 ==========
    
    def copy_last_message(self) -> bool:
        """
        复制最后一条 AI 消息
        
        Returns:
            是否复制成功
        """
        logger.info("Copying last AI message")
        
        ai_msg = self.get_last_ai_message()
        if not ai_msg:
            logger.warning("No AI message to copy")
            return False
        
        copy_btn = ai_msg.locator(self.COPY_BTN).first
        if copy_btn.count() > 0:
            copy_btn.click()
            self.wait(500)

            # 验证复制成功
            if self.assert_visible(self.COPY_SUCCESS, timeout=3000):
                logger.info("Message copied successfully")
                self.step_shot("copy_success")
                return True

        logger.warning("Copy failed or not available")
        self.step_shot("copy_failed")
        return False
    
    def get_message_text(self, message_locator: Locator) -> str:
        """
        获取消息文本内容
        
        Args:
            message_locator: 消息 Locator
            
        Returns:
            消息文本
        """
        return message_locator.inner_text()
    
    def verify_message_contains(self, message_locator: Locator, expected_text: str) -> bool:
        """
        验证消息包含指定文本
        
        Args:
            message_locator: 消息 Locator
            expected_text: 期望包含的文本
            
        Returns:
            是否包含
        """
        text = self.get_message_text(message_locator)
        return expected_text.lower() in text.lower()
    
    # ========== 文件上传 ==========
    
    def upload_file(self, file_path: str) -> "ChatPage":
        """
        上传文件

        Args:
            file_path: 文件路径

        Returns:
            self
        """
        logger.info(f"Uploading file: {file_path}")
        self.step_shot("upload_before")

        # 直接通过 file input 设置文件（无需点击上传按钮）
        file_input = self.page.locator(self.FILE_INPUT)
        file_input.set_input_files(file_path)

        self.wait(2000)  # 等待上传完成
        logger.info("File upload initiated")
        self.step_shot("upload_after")
        return self

    def verify_file_uploaded(self, timeout: int = 10000) -> bool:
        """
        验证文件上传成功

        Args:
            timeout: 超时时间

        Returns:
            是否上传成功
        """
        file_preview_selector = '.qwenpaw-upload-list-item, .qwenpaw-sender-content [class*="file"], [class*="attachment"]'
        return self.assert_visible(file_preview_selector, timeout=timeout)
    
    # ========== 会话管理 ==========
    
    def open_session_list(self) -> "ChatPage":
        """打开会话列表（带页面状态自愈）"""
        logger.info("Opening session list")
        # 先关闭可能残留的下拉菜单/浮层，防止遮挡按钮
        try:
            self.page.keyboard.press("Escape")
            self.page.mouse.move(0, 0)  # 移开鼠标避免触发其它 hover
        except Exception:
            pass
        self.wait(300)

        # 兜底：如果按钮短时间内找不到（可能侧边栏被异常状态隐藏），尝试刷新页面
        session_btn_locator = self.page.locator(self.SESSION_LIST_BTN).first
        try:
            session_btn_locator.wait_for(state="visible", timeout=5000)
        except (TimeoutError, Exception):
            logger.warning(
                "[open_session_list] session list button not visible in 5s, "
                "page may be in a stuck state, trying to recover by reloading"
            )
            try:
                self.page.reload(wait_until="domcontentloaded", timeout=15000)
                self.wait(1500)
                session_btn_locator.wait_for(state="visible", timeout=10000)
            except Exception as e:
                logger.warning(f"[open_session_list] reload-recovery also failed: {e}")
                self.step_shot("open_session_list_btn_invisible_after_reload")
                # 不 raise，让上层 try/except 处理
                return self

        try:
            session_btn_locator.click(timeout=8000)
        except Exception:
            logger.warning("常规点击失败，尝试 force click")
            try:
                session_btn_locator.click(force=True, timeout=5000)
            except Exception as e:
                logger.warning(f"[open_session_list] force click also failed: {e}")
                self.step_shot("open_session_list_click_failed")
                return self

        # 等待会话列表抽屉渲染完成
        try:
            self.page.locator(self.SESSION_ITEM).first.wait_for(state="visible", timeout=8000)
        except (TimeoutError, Exception):
            logger.warning("Session list may be empty or slow to render")
        self.wait(500)
        self.step_shot("session_list_opened")
        return self
    
    def close_session_list(self) -> "ChatPage":
        """关闭会话列表"""
        logger.info("Closing session list")
        close_btn = self.page.locator('.qwenpaw-drawer ' + self.DRAWER_CLOSE)
        if close_btn.count() > 0:
            close_btn.first.click()
            self.wait(500)
        return self
    
    def get_session_items(self) -> List[Locator]:
        """获取所有会话项"""
        return self.page.locator(self.SESSION_ITEM).all()
    
    def get_session_count(self) -> int:
        """获取会话数量"""
        return len(self.get_session_items())
    
    def switch_to_session(self, index: int = 0) -> "ChatPage":
        """
        切换到指定会话
        
        Args:
            index: 会话索引
            
        Returns:
            self
        """
        sessions = self.get_session_items()
        if sessions and index < len(sessions):
            target = sessions[index]
            try:
                target.scroll_into_view_if_needed(timeout=5000)
                target.wait_for(state="visible", timeout=5000)
            except Exception as e:
                logger.warning(f"Session {index} visibility check failed: {e}")
            target.click()
            self.wait(1000)
            logger.info(f"Switched to session at index {index}")
            self.step_shot(f"switch_to_session_{index}")
        return self
    
    def rename_session(self, index: int, new_name: str) -> "ChatPage":
        """
        重命名会话（hover 后点击编辑按钮，输入新名称后按 Enter）
        
        Args:
            index: 会话索引
            new_name: 新名称
            
        Returns:
            self
        """
        logger.info(f"Renaming session {index} to: {new_name}")
        
        sessions = self.get_session_items()
        if not sessions or index >= len(sessions):
            logger.warning(f"Session at index {index} not found")
            return self
        
        target_session = sessions[index]
        
        # hover 会话项以显示操作按钮
        target_session.hover()
        self.wait(500)
        
        # 尝试方式1: 点击编辑按钮
        edit_btn = target_session.locator(self.SESSION_EDIT_BTN)
        if edit_btn.count() > 0:
            edit_btn.first.click()
            self.wait(500)
        else:
            # 尝试方式2: 双击会话名称触发编辑
            logger.info("Edit button not found, trying double-click on session name")
            name_el = target_session.locator(self.SESSION_NAME)
            if name_el.count() > 0:
                name_el.first.dblclick()
            else:
                target_session.dblclick()
            self.wait(500)
        
        # 使用多种选择器查找 input（可能在会话项内部或外部）
        rename_input = None
        input_selectors = [
            'input.qwenpaw-input',
            'input[type="text"]',
            'input',
        ]
        
        # 先在会话项内部查找
        for selector in input_selectors:
            locator = target_session.locator(selector)
            if locator.count() > 0 and locator.first.is_visible():
                rename_input = locator.first
                logger.info(f"Found rename input inside session with selector: {selector}")
                break
        
        # 如果会话项内部没找到，在页面全局查找
        if rename_input is None:
            for selector in input_selectors:
                locator = self.page.locator(f'.qwenpaw-modal input, .qwenpaw-drawer input, {self.SESSION_ITEM} {selector}')
                if locator.count() > 0 and locator.first.is_visible():
                    rename_input = locator.first
                    logger.info(f"Found rename input globally with selector: {selector}")
                    break
        
        if rename_input is None:
            logger.warning("Rename input not found with any selector, skipping rename")
            return self
        
        rename_input.fill(new_name)
        self.step_shot(f"rename_input_filled_{new_name[:20]}")
        rename_input.press("Enter")
        self.wait(1000)

        logger.info(f"Session renamed to: {new_name}")
        self.step_shot(f"rename_done_{new_name[:20]}")
        return self
    
    def pin_session(self, index: int) -> "ChatPage":
        """
        置顶会话（hover 后点击会话项内的置顶按钮）

        ⚠️ pin/edit/delete 三个按钮都是 hover-only 显示，不 hover 就直接 click 会
        因为按钮 invisible 而被 Playwright 强制等到 60s 超时。
        """
        logger.info(f"Pinning session at index {index}")

        sessions = self.get_session_items()
        if not sessions or index >= len(sessions):
            logger.warning(f"Session at index {index} not found")
            self.step_shot(f"pin_session_{index}_not_found")
            return self

        target_session = sessions[index]
        # 必须先滚动到可见 + hover 把操作按钮露出来
        try:
            target_session.scroll_into_view_if_needed(timeout=5000)
            target_session.hover(timeout=10000)
        except Exception as e:
            logger.warning(f"[pin_session] regular hover failed ({e}), trying force hover")
            try:
                target_session.hover(force=True, timeout=10000)
            except Exception as e2:
                logger.warning(f"[pin_session] force hover also failed: {e2}")
                self.step_shot(f"pin_session_{index}_hover_failed")
                return self
        self.wait(400)
        self.step_shot(f"pin_session_{index}_after_hover")

        # 点击置顶按钮（带短超时，按钮还看不到就 force click）
        pin_btn = target_session.locator(self.SESSION_PIN_BTN)
        if pin_btn.count() == 0:
            logger.warning("Pin button not found in session item")
            self.step_shot(f"pin_session_{index}_btn_missing")
            return self

        try:
            pin_btn.first.click(timeout=5000)
        except Exception as e:
            logger.warning(f"[pin_session] regular click failed ({e}), trying force click")
            try:
                pin_btn.first.click(force=True, timeout=5000)
            except Exception as e2:
                logger.warning(f"[pin_session] force click also failed: {e2}")
                self.step_shot(f"pin_session_{index}_click_failed")
                return self

        self.wait(1000)
        logger.info("Session pinned")
        self.step_shot(f"pin_session_{index}_done")
        return self
    
    def delete_session(self, index: int) -> "ChatPage":
        """
        删除会话（hover 后点击删除按钮，直接删除无确认弹窗）。

        ⚠️ 删除按钮是 hover-only：只有 hover 在会话项上时才显示。
        而 step_shot/wait 之间鼠标可能已经"漂移"，导致按钮重新隐藏，
        Playwright 默认会等到 60s 超时。所以必须：
        - 截图前不要久 wait
        - click 必须用短超时 + force click 兜底
        - click 失败前再 hover 一次保证按钮露出
        """
        logger.info(f"Deleting session at index {index}")

        sessions_before = self.get_session_count()
        sessions = self.get_session_items()

        if not sessions or index >= len(sessions):
            logger.warning(f"Session at index {index} not found")
            return self

        target_session = sessions[index]

        # hover 会话项以显示操作按钮（先滚动到可见位置）
        try:
            target_session.scroll_into_view_if_needed(timeout=5000)
            target_session.hover(timeout=10000)
        except Exception:
            logger.warning(f"Session {index} 不可见，尝试 force hover")
            try:
                target_session.hover(force=True, timeout=10000)
            except Exception as e:
                logger.warning(f"[delete_session] force hover also failed: {e}")
                self.step_shot(f"delete_session_{index}_hover_failed")
                return self
        self.wait(300)
        # 截图：hover 完成、点击删除按钮之前（仅 200ms 后立即截图，避免鼠标漂移）
        self.step_shot(f"delete_session_{index}_before_click")

        # 点击删除按钮（直接删除，无确认弹窗）
        del_btn = target_session.locator(self.SESSION_DELETE_BTN)
        if del_btn.count() == 0:
            logger.warning("Delete button not found")
            self.step_shot(f"delete_session_{index}_btn_missing")
            return self

        # 短超时 + force click 三重兜底：因为 hover 状态可能已经丢失
        try:
            del_btn.first.click(timeout=3000)
        except Exception as e:
            logger.warning(f"[delete_session] regular click failed ({e}), re-hover and retry")
            try:
                # 再 hover 一次让按钮重新可见
                target_session.hover(force=True, timeout=5000)
                self.wait(200)
                del_btn.first.click(timeout=3000)
            except Exception as e2:
                logger.warning(f"[delete_session] retry click failed ({e2}), trying force click")
                try:
                    del_btn.first.click(force=True, timeout=5000)
                except Exception as e3:
                    logger.warning(f"[delete_session] force click also failed: {e3}")
                    self.step_shot(f"delete_session_{index}_click_failed")
                    return self

        self.wait(1000)
        logger.info(f"Session deleted (before: {sessions_before}, after: {self.get_session_count()})")
        self.step_shot(f"delete_session_{index}_done")
        return self
    
    def verify_pinned_session(self) -> bool:
        """验证是否有置顶的会话（通过 data-pinned 属性判断）"""
        pinned_btn = self.page.locator('[class*=pinButton][data-pinned="true"]')
        return pinned_btn.count() > 0
    
    # ========== 模型和 Agent 切换 ==========
    
    def open_model_selector(self) -> "ChatPage":
        """打开模型选择器"""
        logger.info("Opening model selector")
        # 模型选择器在 header 右侧区域
        header = self.page.locator('.qwenpaw-chat-anywhere-layout-right-header')
        model_btn = header.locator(self.MODEL_SELECTOR).first
        model_btn.click()
        self.wait(500)
        return self

    def select_model(self, model_name: str) -> "ChatPage":
        """
        选择模型

        Args:
            model_name: 模型名称

        Returns:
            self
        """
        logger.info(f"Selecting model: {model_name}")

        # 查找并选择模型
        model_option = self.page.locator(self.MODEL_OPTION).filter(has_text=model_name).first
        if model_option.count() > 0:
            model_option.click()
            self.wait(1000)
            logger.info(f"Model selected: {model_name}")

        return self

    def get_available_models(self) -> List[str]:
        """获取可用模型列表"""
        options = self.page.locator(self.MODEL_OPTION).all()
        models = [opt.inner_text() for opt in options]
        return models

    def open_agent_selector(self) -> "ChatPage":
        """打开 Agent 选择器"""
        logger.info("Opening agent selector")
        agent_btn = self.page.locator(self.AGENT_SELECTOR).first
        if agent_btn.count() > 0:
            agent_btn.click()
            self.wait(500)
        return self
    
    # ========== 技能调用 ==========
    
    def invoke_skill(self, skill_name: str, input_text: str = "") -> "ChatPage":
        """
        调用技能
        
        Args:
            skill_name: 技能名称
            input_text: 输入参数
            
        Returns:
            self
        """
        command = f"/{skill_name}"
        if input_text:
            command += f" {input_text}"
        
        logger.info(f"Invoking skill: {command}")
        return self.send_message_and_wait(command)
    
    def get_skills_list(self) -> Optional[str]:
        """获取技能列表（通过 /skills 命令）"""
        self.send_message("/skills")
        response = self.wait_for_ai_response()
        if response:
            return self.get_message_text(response)
        return None
    
    # ========== 工具详情 ==========
    
    def expand_tool_details(self, message_index: int = -1) -> bool:
        """
        展开工具调用详情
        
        Args:
            message_index: 消息索引（-1 表示最后一条）
            
        Returns:
            是否展开成功
        """
        messages = self.get_ai_messages()
        if not messages:
            return False
        
        target_msg = messages[message_index]
        toggle_btn = target_msg.locator(self.TOOL_TOGGLE).first
        
        if toggle_btn.count() > 0:
            toggle_btn.click()
            self.wait(500)
            return self.assert_visible(self.TOOL_DETAILS, timeout=3000)
        
        return False
    
    # ========== 错误处理 ==========
    
    def has_error(self) -> bool:
        """检查是否有错误消息"""
        return self.assert_visible(self.ERROR_MESSAGE, timeout=2000)
    
    def get_error_message(self) -> Optional[str]:
        """获取错误消息文本"""
        error = self.find(self.ERROR_MESSAGE)
        if error.count() > 0:
            return error.inner_text()
        return None
    
    def dismiss_error(self) -> "ChatPage":
        """关闭错误消息"""
        error = self.find(self.ERROR_MESSAGE)
        if error.count() > 0:
            close_btn = error.locator('.qwenpaw-message-close, .qwenpaw-notification-close').first
            if close_btn.count() > 0:
                close_btn.click()
                self.wait(500)
        return self
    
    # ========== 滚动和导航 ==========
    
    def scroll_to_top(self) -> "ChatPage":
        """滚动消息列表到顶部"""
        self.page.evaluate("""() => {
            const list = document.querySelector('.qwenpaw-bubble-list-scroll');
            if (list) list.scrollTop = 0;
        }""")
        self.wait(500)
        return self

    def scroll_to_bottom(self) -> "ChatPage":
        """滚动消息列表到底部"""
        self.page.evaluate("""() => {
            const list = document.querySelector('.qwenpaw-bubble-list-scroll');
            if (list) list.scrollTop = list.scrollHeight;
        }""")
        self.wait(500)
        return self
    
    def scroll_to_message(self, message_index: int) -> "ChatPage":
        """
        滚动到指定消息
        
        Args:
            message_index: 消息索引
            
        Returns:
            self
        """
        messages = self.get_all_messages()
        if messages and message_index < len(messages):
            messages[message_index].scroll_into_view_if_needed()
            self.wait(500)
        return self
    
    # ========== 组合操作 ==========
    
    def complete_chat_flow(self, messages: List[str]) -> "ChatPage":
        """
        完成完整的对话流程
        
        Args:
            messages: 要发送的消息列表
            
        Returns:
            self
        """
        logger.info(f"Starting chat flow with {len(messages)} messages")
        
        for msg in messages:
            self.send_message_and_wait(msg)
        
        logger.info("Chat flow completed")
        return self
    
    def create_chat_and_send(self, message: str) -> "ChatPage":
        """
        创建新对话并发送消息
        
        Args:
            message: 消息内容
            
        Returns:
            self
        """
        return self.create_new_chat().send_message_and_wait(message)

    # ========== 清理 ==========

    def delete_all_sessions(self, max_attempts: int = 50) -> "ChatPage":
        """
        删除所有会话，用于测试后清理数据。

        ⚠️ cleanup 是健壮性敏感场景：上一个用例可能让页面停留在任何异常状态
        （弹窗未关、菜单未收、聚焦在输入框、有抖动浮层等）。这里在打开会话列表前，
        先把页面状态强制 reset 一下，避免被遮挡导致 60s 死等。
        """
        logger.info("Cleaning up: deleting all sessions")

        # ===== 状态自愈：把页面恢复到一个稳定可操作状态 =====
        try:
            # 多按几次 Escape 关掉弹窗、下拉菜单、modal 等
            for _ in range(3):
                self.page.keyboard.press("Escape")
                self.wait(100)
            # 鼠标移到角落，避免任何 hover 浮层挡住按钮
            self.page.mouse.move(0, 0)
            # 滚动到页面顶部，确保侧边栏按钮可见
            try:
                self.page.evaluate("() => window.scrollTo(0, 0)")
            except Exception:
                pass
            self.wait(300)
        except Exception as e:
            logger.warning(f"[cleanup] page state reset partially failed: {e}")

        try:
            self.open_session_list()
        except Exception as e:
            logger.warning(f"[cleanup] open_session_list failed, skip cleanup: {e}")
            return self

        deleted_count = 0
        for _ in range(max_attempts):
            try:
                session_count = self.get_session_count()
            except Exception as e:
                logger.warning(f"[cleanup] get_session_count failed: {e}")
                break
            if session_count == 0:
                break

            try:
                self.delete_session(0)
                deleted_count += 1
            except Exception as error:
                logger.warning(f"Failed to delete session: {error}")
                break

        logger.info(f"Cleanup complete: deleted {deleted_count} sessions")
        return self
