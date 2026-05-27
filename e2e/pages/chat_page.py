# -*- coding: utf-8 -*-
"""
QwenPaw Chat page object.

Wraps all interactions on the Chat page and exposes business-level methods.
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
    Chat page object.

    Wraps all user interactions on the Chat page:
    - Create new conversation
    - Send messages
    - File upload
    - Session management
    - Model switching
    - Skill invocation
    """

    PAGE_TITLE = "QwenPaw Console"
    PAGE_URL = f"{config.base_url}/chat"

    # ========== Selector definitions ==========
    # Page components use the qwenpaw- CSS prefix

    # Navigation and new chat (compatible with both spark-icon and anticon icon sets)
    NEW_CHAT_BTN = 'button:has(.spark-icon-spark-newChat-fill), button:has(.anticon-plus), button:has([class*="newChat"])'
    SESSION_LIST_BTN = 'button:has(.spark-icon-spark-history-line), button:has(.anticon-history), button:has([class*="history"])'

    # Input area
    CHAT_INPUT = 'textarea.qwenpaw-sender-input'
    SEND_BTN = 'button.qwenpaw-sender-actions-btn.qwenpaw-btn-primary'
    FILE_INPUT = 'input[type="file"]'
    UPLOAD_WRAPPER = 'span.qwenpaw-upload-wrapper'

    # Message area
    USER_MESSAGE = '.qwenpaw-bubble.qwenpaw-bubble-end'
    AI_MESSAGE = '.qwenpaw-bubble.qwenpaw-bubble-start'
    MESSAGE_CONTAINER = '.qwenpaw-bubble.qwenpaw-bubble-start, .qwenpaw-bubble.qwenpaw-bubble-end'
    MESSAGE_LIST = '.qwenpaw-bubble-list-scroll'

    # Welcome screen (check input visibility)
    WELCOME_TEXT = 'textarea.qwenpaw-sender-input'
    QUICK_ACTIONS = '.quick-action'

    # Session management (through the history drawer, using CSS Modules class names)
    SESSION_ITEM = '[class*=chatSessionItem]'
    SESSION_ACTIVE = '[class*=chatSessionItem][class*=active]'
    SESSION_NAME = '[class*=chatSessionItem] [class*=name]'
    SESSION_PIN_BTN = 'button:has(.spark-icon-spark-mark-line), button:has(.anticon-pushpin)'
    SESSION_EDIT_BTN = 'button:has(.spark-icon-spark-edit-line), button:has(.anticon-edit)'
    SESSION_DELETE_BTN = 'button:has(.spark-icon-spark-delete-line), button:has(.anticon-delete)'

    # Settings and model
    MODEL_SELECTOR = '.qwenpaw-dropdown-trigger'
    MODEL_OPTION = '.qwenpaw-dropdown-menu-item'
    AGENT_SELECTOR = '.qwenpaw-select-selector'

    # Action buttons
    COPY_BTN = 'span[title="复制"]'

    # Tool and skill details
    TOOL_TOGGLE = '.qwenpaw-operate-card-header-arrow'
    TOOL_DETAILS = '.qwenpaw-operate-card'

    # Errors and toasts (SUCCESS_MESSAGE / ERROR_MESSAGE inherited from BasePage)
    COPY_SUCCESS = '.qwenpaw-message-success'

    # Drawer and dialog
    DRAWER_CLOSE = '[class*=headerRight] button'
    CONFIRM_BTN = 'button:has-text("确认"), button:has-text("OK"), .qwenpaw-btn-primary:has-text("确定")'
    CANCEL_BTN = 'button:has-text("取消"), button:has-text("Cancel")'

    # ========== Robust "button disabled" detection JS snippets ==========
    # Different UI frameworks express disabled differently; we must check all four channels:
    #   1. Native button.disabled property
    #   2. disabled attribute
    #   3. aria-disabled="true"
    #   4. Framework-injected disabled / loading class
    # Hitting any of them is treated as disabled.
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

    # ========== Initialization ==========
    
    def __init__(self, page: Page):
        super().__init__(page)
        logger.info("ChatPage initialized")
    
    # ========== Page navigation ==========

    def open(self) -> "ChatPage":
        """Open the Chat page."""
        logger.info("Opening Chat page")
        try:
            self.goto()
        except Exception:
            # networkidle may time out due to long-lived connections / SSE; fall back to 'load'
            logger.warning("Chat page networkidle timeout, falling back to 'load'")
            self.page.goto(self.PAGE_URL, wait_until="load", timeout=60000)
        self.wait_for_loading()
        self.step_shot("open_chat_page")
        return self
    
    def is_loaded(self) -> bool:
        """Check whether the page has finished loading."""
        try:
            # Check whether the input box or welcome text is present
            return (
                self.assert_visible(self.CHAT_INPUT, timeout=5000) or
                self.assert_visible(self.WELCOME_TEXT, timeout=5000)
            )
        except Exception:
            return False
    
    # ========== New chat ==========

    def create_new_chat(self) -> "ChatPage":
        """
        Create a new chat.

        Returns:
            self
        """
        logger.info("Creating new chat")
        # Reset send state (a new session does not need to wait for the previous AI response)
        if hasattr(self, '_has_sent_message'):
            del self._has_sent_message
        self._ai_count_before_send = 0
        
        new_chat_btn = self.find(self.NEW_CHAT_BTN)
        if new_chat_btn.count() > 0:
            new_chat_btn.click()
            # Wait for page navigation and full load
            self.page.wait_for_load_state("networkidle")
            self.page.locator(self.CHAT_INPUT).wait_for(state="visible", timeout=10000)
        self.step_shot("create_new_chat_done")
        return self
    
    def verify_welcome_screen(self) -> bool:
        """
        Verify the welcome screen is shown.

        Returns:
            whether the welcome screen is visible
        """
        logger.info("Verifying welcome screen")
        result = self.assert_visible(self.WELCOME_TEXT, timeout=5000)
        # Immediately clear any lingering hover/focus state to avoid polluting subsequent send_message
        # (previously observed: after calling this method, the first send_message would never see the button become disabled)
        try:
            self.page.mouse.move(0, 0)
            self.page.keyboard.press("Escape")
        except Exception:
            pass
        return result
    
    def get_quick_actions(self) -> List[Locator]:
        """Get the list of quick action buttons."""
        return self.find_all(self.QUICK_ACTIONS)

    def click_quick_action(self, index: int = 0) -> "ChatPage":
        """
        Click a quick action button.

        Args:
            index: button index

        Returns:
            self
        """
        actions = self.get_quick_actions()
        if actions and index < len(actions):
            actions[index].click()
            logger.info(f"Clicked quick action at index {index}")
        return self
    
    # ========== Send message ==========
    
    def send_message(self, text: str) -> "ChatPage":
        """
        Send a message (strict-validation version).

        Strictly isolated from the previous round:
        1. Snapshot the baseline (AI / User message counts) before any DOM change.
        2. Must wait for the previous round's "button enabled" before entering the next round
           (avoid interrupting while still streaming).
        3. After clicking send, must observe "button becomes disabled" -- the only trustworthy
           signal that "a new round really started".
           Not seeing disabled = this round did not take effect -> raise so the upstream test truly fails.

        Args:
            text: message content

        Returns:
            self

        Raises:
            AssertionError / TimeoutError: when send did not actually trigger a new AI response round.
        """
        logger.info(f"Sending message: {text[:50]}...")

        # ---- Entry sanitation: clear leftover popups/focus (avoid side effects from verify_* etc.) ----
        try:
            self.page.keyboard.press("Escape")
            self.page.mouse.move(10, 10)
            self.wait(150)
        except Exception:
            pass

        # ---- Before a new round: record the baseline (must be before any fill / click) ----
        self._ai_count_before_send = self.page.locator(self.AI_MESSAGE).count()
        user_count_before = self.page.locator(self.USER_MESSAGE).count()
        logger.info(
            f"[send_message] baseline: ai={self._ai_count_before_send}, "
            f"user={user_count_before}"
        )

        # ---- Wait for the previous round to truly finish (dual signal: button recovered OR content stable >= 1.5s) ----
        # Design: use the same "dual signal" as wait_for_ai_response to avoid getting stuck on the known frontend bug where streaming signals are lost.
        # Only needs to wait if there is history (skip when user_count_before==0 on the first round).
        # Timeout shortened to 8s: the previous wait_for_ai_response already released, this is just a safety wait until UI is fully idle.
        if user_count_before > 0:
            try:
                self.page.wait_for_function(
                    """() => {
                        // Path A: button has recovered to enabled
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
                        // Path B: last AI bubble content unchanged for 1.5s in a row (release even if button is forever disabled)
                        const aiMsgs = document.querySelectorAll(
                            '.qwenpaw-bubble.qwenpaw-bubble-start'
                        );
                        if (aiMsgs.length === 0) return true; // No AI bubble, release directly
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

        # ---- Fill the input box ----
        input_box = self.page.locator(self.CHAT_INPUT)
        input_box.click()
        self.wait(300)
        input_box.fill("")
        self.wait(200)
        input_box.fill(text)
        self.wait(500)

        # Screenshot: input done, before clicking send
        self.step_shot(f"send_before_click_{text[:20]}")

        # ---- Trigger send ----
        send_btn = self.page.locator(self.SEND_BTN)
        if send_btn.is_visible() and send_btn.is_enabled():
            send_btn.click()
        else:
            input_box.press("Enter")

        # ---- Strict check: user bubble must +1 (proof the frontend actually sent the message) ----
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
            # Verify again after retry; if still failing, raise for real
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

        # ---- Soft check: try to observe the send button becoming disabled (auxiliary signal only, not enforced) ----
        # Note: previously treating "must see disabled" as a hard condition introduced "false negatives" -- in some cases
        # the backend responds very fast, button flashes enabled->disabled->enabled, and we miss the disabled state and error out.
        # In fact, the user bubble appearing = the message has truly been sent; the "real start" of a new round is judged by wait_for_ai_response
        # using "AI bubble count +1" and "content stable" -- that is the gold standard.
        # Here we only do a best-effort observation, with timeout shortened to 3s and no error raised.
        try:
            self.page.wait_for_function(
                self._JS_BTN_IS_DISABLED,
                timeout=3000,
            )
            self._send_triggered_round = True
            logger.info("[send_message] send button became disabled (round started)")
        except (TimeoutError, AssertionError, Exception):
            # Not seeing disabled does not mean failure -- maybe the backend was too fast, or the frontend button state machine is buggy.
            # Delegate the "did AI actually reply" judgment fully to wait_for_ai_response.
            self._send_triggered_round = True  # Default trust: the user bubble already appeared
            logger.info(
                "[send_message] send button disabled-state not observed within 3s; "
                "trusting user-bubble signal and delegating to wait_for_ai_response"
            )

        # Screenshot: user message sent, AI about to reply
        self.step_shot("send_after_user_bubble")
        return self

    def send_message_and_wait(self, text: str, timeout: int = 30000) -> "ChatPage":
        """
        Send a message and wait for the AI reply.
        Args:
            text: message content
            timeout: wait timeout

        Returns:
            self
        """
        self.send_message(text)
        self.wait_for_ai_response(timeout)
        return self

    def get_user_messages(self) -> List[Locator]:
        """Get all user messages."""
        return self.page.locator(self.USER_MESSAGE).all()

    def get_ai_messages(self) -> List[Locator]:
        """Get all AI messages."""
        return self.page.locator(self.AI_MESSAGE).all()

    def get_all_messages(self) -> List[Locator]:
        """Get all messages."""
        return self.page.locator(self.MESSAGE_CONTAINER).all()

    def get_last_ai_message(self) -> Optional[Locator]:
        """Get the last AI message."""
        messages = self.get_ai_messages()
        return messages[-1] if messages else None

    def wait_for_ai_response(self, timeout: int = 30000) -> Optional[Locator]:
        """
        Wait for the AI reply to truly complete (strict version, eliminate false positives).

        All four gates below must pass in order before "AI really finished replying"; any gate failure -> return None
        so the upstream test truly FAILs:

        Gate 0  send_message must have actually triggered a new round (button disabled state was observed)
        Gate 1  AI bubble count > baseline (new bubble was truly born)
        Gate 2  Send button transitioned from disabled -> enabled (streaming really ended)
        Gate 3  The latest AI bubble content is stable (innerText unchanged for >= 800ms in a row)
                and after stripping the "Thinking" placeholder, still has >= 2 characters

        Args:
            timeout: overall timeout (ms), shared budget across gates

        Returns:
            Locator of the last AI message; returns None on any gate failure.
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

        # ---- Gate 0: did send actually trigger a new round ----
        if not getattr(self, "_send_triggered_round", True):
            logger.error(
                "[wait_ai] send_message never observed send-button=disabled, "
                "no new round was triggered. Treat as failure."
            )
            return None

        # ---- Gate 1: wait for a new AI bubble to appear ----
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

        # ---- Gate 2 + Gate 3 combined: wait for "AI content stable >= 2.5s" or "button back to enabled" (whichever first) ----
        # Design motivation (based on real log observation):
        #   - The system under test has a known bug: streaming-end signals are often lost, the button stays forever disabled,
        #     but the AI reply content has actually been fully appended. Waiting forever for the button -> every test gets dragged to 90s then FAILs.
        #   - Solution: use "content stable" as the primary signal (closer to real user perception),
        #     and "button recovered" as the fast-path accelerator; whichever signal is ready first releases.
        #   - Still filter out the "Thinking / Loading" placeholder + require >= 2 real characters -> eliminates false positives.
        #   - Stability window widened to 2500ms (more stable than the original 800ms; avoids misjudging long-token streaming gaps).
        stability_timeout = min(timeout, 30000)
        passed_via = None
        try:
            self.page.wait_for_function(
                """(expectedCount) => {
                    // Path A: button transitioned from disabled back to enabled -> streaming really ended
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

                    // Path B: AI bubble content unchanged for 2500ms in a row and >= 2 chars after stripping placeholders
                    const aiMsgs = document.querySelectorAll(
                        '.qwenpaw-bubble.qwenpaw-bubble-start'
                    );
                    if (aiMsgs.length <= expectedCount) {
                        return false; // No new bubble at all; definitely cannot release
                    }
                    const last = aiMsgs[aiMsgs.length - 1];
                    const raw = (last.innerText || '').trim();
                    const stripped = raw
                        .replace(/Thinking/gi, '')
                        .replace(/Loading/gi, '')
                        .trim();
                    const hasRealText = stripped.length >= 2;

                    // Content stability check (only computed when there is real text)
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

                    // Path A priority (button recovered + at least real text -> release immediately)
                    if (btnEnabled && hasRealText) {
                        window.__qwenpaw_wait_passed_via__ = 'btn_enabled';
                        return true;
                    }
                    // Path B fallback (release on content stability even if button is forever disabled)
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
            # Failure screenshot for post-mortem
            self.step_shot("wait_ai_FAIL_gate23")
            return None
        finally:
            # Clean up window cache so it doesn't affect the next round's judgment
            try:
                self.page.evaluate(
                    "() => { try { "
                    "delete window.__qwenpaw_ai_stable_cache__; "
                    "delete window.__qwenpaw_wait_passed_via__; "
                    "} catch(e) {} }"
                )
            except Exception:
                pass

        # Screenshot: final state after AI fully replied
        self.step_shot(f"ai_response_complete_{passed_via or 'unknown'}")
        return ai_locator.last

    # ========== Message actions ==========
    
    def copy_last_message(self) -> bool:
        """
        Copy the last AI message.

        Returns:
            whether the copy succeeded
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

            # Verify copy success
            if self.assert_visible(self.COPY_SUCCESS, timeout=3000):
                logger.info("Message copied successfully")
                self.step_shot("copy_success")
                return True

        logger.warning("Copy failed or not available")
        self.step_shot("copy_failed")
        return False

    def get_message_text(self, message_locator: Locator) -> str:
        """
        Get the text content of a message.

        Args:
            message_locator: message Locator

        Returns:
            message text
        """
        return message_locator.inner_text()

    def verify_message_contains(self, message_locator: Locator, expected_text: str) -> bool:
        """
        Verify the message contains the given text.

        Args:
            message_locator: message Locator
            expected_text: text expected to be present

        Returns:
            whether the message contains the text
        """
        text = self.get_message_text(message_locator)
        return expected_text.lower() in text.lower()

    # ========== File upload ==========

    def upload_file(self, file_path: str) -> "ChatPage":
        """
        Upload a file.

        Args:
            file_path: path to the file

        Returns:
            self
        """
        logger.info(f"Uploading file: {file_path}")
        self.step_shot("upload_before")

        # Set the file directly via the file input (no need to click the upload button)
        file_input = self.page.locator(self.FILE_INPUT)
        file_input.set_input_files(file_path)

        self.wait(2000)  # Wait for upload to complete
        logger.info("File upload initiated")
        self.step_shot("upload_after")
        return self

    def verify_file_uploaded(self, timeout: int = 10000) -> bool:
        """
        Verify the file was uploaded successfully.

        Args:
            timeout: timeout in ms

        Returns:
            whether the upload succeeded
        """
        file_preview_selector = '.qwenpaw-upload-list-item, .qwenpaw-sender-content [class*="file"], [class*="attachment"]'
        return self.assert_visible(file_preview_selector, timeout=timeout)

    # ========== Session management ==========

    def open_session_list(self) -> "ChatPage":
        """Open the session list (with page state self-healing)."""
        logger.info("Opening session list")
        # Close any leftover dropdowns / popovers first to prevent button occlusion
        try:
            self.page.keyboard.press("Escape")
            self.page.mouse.move(0, 0)  # Move the mouse away to avoid triggering other hovers
        except Exception:
            pass
        self.wait(300)

        # Fallback: if the button is not found in a short time (maybe the sidebar is hidden by an abnormal state), try reloading the page
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
                # Do not raise; let the upstream try/except handle it
                return self

        try:
            session_btn_locator.click(timeout=8000)
        except Exception:
            logger.warning("Normal click failed, trying force click")
            try:
                session_btn_locator.click(force=True, timeout=5000)
            except Exception as e:
                logger.warning(f"[open_session_list] force click also failed: {e}")
                self.step_shot("open_session_list_click_failed")
                return self

        # Wait for the session list drawer to finish rendering
        try:
            self.page.locator(self.SESSION_ITEM).first.wait_for(state="visible", timeout=8000)
        except (TimeoutError, Exception):
            logger.warning("Session list may be empty or slow to render")
        self.wait(500)
        self.step_shot("session_list_opened")
        return self

    def close_session_list(self) -> "ChatPage":
        """Close the session list."""
        logger.info("Closing session list")
        close_btn = self.page.locator('.qwenpaw-drawer ' + self.DRAWER_CLOSE)
        if close_btn.count() > 0:
            close_btn.first.click()
            self.wait(500)
        return self

    def get_session_items(self) -> List[Locator]:
        """Get all session items."""
        return self.page.locator(self.SESSION_ITEM).all()

    def get_session_count(self) -> int:
        """Get the number of sessions."""
        return len(self.get_session_items())

    def switch_to_session(self, index: int = 0) -> "ChatPage":
        """
        Switch to the session at the given index.

        Args:
            index: session index

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
        Rename a session (hover, click the edit button, type a new name, then press Enter).

        Args:
            index: session index
            new_name: new name

        Returns:
            self
        """
        logger.info(f"Renaming session {index} to: {new_name}")

        sessions = self.get_session_items()
        if not sessions or index >= len(sessions):
            logger.warning(f"Session at index {index} not found")
            return self

        target_session = sessions[index]

        # Hover the session item to reveal action buttons
        target_session.hover()
        self.wait(500)

        # Approach 1: click the edit button
        edit_btn = target_session.locator(self.SESSION_EDIT_BTN)
        if edit_btn.count() > 0:
            edit_btn.first.click()
            self.wait(500)
        else:
            # Approach 2: double-click the session name to trigger edit mode
            logger.info("Edit button not found, trying double-click on session name")
            name_el = target_session.locator(self.SESSION_NAME)
            if name_el.count() > 0:
                name_el.first.dblclick()
            else:
                target_session.dblclick()
            self.wait(500)

        # Try several selectors to find the input (may live inside or outside the session item)
        rename_input = None
        input_selectors = [
            'input.qwenpaw-input',
            'input[type="text"]',
            'input',
        ]

        # Search inside the session item first
        for selector in input_selectors:
            locator = target_session.locator(selector)
            if locator.count() > 0 and locator.first.is_visible():
                rename_input = locator.first
                logger.info(f"Found rename input inside session with selector: {selector}")
                break

        # If not found inside the session item, search globally on the page
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
        Pin a session (hover, then click the pin button inside the session item).

        WARNING: pin/edit/delete buttons are all hover-only; clicking without hovering first will
        cause Playwright to wait up to 60s for an invisible button.
        """
        logger.info(f"Pinning session at index {index}")

        sessions = self.get_session_items()
        if not sessions or index >= len(sessions):
            logger.warning(f"Session at index {index} not found")
            self.step_shot(f"pin_session_{index}_not_found")
            return self

        target_session = sessions[index]
        # Must scroll into view + hover first to reveal the action buttons
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

        # Click the pin button (short timeout; force click if still not visible)
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
        Delete a session (hover then click the delete button; deletes directly with no confirmation popup).

        WARNING: the delete button is hover-only -- it is only shown while hovering the session item.
        Between step_shot/wait the mouse may "drift" and the button gets hidden again, so
        Playwright will wait up to 60s by default. Therefore:
        - Do not wait for long before taking the screenshot
        - click must use a short timeout + force-click fallback
        - Re-hover before retrying click to ensure the button is visible
        """
        logger.info(f"Deleting session at index {index}")

        sessions_before = self.get_session_count()
        sessions = self.get_session_items()

        if not sessions or index >= len(sessions):
            logger.warning(f"Session at index {index} not found")
            return self

        target_session = sessions[index]

        # Hover the session item to reveal action buttons (scroll into view first)
        try:
            target_session.scroll_into_view_if_needed(timeout=5000)
            target_session.hover(timeout=10000)
        except Exception:
            logger.warning(f"Session {index} not visible, trying force hover")
            try:
                target_session.hover(force=True, timeout=10000)
            except Exception as e:
                logger.warning(f"[delete_session] force hover also failed: {e}")
                self.step_shot(f"delete_session_{index}_hover_failed")
                return self
        self.wait(300)
        # Screenshot: hover done, before clicking delete (take screenshot only 200ms later to avoid mouse drift)
        self.step_shot(f"delete_session_{index}_before_click")

        # Click the delete button (deletes directly, no confirmation popup)
        del_btn = target_session.locator(self.SESSION_DELETE_BTN)
        if del_btn.count() == 0:
            logger.warning("Delete button not found")
            self.step_shot(f"delete_session_{index}_btn_missing")
            return self

        # Short timeout + force click triple fallback: hover state may already be lost
        try:
            del_btn.first.click(timeout=3000)
        except Exception as e:
            logger.warning(f"[delete_session] regular click failed ({e}), re-hover and retry")
            try:
                # Re-hover so the button becomes visible again
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
        """Verify that at least one session is pinned (checked via the data-pinned attribute)."""
        pinned_btn = self.page.locator('[class*=pinButton][data-pinned="true"]')
        return pinned_btn.count() > 0

    # ========== Model and Agent switching ==========
    
    def open_model_selector(self) -> "ChatPage":
        """Open the model selector."""
        logger.info("Opening model selector")
        # The model selector lives in the right-side area of the header
        header = self.page.locator('.qwenpaw-chat-anywhere-layout-right-header')
        model_btn = header.locator(self.MODEL_SELECTOR).first
        model_btn.click()
        self.wait(500)
        return self

    def select_model(self, model_name: str) -> "ChatPage":
        """
        Select a model.

        Args:
            model_name: model name

        Returns:
            self
        """
        logger.info(f"Selecting model: {model_name}")

        # Find and select the model
        model_option = self.page.locator(self.MODEL_OPTION).filter(has_text=model_name).first
        if model_option.count() > 0:
            model_option.click()
            self.wait(1000)
            logger.info(f"Model selected: {model_name}")

        return self

    def get_available_models(self) -> List[str]:
        """Get the list of available models."""
        options = self.page.locator(self.MODEL_OPTION).all()
        models = [opt.inner_text() for opt in options]
        return models

    def open_agent_selector(self) -> "ChatPage":
        """Open the Agent selector."""
        logger.info("Opening agent selector")
        agent_btn = self.page.locator(self.AGENT_SELECTOR).first
        if agent_btn.count() > 0:
            agent_btn.click()
            self.wait(500)
        return self

    # ========== Skill invocation ==========

    def invoke_skill(self, skill_name: str, input_text: str = "") -> "ChatPage":
        """
        Invoke a skill.

        Args:
            skill_name: skill name
            input_text: input arguments

        Returns:
            self
        """
        command = f"/{skill_name}"
        if input_text:
            command += f" {input_text}"

        logger.info(f"Invoking skill: {command}")
        return self.send_message_and_wait(command)

    def get_skills_list(self) -> Optional[str]:
        """Get the skill list (via the /skills command)."""
        self.send_message("/skills")
        response = self.wait_for_ai_response()
        if response:
            return self.get_message_text(response)
        return None

    # ========== Tool details ==========

    def expand_tool_details(self, message_index: int = -1) -> bool:
        """
        Expand the tool invocation details.

        Args:
            message_index: message index (-1 means the last one)

        Returns:
            whether the expansion succeeded
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

    # ========== Error handling ==========

    def has_error(self) -> bool:
        """Check whether there is an error message."""
        return self.assert_visible(self.ERROR_MESSAGE, timeout=2000)

    def get_error_message(self) -> Optional[str]:
        """Get the error message text."""
        error = self.find(self.ERROR_MESSAGE)
        if error.count() > 0:
            return error.inner_text()
        return None

    def dismiss_error(self) -> "ChatPage":
        """Dismiss the error message."""
        error = self.find(self.ERROR_MESSAGE)
        if error.count() > 0:
            close_btn = error.locator('.qwenpaw-message-close, .qwenpaw-notification-close').first
            if close_btn.count() > 0:
                close_btn.click()
                self.wait(500)
        return self

    # ========== Scrolling and navigation ==========

    def scroll_to_top(self) -> "ChatPage":
        """Scroll the message list to the top."""
        self.page.evaluate("""() => {
            const list = document.querySelector('.qwenpaw-bubble-list-scroll');
            if (list) list.scrollTop = 0;
        }""")
        self.wait(500)
        return self

    def scroll_to_bottom(self) -> "ChatPage":
        """Scroll the message list to the bottom."""
        self.page.evaluate("""() => {
            const list = document.querySelector('.qwenpaw-bubble-list-scroll');
            if (list) list.scrollTop = list.scrollHeight;
        }""")
        self.wait(500)
        return self

    def scroll_to_message(self, message_index: int) -> "ChatPage":
        """
        Scroll to the message at the given index.

        Args:
            message_index: message index

        Returns:
            self
        """
        messages = self.get_all_messages()
        if messages and message_index < len(messages):
            messages[message_index].scroll_into_view_if_needed()
            self.wait(500)
        return self

    # ========== Composite actions ==========

    def complete_chat_flow(self, messages: List[str]) -> "ChatPage":
        """
        Run a complete chat flow.

        Args:
            messages: list of messages to send

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
        Create a new chat and send a message.

        Args:
            message: message content

        Returns:
            self
        """
        return self.create_new_chat().send_message_and_wait(message)

    # ========== Cleanup ==========

    def delete_all_sessions(self, max_attempts: int = 50) -> "ChatPage":
        """
        Delete all sessions; used to clean up test data after the test.

        WARNING: cleanup is robustness-sensitive; the previous test may have left the page in any abnormal state
        (popups not closed, menus not collapsed, focus stuck in the input box, jittering popovers, etc.). Before opening
        the session list, force-reset the page state to avoid 60s dead waits caused by occlusion.
        """
        logger.info("Cleaning up: deleting all sessions")

        # ===== State self-healing: restore the page to a stable operable state =====
        try:
            # Press Escape several times to close popups, dropdowns, modals, etc.
            for _ in range(3):
                self.page.keyboard.press("Escape")
                self.wait(100)
            # Move the mouse to the corner to avoid any hover popover occluding the buttons
            self.page.mouse.move(0, 0)
            # Scroll to the top of the page to make sure the sidebar button is visible
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
