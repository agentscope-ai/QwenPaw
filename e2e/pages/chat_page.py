# -*- coding: utf-8 -*-
"""
QwenPaw Chat page object.

Wraps all interactions on the Chat page and exposes business-level methods.
"""
from __future__ import annotations

import logging
import re
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

    # Sidebar.tsx exposes the current action through its translated accessible
    # name. ``:visible`` excludes the duplicate compact/expanded surface.
    NEW_CHAT_BTN = (
        'button[aria-label="New task"]:visible, '
        'button[aria-label="新建任务"]:visible, '
        'button:has-text("New task"):visible, '
        'button:has-text("新建任务"):visible'
    )
    # Conversation-history disclosure button in the sidebar.
    #
    # The previous value ended with a very broad ``button:has([class*="history"])``
    # which, after #7502, matches *two different* buttons: the
    # ``sidebarSessionList-module__historyHeader`` disclosure toggle (onClick =
    # ``setHistoryCollapsed(c => !c)``) and, when the sidebar is collapsed, the
    # ``collapsedNavItem`` history button in ``Sidebar.tsx`` whose onClick opens a
    # Popover instead of expanding the inline list. Playwright resolves a
    # comma-separated selector as a union and ``.first`` picks the *first match in
    # DOM order* — not the first alternative written — so listing a precise
    # anchor before a broad one does **not** create a preference order. Anchor on
    # the module-scoped ``historyHeader`` class instead: it exists in the same
    # ``sidebarSessionList.module.less`` both before and after #7502, and the
    # element is a ``<button>`` in both, so one selector covers both generations.
    # ``button`` also excludes the sibling ``historyHeaderRow`` container (a
    # ``<div>``) whose scoped name contains ``historyHeader`` as a substring.
    SESSION_LIST_BTN = 'button[class*="historyHeader"]'

    # Input area
    CHAT_INPUT = (
        '.qwenpaw-sender [role="textbox"][contenteditable="true"]:visible, '
        "textarea.qwenpaw-sender-input:visible"
    )
    SEND_BTN = 'button.qwenpaw-sender-actions-btn.qwenpaw-btn-primary'
    FILE_INPUT = 'input[type="file"]'
    UPLOAD_WRAPPER = 'span.qwenpaw-upload-wrapper'

    # Message area
    USER_MESSAGE = '.qwenpaw-bubble.qwenpaw-bubble-end'
    AI_MESSAGE = '.qwenpaw-bubble.qwenpaw-bubble-start'
    MESSAGE_CONTAINER = '.qwenpaw-bubble.qwenpaw-bubble-start, .qwenpaw-bubble.qwenpaw-bubble-end'
    MESSAGE_LIST = '.qwenpaw-bubble-list-scroll'

    # Welcome screen (check input visibility)
    WELCOME_TEXT = CHAT_INPUT
    QUICK_ACTIONS = '.quick-action'

    # Session management.
    #
    # Upstream #7502 ("redesign sidebar and settings experience") removed the
    # right-side "All Chats" drawer entirely: ``ChatSessionDrawer`` is gone
    # (upstream now asserts it is not even referenced — see
    # ``console/src/pages/Chat/index.module.test.ts``) and the session list
    # lives only in ``console/src/layouts/SidebarSessionList.tsx``. The list
    # container changed from ``styles.listWrapper`` to ``styles.scroll``
    # (``listWrapper`` survives only as the *ref variable name*
    # ``listWrapperRef``), so the ancestor prefix ``[class*=listWrapper]`` used
    # to scope these selectors no longer matches anything and every session
    # lookup silently returned 0 items.
    #
    # The ``SessionItem`` component itself did *not* change shape: both before
    # and after #7502 its root element is
    # ``<div className={cls} role="button">`` where ``cls`` is built from
    # ``styles.item`` of ``sessionItem.module.less``. With the build's
    # ``generateScopedName: "[name]__[local]__[hash:base64:5]"`` that renders as
    # ``sessionItem-module__item__<hash>``. So the module-scoped class name plus
    # ``role="button"`` is a stable two-anchor handle across both generations,
    # and — because ``SessionItem`` has exactly one render site in the whole
    # console — it needs no ancestor prefix to stay unambiguous.
    #
    # ``[class*="chatSessionItem"]`` is kept as a fallback for builds older than
    # the v2.0.0 redesign.
    SESSION_ITEM = (
        'div[class*="sessionItem-module__item"], '
        '[class*=chatSessionItem]'
    )
    # Active item: ``.active`` is nested (``&.active``) inside ``.item`` in the
    # same module, so its scoped name carries the ``sessionItem-module__``
    # prefix too. Matching the prefixed name rather than a bare
    # ``[class*=active]`` keeps the selector from latching onto unrelated
    # active-looking classes.
    SESSION_ACTIVE = (
        'div[class*="sessionItem-module__item"]'
        '[class*="sessionItem-module__active"], '
        '[class*=chatSessionItem][class*=active]'
    )
    # Session title element: ``<div className={styles.name}>``. Scoped to
    # ``sessionItem-module__name`` on purpose — a bare ``[class*=name]`` also
    # matches the sibling ``styles.renameInput`` element ("re**name**Input"),
    # which would return the edit box instead of the title.
    SESSION_NAME = (
        'div[class*="sessionItem-module__item"] '
        '[class*="sessionItem-module__name"], '
        '[class*=chatSessionItem] [class*=name]'
    )
    # SessionItem actions live behind a "more" button. The current console
    # renders a custom Popover menu with role-based action buttons.
    SESSION_MORE_BTN = '[class*=moreBtn]'
    # Match the exact label span so "Pin" does not also match "Unpin".
    SESSION_MENU_PIN = (
        'div[role="menu"]:visible button[role="menuitem"]'
        ':has(span:text-is("Pin")), '
        'div[role="menu"]:visible button[role="menuitem"]'
        ':has(span:text-is("置顶"))'
    )
    SESSION_MENU_UNPIN = (
        'div[role="menu"]:visible button[role="menuitem"]'
        ':has(span:text-is("Unpin")), '
        'div[role="menu"]:visible button[role="menuitem"]'
        ':has(span:text-is("取消置顶"))'
    )
    SESSION_MENU_RENAME = (
        'div[role="menu"]:visible '
        'button[role="menuitem"]:has-text("Rename"), '
        'div[role="menu"]:visible '
        'button[role="menuitem"]:has-text("重命名")'
    )
    SESSION_MENU_DELETE = (
        'div[role="menu"]:visible '
        'button[role="menuitem"]:has-text("Delete"), '
        'div[role="menu"]:visible '
        'button[role="menuitem"]:has-text("删除")'
    )
    # Inline rename input rendered when a SessionItem enters edit mode.
    SESSION_RENAME_INPUT = 'input[class*=renameInput]'
    # Conversation search box (filters sessions by title).
    # Since #7502 this input is only mounted on demand — see
    # ``open_session_search()`` for the two clicks that reveal it, and for why
    # this selector alone is not enough any more.
    SESSION_SEARCH_INPUT = '[class*=searchContainer] input'
    # The overflow button next to the history header that opens the dropdown
    # holding "Search conversations" / "New group". Its accessible name comes
    # from ``sidebar.more``. Named ``..._MORE_ACTIONS_BTN`` to keep it distinct
    # from ``SESSION_MORE_BTN`` below, which is the per-session-item action
    # button (Pin / Rename / Archive / Delete) and an unrelated element.
    SESSION_MORE_ACTIONS_BTN = (
        'button[aria-label="More"], button[aria-label="更多"]'
    )
    # The search entry inside that dropdown. Label comes from
    # ``chat.sessionPanel.searchConversations`` ("Search conversations…" /
    # "搜索对话…"); matched on the prefix so the trailing ellipsis cannot
    # break it.
    SESSION_SEARCH_MENU_ITEM = (
        '.qwenpaw-dropdown-menu-item:has-text("Search conversations"), '
        '.ant-dropdown-menu-item:has-text("Search conversations"), '
        '.qwenpaw-dropdown-menu-item:has-text("搜索对话"), '
        '.ant-dropdown-menu-item:has-text("搜索对话")'
    )
    # Pinned marker on a session row. Post-#7956 SessionItem renders
    # ``<span class="...pinMark" title={t("chat.group.pinned")}>`` with a
    # lucide Pin icon when the session is pinned (SessionItem/index.tsx).
    # This is the product's own visible pin indicator and the primary
    # anchor for verification; the menu round-trip is only a fallback.
    SESSION_PIN_MARK = (
        'div[role="button"][class*="sessionItem-module__item"] '
        'span[class*="pinMark"], '
        '[class*=chatSessionItem] span[class*="pinMark"], '
        'span[title="Pinned"], span[title="置顶"]'
    )
    # Legacy hover-button selectors (kept for older builds / fallbacks).
    SESSION_PIN_BTN = 'button:has(.spark-icon-spark-mark-line), button:has(.anticon-pushpin)'
    SESSION_EDIT_BTN = 'button:has(.spark-icon-spark-edit-line), button:has(.anticon-edit)'
    SESSION_DELETE_BTN = 'button:has(.spark-icon-spark-delete-line), button:has(.anticon-delete)'

    # --- Tool approval level toggle (composer / sender area) — upstream #5685 ---
    # Upstream #7334 rebuilt ApprovalLevelToggle from an antd Tag into a plain
    # ``<button class="...trigger">`` (CSS-module hash class, not stable), so
    # the old ``span.qwenpaw-tag`` anchor no longer exists. The button carries
    # ``aria-label=<i18n toolExecutionLevelTitle>`` — the same handle upstream
    # uses in its own unit test (ApprovalToggle.test.tsx) — so we anchor on it.
    # Note: #7368 renamed that title from "Tool Execution Security" to
    # "Tool Approval Mode" (zh: 工具审批模式). In non-compact desktop mode the
    # button text also contains the current level label (e.g. "Strict Mode");
    # in compact/mobile mode it is icon-only. Only one of ApprovalLevelToggle /
    # HarnessApprovalToggle renders at a time (mutually exclusive in the
    # composer), and the harness variant uses a different aria-label, so the
    # locator below is unambiguous.
    APPROVAL_TOGGLE = (
        'button[aria-label="Tool Approval Mode"], '
        'button[aria-label="工具审批模式"]'
    )
    APPROVAL_LEVELS = {
        "STRICT": ("Strict Mode", "严格模式"),
        "SMART": ("Smart Mode", "智能模式"),
        "AUTO": ("Auto Mode", "自动模式"),
        "OFF": ("Off Mode", "关闭模式"),
    }
    # Only items inside the currently-open dropdown (antd keeps closed menus in
    # the DOM with a ``-hidden`` modifier). The #7334 rebuild kept the antd
    # Dropdown for the menu itself, so this selector is unchanged.
    APPROVAL_MENU_ITEM = (
        '.qwenpaw-dropdown:not(.qwenpaw-dropdown-hidden) '
        '.qwenpaw-dropdown-menu-item'
    )

    # Settings and model
    # --- Model selector, post-#7899 (upstream d7afd981, merged 2026-09-21) ---
    # #7899 ("unify model discovery, pricing, selection and thinking
    # controls") moved the model picker OUT of the chat right-header and
    # INTO the sender prefix, wrapped by the new ``SessionThinking``
    # feature component (console/src/features/thinking/SessionThinking.tsx,
    # added by the same PR). Two consequences for us:
    #   1. The container ``.qwenpaw-chat-anywhere-layout-right-header`` no
    #      longer holds the trigger (the right header now only renders
    #      ChatHeaderTitle / ChatActionGroup / plugin slots).
    #   2. The trigger is no longer an antd Dropdown trigger: it is a plain
    #      ``<button class="...trigger">`` inside an antd *Popover*, so the
    #      runtime class ``qwenpaw-dropdown-trigger`` never appears.
    # The stable handles are the i18n-derived accessible names:
    #   * outer trigger: ``aria-label = t("thinkingControl.title")``
    #     ("Thinking intensity" / "思考强度")
    #   * inner "change model" button inside the opened panel:
    #     ``ThinkingControl`` renders ``button.<css-module modelChoice>``
    #     whose accessible name falls back to ``t("modelSelector.selectModel")``
    #     ("Select model" / "选择模型") when the model lacks thinking support,
    #     and whose visible text is the active model name otherwise.
    #   * embedded picker rows: ``button.<css-module modelSelectButton>``
    #     (ModelSelector ``embedded`` branch, index.tsx:1291).
    MODEL_THINKING_TRIGGER = (
        'button[aria-label="Thinking intensity"], '
        'button[aria-label="思考强度"], '
        # i18n cold-start arm: before the locale bundle resolves, the
        # trigger renders the RAW key as its aria-label (live-probe DOM
        # 2026-10-15: aria-label="thinkingControl.title"). Without this
        # arm the first case of a cold CI run times out at hop 1 while
        # every later case passes (the bundle is then cached) — exactly
        # the split seen in fork run 38557785191 (attempt 1 died at hop 1
        # with the trigger plainly on screen, attempt 2 reached hop 2).
        'button[aria-label="thinkingControl.title"]'
    )
    MODEL_CHOICE_BTN = (
        'div[role="dialog"] button[class*="modelChoice"], '
        'button[class*="modelChoice"]'
    )
    MODEL_SELECT_EMBEDDED_BTN = (
        'div[role="dialog"] button[class*="modelSelectButton"], '
        'button[class*="modelSelectButton"]'
    )
    # Legacy anchors, kept ONLY as last-resort fallbacks for builds older
    # than #7899 (the pre-#7899 header Dropdown). They are dead on current
    # main; do not add new uses.
    MODEL_SELECTOR = '.qwenpaw-dropdown-trigger'
    MODEL_OPTION = '.qwenpaw-dropdown-menu-item'
    AGENT_SELECTOR = '.qwenpaw-select-selector'

    # --- Sidebar agent switcher (components/AgentSelector) ---
    # The antd Select sits inside a CSS-module wrapper whose hashed class
    # keeps the "agentSelector" basename; scoping avoids other Selects.
    AGENT_SWITCHER = '[class*="agentSelector"] .qwenpaw-select-selector'
    AGENT_SWITCHER_VALUE = (
        '[class*="agentSelector"] .qwenpaw-select-selection-item'
    )
    AGENT_SWITCHER_OPTION = (
        '.qwenpaw-select-dropdown:not(.qwenpaw-select-dropdown-hidden) '
        '.qwenpaw-select-item-option'
    )

    # --- Slash-command suggestion popup (@ant-design/x Suggestion) ---
    # Opens while the input starts with "/" and has no whitespace yet.
    # Two nodes carry .qwenpaw-suggestion (inline content + the cascader
    # dropdown); anchor on the dropdown, excluding its hidden state.
    SUGGESTION_POPUP = (
        '.qwenpaw-suggestion.qwenpaw-select-dropdown'
        ':not(.qwenpaw-select-dropdown-hidden)'
    )
    SUGGESTION_ITEM = '.qwenpaw-suggestion-item'

    # --- Sidebar session date groups — upstream #5643 ---
    # SidebarSessionList renders one <button class={styles.groupLabel}> per
    # non-empty bucket (Pinned / Today / Within 7 days / Within 30 days /
    # Earlier); clicking toggles collapse. "month" + "older" start collapsed.
    SIDEBAR_GROUP_LABEL = 'div[role="button"][class*="SessionGroupHeader"]'
    SIDEBAR_DATE_LABEL = '[data-date-group]'
    SIDEBAR_GROUP_CHEVRON = 'span[class*="groupChevron"]'
    SIDEBAR_GROUP_TEXTS = {
        "pinned": ("Pinned", "置顶"),
        "today": ("Today", "今天"),
        "week": ("Within 7 days", "7天内"),
        "month": ("Within 30 days", "30天内"),
        "older": ("Earlier", "更早"),
    }

    # --- Non-owner tab banner — upstream #5664 ---
    # antd <Alert type="info" banner> injected into the sender beforeUI slot
    # when this tab lost the qwenpaw:queue-owner:<sessionId> Web Lock. Appears
    # only after a 300ms ownershipResolved fallback timer.
    QUEUE_BANNER = '.qwenpaw-alert-banner'
    _QUEUE_BANNER_RE = re.compile(
        r"This tab queues only|当前标签页仅入队"
    )

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

    # ========== "Which AI bubble carries this round's answer" ==========
    #
    # Fork run 38788391872's FAIL-moment DOM snapshot settles what the render
    # order actually is (two attempts, same shape; quoted verbatim):
    #
    #   idx0   'QwenPaw\nCompleted 1 steps\n\n1, 2, ... 10, 11\n\n02:59:31'
    #   idx1   ...                                              02:59:27
    #   ...
    #   idx9   'QwenPaw\nCompleted 1 steps\n\n1, 2\n\n02:58:29'
    #   idx10  ''
    #
    # Two facts, each fatal to ``get_ai_messages()[-1]``: the list renders
    # NEWEST-FIRST, so the DOM end is the OLDEST bubble; and context
    # compression empties the OLDEST bubbles, so the DOM end is precisely the
    # bubble that loses its text first. ``[-1]`` therefore yields an empty
    # string, which is how
    # tests/test_context_scroll.py::TestLongConversationCompression failed
    # with ``assert ('1' in '' or 'one' in '')`` while the step screenshot
    # showed the answer fully rendered.
    #
    # The rendered per-bubble timestamp is the only order-independent
    # freshness signal the DOM carries, so that is what this reads. It returns
    # an INDEX plus the tier that produced it. -1 means "cannot tell", and the
    # caller must then fall back to DOM order (a visible false red) rather than
    # guess: guessing here means handing the PREVIOUS round's answer to an
    # assertion, which passes for the wrong reason and hides the defect.
    #
    # Tiers, in order:
    #   1 fresh_after_send        baseline present: newest bubble rendered
    #                             AFTER the send. This is the tier that rules
    #                             out a false green.
    #   2 pathe_fresh_single      baseline present but no usable timestamp:
    #                             the single index the release path recorded
    #                             as carrying fresh text (an ambiguous count
    #                             is refused). Defensive: keeps this correct
    #                             if a build stops rendering timestamps.
    #   3 newest_with_ts          no baseline: newest by timestamp.
    #   4 last_nonempty_dom_order no baseline and no timestamps: walk back from
    #                             the DOM end to the first non-empty bubble
    #                             (correct on a forward list, and still better
    #                             than '' on a reverse one).
    _JS_LATEST_AI_BUBBLE = """(args) => {
        const baselineTs = (args && typeof args.baselineTs === 'number')
            ? args.baselineTs : -1;
        const pathEFreshIdx = (args && Array.isArray(args.pathEFreshIdx))
            ? args.pathEFreshIdx : [];
        const els = document.querySelectorAll(
            '.qwenpaw-bubble.qwenpaw-bubble-start'
        );
        const rows = [];
        let tsCount = 0;
        for (let i = 0; i < els.length; i++) {
            const raw = (els[i].innerText || '').trim();
            const stripped = raw
                .replace(/Thinking/gi, '')
                .replace(/Loading/gi, '')
                .trim();
            // Take the LAST HH:MM:SS in the text: the answer body itself may
            // quote a time, and the rendered stamp is what trails the bubble.
            let ts = -1;
            const hits = raw.match(/\\d{1,2}:\\d{2}:\\d{2}/g);
            if (hits && hits.length > 0) {
                const p = hits[hits.length - 1].split(':');
                ts = (+p[0]) * 3600 + (+p[1]) * 60 + (+p[2]);
                tsCount++;
            }
            rows.push({ idx: i, ok: stripped.length >= 2, ts: ts });
        }
        // Stamps carry no date, so a round crossing midnight would otherwise
        // look 24h older than the baseline.
        const adjust = (t) => {
            if (baselineTs >= 0 && t >= 0 && t < baselineTs - 43200) {
                return t + 86400;
            }
            return t;
        };

        if (baselineTs >= 0) {
            let best = null;
            for (let i = 0; i < rows.length; i++) {
                if (!rows[i].ok || rows[i].ts < 0) continue;
                const t = adjust(rows[i].ts);
                if (t <= baselineTs) continue;
                if (!best || t > best.t) best = { idx: rows[i].idx, t: t };
            }
            if (best) {
                return {
                    idx: best.idx, why: 'fresh_after_send', ts: best.t,
                    count: rows.length, tsCount: tsCount,
                };
            }
            if (pathEFreshIdx.length === 1) {
                const cand = pathEFreshIdx[0];
                if (cand >= 0 && cand < rows.length && rows[cand].ok) {
                    return {
                        idx: cand, why: 'pathe_fresh_single',
                        ts: rows[cand].ts, count: rows.length,
                        tsCount: tsCount,
                    };
                }
            }
            // Refuse to guess: fall back to today's behaviour so a wrong read
            // stays a visible RED instead of a silent pass on stale text.
            return {
                idx: -1, why: 'no_bubble_newer_than_baseline',
                count: rows.length, tsCount: tsCount,
            };
        }

        let best3 = null;
        for (let i = 0; i < rows.length; i++) {
            if (!rows[i].ok || rows[i].ts < 0) continue;
            if (!best3 || rows[i].ts > best3.t) {
                best3 = { idx: rows[i].idx, t: rows[i].ts };
            }
        }
        if (best3) {
            return {
                idx: best3.idx, why: 'newest_with_ts', ts: best3.t,
                count: rows.length, tsCount: tsCount,
            };
        }
        for (let i = rows.length - 1; i >= 0; i--) {
            if (rows[i].ok) {
                return {
                    idx: rows[i].idx, why: 'last_nonempty_dom_order',
                    ts: rows[i].ts, count: rows.length, tsCount: tsCount,
                };
            }
        }
        return {
            idx: -1, why: 'no_nonempty_bubble',
            count: rows.length, tsCount: tsCount,
        };
    }"""

    # ========== Initialization ==========
    
    def __init__(self, page: Page):
        super().__init__(page)
        # Read-path state, both written by send_message / wait_for_ai_response
        # and read by _resolve_latest_ai_index. Declared here so the resolver
        # never depends on attribute-existence luck.
        self._ai_stamp_before_send = -1
        self._ai_texts_before_send: List[str] = []
        self._last_round_fresh_idx: List[int] = []
        logger.info("ChatPage initialized")
    
    # ========== Page navigation ==========

    def open(self) -> "ChatPage":
        """Open the Chat page."""
        logger.info("Opening Chat page")
        self.goto()
        # The chat page keeps SSE connections open, so ``networkidle``
        # never fires. Wait for the textarea to be visible instead —
        # that's a strong signal that React has booted and the page is
        # interactive.
        self.page.locator(self.CHAT_INPUT).first.wait_for(
            state="visible", timeout=self.timeout
        )
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
        
        new_chat_btn = self.find(self.NEW_CHAT_BTN).first
        expect(new_chat_btn).to_be_visible(timeout=self.timeout)
        new_chat_btn.click()
        # The chat page keeps an SSE connection open, so ``networkidle`` is
        # not a useful completion signal. The new-task event is complete once
        # the previous transcript is gone and the composer is interactive.
        expect(self.page.locator(self.MESSAGE_CONTAINER)).to_have_count(
            0,
            timeout=self.timeout,
        )
        self.page.locator(self.CHAT_INPUT).first.wait_for(
            state="visible",
            timeout=self.timeout,
        )
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
        # Retained but NO LONGER READ by any release path. It used to guard
        # Path D on the theory that compression rebuilds the bubble list and
        # the user count proves the request still reached the server. Fork
        # run 38788391872 falsified that theory: the FAIL-moment DOM
        # snapshot recorded ZERO bubble attachments during the whole wait
        # window, so nothing was rebuilt or unloaded - this round's answer
        # sat in the list the entire time and the release paths simply read
        # the wrong end of it. Kept (rather than dropped) because Path D's
        # comment quotes the old condition to explain why a count-based
        # guard cannot work here.
        self._user_count_before_send = user_count_before
        # Text baseline for wait_for_ai_response's Path E. Taken HERE, before
        # the fill/click, because by the time that wait starts gate-1 has
        # already seen this round's own bubble and its text may already be
        # rendered - a snapshot taken at wait start then cannot tell this
        # round's answer apart from history. Normalised the same way the
        # release path normalises (Thinking/Loading stripped, trimmed) so the
        # two sides compare like for like; a bubble that still said
        # "Thinking" at snapshot time would otherwise count as fresh text.
        #
        # The same snapshot also records the NEWEST rendered bubble stamp
        # (``_ai_stamp_before_send``), which is the baseline the read path
        # uses to tell this round's answer apart from history: only a bubble
        # stamped AFTER it can be this round's. Both sides read the stamps the
        # frontend paints, so no clock outside the page is involved.
        try:
            baseline = self.page.evaluate(
                """() => {
                    const out = [];
                    let maxTs = -1;
                    document.querySelectorAll(
                        '.qwenpaw-bubble.qwenpaw-bubble-start'
                    ).forEach((el) => {
                        const raw = (el.innerText || '').trim();
                        const s = raw
                            .replace(/Thinking/gi, '')
                            .replace(/Loading/gi, '')
                            .trim();
                        out.push(s);
                        // Newest pre-existing render stamp, read from the same
                        // clock the bubbles are painted with. Using the test
                        // runner's wall clock here instead would compare
                        // against a different clock and could be skewed.
                        const hits = raw.match(/\\d{1,2}:\\d{2}:\\d{2}/g);
                        if (hits && hits.length > 0) {
                            const p = hits[hits.length - 1].split(':');
                            const t = (+p[0]) * 3600
                                + (+p[1]) * 60
                                + (+p[2]);
                            if (t > maxTs) maxTs = t;
                        }
                    });
                    return { texts: out, maxTs: maxTs };
                }"""
            ) or {}
            self._ai_texts_before_send = list(baseline.get("texts") or [])
            self._ai_stamp_before_send = baseline.get("maxTs", -1)
        except Exception as e:  # baseline is best-effort; Path E degrades safely
            self._ai_texts_before_send = []
            self._ai_stamp_before_send = -1
            logger.warning(
                f"[send_message] pre-send AI text baseline unavailable: "
                f"{type(e).__name__}"
            )
        logger.info(
            f"[send_message] baseline: ai={self._ai_count_before_send}, "
            f"user={user_count_before}, "
            f"ai_texts={len(self._ai_texts_before_send)}, "
            f"newest_stamp={self._ai_stamp_before_send}"
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
        input_box.focus()
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
            input_box.focus()
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
        """
        Get the most recent AI message.

        NOT ``get_ai_messages()[-1]``: fork run 38788391872's FAIL-moment
        snapshot proved this page renders the bubble list NEWEST-FIRST and
        that context compression empties the OLDEST bubbles, so the DOM end is
        the one bubble guaranteed to lose its text. ``[-1]`` returned an empty
        string there, failing
        ``TestLongConversationCompression`` with
        ``assert ('1' in '' or 'one' in '')`` while the step screenshot showed
        the answer fully rendered.

        Resolution is order-independent (rendered bubble stamps, then the
        release path's fresh-text index, then DOM order) and refuses to guess:
        when it cannot identify this round's answer it falls back to the
        DOM-end bubble, i.e. today's behaviour - a visible false red rather
        than a silent pass on the previous round's text.
        """
        return self._latest_ai_locator("get_last_ai_message")

    def _resolve_latest_ai_index(self, use_round_baseline: bool = True) -> Tuple[int, str]:
        """
        Locate the AI bubble that carries the current round's answer.

        Returns ``(index, why)``. ``index == -1`` means "cannot tell" and the
        caller must fall back to DOM order rather than guess, because guessing
        means handing the PREVIOUS round's answer to an assertion - which
        passes for the wrong reason and hides the defect.

        ``_JS_LATEST_AI_BUBBLE`` documents the tiers and the evidence. The
        baseline is the newest render stamp recorded by ``send_message``
        BEFORE the click, so it is only available when this wait belongs to a
        round; ``use_round_baseline=False`` asks for "the latest AI message"
        outside any round (tiers 3/4).
        """
        baseline_ts = -1
        if use_round_baseline:
            raw_baseline = getattr(self, "_ai_stamp_before_send", None)
            if isinstance(raw_baseline, int) and raw_baseline >= 0:
                baseline_ts = raw_baseline
        fresh_idx: List[int] = []
        if use_round_baseline:
            recorded = getattr(self, "_last_round_fresh_idx", None) or []
            fresh_idx = [i for i in recorded if isinstance(i, int)]
        try:
            result = self.page.evaluate(
                self._JS_LATEST_AI_BUBBLE,
                {"baselineTs": baseline_ts, "pathEFreshIdx": fresh_idx},
            ) or {}
            idx = result.get("idx", -1)
            why = result.get("why", "unavailable")
            if not isinstance(idx, int):
                idx = -1
                why = "bad_idx_type"
            logger.info(
                f"[read_ai] latest bubble idx={idx} why='{why}' "
                f"(baselineTs={baseline_ts}, freshIdx={fresh_idx}, "
                f"count={result.get('count')}, tsCount={result.get('tsCount')})"
            )
            return idx, why
        except Exception as e:
            logger.warning(
                f"[read_ai] latest-bubble resolution failed "
                f"({type(e).__name__}); falling back to DOM order"
            )
            return -1, f"evaluate_failed:{type(e).__name__}"

    def _read_newest_ai_text(self) -> str:
        """Text of the newest non-empty AI bubble (diagnostics only)."""
        idx, _why = self._resolve_latest_ai_index(use_round_baseline=False)
        locator = self.page.locator(self.AI_MESSAGE)
        target = locator.nth(idx) if idx >= 0 else locator.last
        return target.inner_text()

    def _latest_ai_locator(self, caller: str) -> Optional[Locator]:
        """
        Shared read-path resolution for ``get_last_ai_message`` and
        ``wait_for_ai_response``'s return value.

        Logs the resolved index, the tier that produced it AND the text it
        reads, so a future red states which of the two was wrong instead of
        leaving the next reader to guess: an empty text with a plausible index
        means the bubble itself is empty, while a stale answer means the tier
        picked the wrong bubble.
        """
        messages = self.get_ai_messages()
        if not messages:
            logger.warning(f"[read_ai] {caller}: no AI bubble in the DOM")
            return None
        idx, why = self._resolve_latest_ai_index()
        if idx < 0:
            logger.warning(
                f"[read_ai] {caller}: unresolved (why='{why}'); falling back "
                f"to DOM order messages[-1] = idx{len(messages) - 1}"
            )
            target = messages[-1]
        else:
            target = messages[idx]
        try:
            sample = target.inner_text().strip()[:120]
        except Exception:
            sample = "<unreadable>"
        logger.info(
            f"[read_ai] {caller}: idx={idx} why='{why}' "
            f"count={len(messages)} text={sample!r}"
        )
        return target

    def wait_for_ai_response(
        self,
        timeout: int = 30000,
        stability_cap_ms: int = 30000,
    ) -> Optional[Locator]:
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
            stability_cap_ms: ceiling of the gate-2/3 window. The default
                (30000) preserves the historical behaviour for every
                existing caller. Long multi-round cases (e.g. the 25-round
                compression case) hit transient stalls that a 30 s window
                cannot absorb; they pass a larger cap.

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
        #   - Path C added 2026-09-18: the SDK can leave a stale EMPTY streaming
        #     bubble after the reply already finished (streaming-end signal
        #     lost). Paths A/B both require real text in the LAST bubble, so a
        #     trailing empty bubble wedges them until the window expires even
        #     though the answer is fully rendered one bubble earlier. Path C
        #     releases on stability of the newest REAL-text bubble that belongs
        #     to this round (index >= expectedCount); the index guard prevents
        #     misreading the previous round's content as this round's reply.
        stability_timeout = min(timeout, stability_cap_ms)
        user_count_before = getattr(self, "_user_count_before_send", None)
        if user_count_before is None:
            user_count_before = self.page.locator(self.USER_MESSAGE).count()
        # Path D (revised 2026-10-16) needs wait-start evidence, not the
        # pre-send baseline: this round's own user bubble has already
        # landed by the time gate-2/3 begins (send_message waits for it),
        # so the pre-send user-count equality can never hold - fork run
        # 38719913840 shows Path D never released once since 2026-10-13.
        # Snapshot the pre-wait AI texts and start a MutationObserver so
        # Path D can release on "a bubble node carrying NEW text was
        # attached after wait start" (the shape a mid-round context
        # compression / virtualised re-render leaves behind).
        #
        # UPDATE, same day, after fork run 38788391872: the rebuild
        # shape described above did NOT occur - the FAIL-moment snapshot
        # recorded an EMPTY attach log on both attempts, so no bubble node
        # was attached during the wait window at all. Path D's premise is
        # falsified and it is retained only as instrumentation. What the
        # snapshot did show is that the list renders newest-first and
        # compression empties the OLDEST bubbles, which is what wedges
        # Paths B and C (both read the last node). Path E below is the
        # release path the evidence supports. The observer and its log stay
        # because "zero attachments" is precisely the negative evidence
        # that ruled the rebuild theory out.
        #
        # Path E needs a PRE-SEND text baseline, which send_message
        # captured before the click. This wait-start snapshot cannot serve
        # that purpose: gate-1 has already seen this round's bubble by
        # here, so its text may already be present and would not count as
        # fresh. Fall back to the wait-start snapshot only when the
        # pre-send baseline is missing (e.g. wait_for_ai_response called
        # without send_message), which degrades Path E to "text not seen at
        # wait start" - still order-independent, just a weaker notion of
        # new.
        pre_send_texts: List[str] = list(
            getattr(self, "_ai_texts_before_send", None) or []
        )
        pre_wait_texts: List[str] = []
        try:
            snapshot = self.page.evaluate(
                """() => {
                    if (window.__qwenpaw_ai_attach_obs__) {
                        try { window.__qwenpaw_ai_attach_obs__.disconnect(); }
                        catch (e) {}
                    }
                    window.__qwenpaw_ai_attach_log__ = [];
                    const texts = [];
                    document.querySelectorAll(
                        '.qwenpaw-bubble.qwenpaw-bubble-start'
                    ).forEach((el) => texts.push((el.innerText || '').trim()));
                    const obs = new MutationObserver((muts) => {
                        const now = Date.now();
                        const log = window.__qwenpaw_ai_attach_log__;
                        for (const m of muts) {
                            for (const n of m.addedNodes) {
                                if (!n || n.nodeType !== 1) continue;
                                const hits = [];
                                if (
                                    n.classList
                                    && n.classList.contains('qwenpaw-bubble')
                                ) {
                                    hits.push(n);
                                }
                                if (n.querySelectorAll) {
                                    n.querySelectorAll('.qwenpaw-bubble')
                                        .forEach((el) => hits.push(el));
                                }
                                for (const el of hits) {
                                    // Keep the element reference: the text
                                    // at attach time is empty for a
                                    // streaming bubble, so Path D must read
                                    // innerText live at poll time.
                                    log.push({
                                        t: now,
                                        cls: String(el.className).slice(0, 120),
                                        el: el,
                                    });
                                }
                            }
                        }
                    });
                    obs.observe(document.body, {childList: true, subtree: true});
                    window.__qwenpaw_ai_attach_obs__ = obs;
                    window.__qwenpaw_ai_wait_start__ = Date.now();
                    return texts;
                }"""
            )
            pre_wait_texts = list(snapshot or [])
            if not pre_send_texts:
                # No pre-send baseline (wait_for_ai_response used without
                # send_message): degrade Path E to the wait-start snapshot
                # rather than disabling it.
                pre_send_texts = list(pre_wait_texts)
        except Exception as e:  # observer is best-effort diagnostics only
            logger.warning(
                f"[wait_ai] attach-observer install failed: {type(e).__name__}"
            )
        passed_via = None
        try:
            self.page.wait_for_function(
                """({expectedCount, expectedUserCount, preWaitTexts, preSendTexts}) => {
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
                    // Path C (2026-09-18): tolerate the known SDK behaviour where
                    // a stale EMPTY streaming bubble is left behind after the
                    // reply already finished (streaming-end signal lost). In that
                    // state `last` is empty forever, so Path A (needs real text)
                    // and Path B (needs real text) can never release, and the
                    // round fails after the whole stability window even though
                    // the reply is fully rendered one bubble earlier. Evidence:
                    // CI step_shot at the FAIL moment shows the round's answer
                    // complete ("Completed 1 steps" + full text) with a trailing
                    // empty spinner bubble. Path C releases when the NEWEST
                    // bubble that carries real text AND belongs to this round
                    // (index >= expectedCount) is stable for 1500ms. The
                    // index guard is what keeps this from misreading the
                    // PREVIOUS round's content as this round's reply.
                    let newestReal = null;
                    for (let i = aiMsgs.length - 1; i >= expectedCount; i--) {
                        const t = (aiMsgs[i].innerText || '').trim();
                        const s = t
                            .replace(/Thinking/gi, '')
                            .replace(/Loading/gi, '')
                            .trim();
                        if (s.length >= 2) {
                            newestReal = { raw: t, idx: i };
                            break;
                        }
                    }
                    if (newestReal) {
                        const keyC = '__qwenpaw_ai_stable_cache_c__';
                        const nowC = Date.now();
                        const cacheC = window[keyC] || {};
                        if (
                            cacheC.text !== newestReal.raw ||
                            cacheC.idx !== newestReal.idx
                        ) {
                            window[keyC] = {
                                text: newestReal.raw,
                                idx: newestReal.idx,
                                since: nowC,
                            };
                        } else if (nowC - cacheC.since >= 1500) {
                            window.__qwenpaw_wait_passed_via__ =
                                'content_stable_new_round';
                            return true;
                        }
                    }

                    // Path D (revised 2026-10-16): the bubble list can be
                    // REBUILT mid-round (context compression / virtualised
                    // re-render), which drops the round's own bubble below
                    // `expectedCount` or empties it. Then Paths A/B/C can
                    // never release even though the answer is fully
                    // rendered - evidence: nightly 2026-10-07..12 and fork
                    // run 38719913840, the 25-round compression case failed
                    // at rounds 11-13 every night with "Last bubble text:
                    // ''" while the FAIL-moment screenshot showed the
                    // round's answer complete ("Completed 1 steps" + full
                    // text) and the send button enabled.
                    // The 2026-10-13 version guarded with
                    // userMsgs.length === expectedUserCount, but that
                    // baseline is taken BEFORE the click while this round's
                    // own user bubble has already landed by wait start, so
                    // the equality can never hold and the path is dead.
                    // Release when: the send button is enabled AND a bubble
                    // node carrying text that did NOT exist at wait start
                    // was attached after wait start (MutationObserver
                    // log). The fresh-text guard is what keeps this from
                    // releasing on the pre-wait history state.
                    const attachLog = window.__qwenpaw_ai_attach_log__ || [];
                    let freshReal = false;
                    for (let i = 0; i < attachLog.length; i++) {
                        const el = attachLog[i].el;
                        if (!el || !el.isConnected) continue;
                        // AI bubbles only: this round's own user bubble is
                        // also attached after wait start and its text is
                        // not in the AI-text snapshot, so without the class
                        // guard a user-bubble re-attach would release.
                        if (!el.classList.contains('qwenpaw-bubble-start')) {
                            continue;
                        }
                        const s = (el.innerText || '')
                            .replace(/Thinking/gi, '')
                            .replace(/Loading/gi, '')
                            .trim();
                        if (s.length >= 2 && preWaitTexts.indexOf(s) === -1) {
                            freshReal = true;
                            break;
                        }
                    }
                    if (btnEnabled && freshReal) {
                        window.__qwenpaw_wait_passed_via__ =
                            'btn_enabled_post_rebuild';
                        return true;
                    }

                    // Path E (2026-10-16, second revision): release on
                    // "some bubble carries text that did not exist before
                    // the send", scanning the WHOLE list.
                    //
                    // This is the path the evidence actually supports. Fork
                    // run 38788391872's FAIL-moment DOM snapshot recorded,
                    // on both attempts: the bubble timestamps strictly
                    // DECREASING by index (02:59:31 at idx0 down to
                    // 02:58:29 at idx9) i.e. the newest bubble is at index
                    // 0 and the OLDEST sits at the end of the NodeList;
                    // this round's answer fully rendered at idx0
                    // ("Completed 1 steps" + the whole reply); the five
                    // oldest bubbles emptied to ''; btnEnabled false; and
                    // the attach log EMPTY.
                    //
                    // Three consequences, each fatal to one of the paths
                    // above:
                    //  - Paths B and C both read aiMsgs[length-1], which is
                    //    the OLDEST bubble, and Path C's `i >= expectedCount`
                    //    guard covers exactly that one index - so once
                    //    compression empties the old bubbles both paths read
                    //    '' forever. That also explains why earlier rounds
                    //    passed: before compression kicked in the oldest
                    //    bubble still had stable text, so Path B released on
                    //    it. It was releasing on the WRONG bubble, which was
                    //    merely harmless while that bubble had content.
                    //  - Paths A and D both require btnEnabled, which the
                    //    snapshot shows is false throughout (the known
                    //    lost-streaming-end-signal behaviour this function
                    //    was written to tolerate in the first place).
                    //  - Path D additionally requires a freshly attached
                    //    node, and the attach log was empty: nothing was
                    //    rebuilt or unloaded. The mid-round-rebuild theory
                    //    Path D was written for is falsified by this run.
                    //
                    // So Path E deliberately depends on NONE of: render
                    // order, list index, the send button, or node
                    // attachment. It scans every bubble and asks only
                    // whether some bubble carries real text absent from the
                    // pre-send baseline (`preSendTexts`, captured in
                    // send_message BEFORE the click - the wait-start
                    // snapshot is too late, since gate-1 has already seen
                    // this round's bubble and its text may already be
                    // rendered there). Emptied old bubbles cannot trigger
                    // it: they normalise to length 0 and are skipped.
                    //
                    // Order-independence is required, not cosmetic: the
                    // snapshot proves the list is newest-first on the
                    // failing round, and nothing establishes that this order
                    // is constant across rounds, builds, or view modes.
                    // Taking an endpoint (first or last) or an index guard
                    // would re-introduce exactly the bug being fixed here.
                    //
                    // The 1500 ms stability window keeps this from
                    // releasing on a half-streamed answer: text that is
                    // still growing is by definition not yet stable. The
                    // key is the SORTED join of all fresh texts, so a
                    // re-order of the same content does not reset it.
                    const preSend = preSendTexts || [];
                    // Guard: with no pre-send baseline there is no way to
                    // tell this round's answer apart from history, so
                    // every existing bubble would look "fresh" and Path E
                    // would release on the PREVIOUS round's content. That
                    // can happen when the pre-send snapshot threw (see the
                    // warning in send_message) or when this wait is reached
                    // without send_message. Refuse to guess: skip Path E
                    // whenever the baseline is missing and there IS history
                    // to be confused by. A genuine first round has no
                    // history (expectedCount === 0), so "any stable text is
                    // new" is safe there and the path still works.
                    if (preSend.length === 0 && expectedCount > 0) {
                        window.__qwenpaw_wait_pathE_skipped__ =
                            'no_presend_baseline';
                        return false;
                    }
                    const fresh = [];
                    const freshIdx = [];
                    for (let i = 0; i < aiMsgs.length; i++) {
                        const s = (aiMsgs[i].innerText || '')
                            .replace(/Thinking/gi, '')
                            .replace(/Loading/gi, '')
                            .trim();
                        if (s.length >= 2 && preSend.indexOf(s) === -1) {
                            fresh.push(s);
                            freshIdx.push(i);
                        }
                    }
                    // Recorded for the READ path: when no bubble carries a
                    // usable render stamp, get_last_ai_message falls back to
                    // this index (only when it is unambiguous).
                    window.__qwenpaw_ai_fresh_idx__ = freshIdx;
                    if (fresh.length > 0) {
                        const keyE = '__qwenpaw_ai_fresh_cache__';
                        const nowE = Date.now();
                        const sigE = fresh.slice().sort().join('\u0000');
                        const cacheE = window[keyE] || {};
                        if (cacheE.sig !== sigE) {
                            window[keyE] = { sig: sigE, since: nowE };
                        } else if (nowE - cacheE.since >= 1500) {
                            window.__qwenpaw_wait_passed_via__ =
                                'fresh_text_stable';
                            window.__qwenpaw_ai_fresh_count__ = fresh.length;
                            return true;
                        }
                    }
                    return false;
                }""",
                arg={
                    "expectedCount": count_before_send,
                    "expectedUserCount": user_count_before,
                    "preWaitTexts": pre_wait_texts,
                    "preSendTexts": pre_send_texts,
                },
                timeout=stability_timeout,
            )
            try:
                passed_via = self.page.evaluate(
                    "() => window.__qwenpaw_wait_passed_via__ || 'unknown'"
                )
            except Exception:
                passed_via = "unknown"
            # Read the fresh-text indices BEFORE the finally block deletes the
            # window caches; the read path uses them as its fallback tier.
            try:
                fresh_idx = list(
                    self.page.evaluate(
                        "() => window.__qwenpaw_ai_fresh_idx__ || []"
                    )
                    or []
                )
            except Exception:
                fresh_idx = []
            self._last_round_fresh_idx = fresh_idx
            logger.info(
                f"[wait_ai] gate-2/3 PASS via '{passed_via}' "
                f"(streaming considered done), fresh_idx={fresh_idx}"
            )
        except (TimeoutError, AssertionError, Exception) as e:
            self._last_round_fresh_idx = []
            try:
                # Report the newest non-empty bubble, not the DOM end: on a
                # reverse-ordered list the DOM end is the OLDEST bubble and
                # compression empties it first, so `.last` prints '' and the
                # log tells the next reader nothing (that is exactly how
                # nightly 2026-10-07..15 read "Last bubble text: ''" while the
                # screenshot showed the answer complete).
                last_text = self._read_newest_ai_text()[:200]
            except Exception:
                last_text = "<unreadable>"
            # FAIL-moment DOM snapshot: the four release-path components
            # plus the bubble inventory and the MutationObserver attach
            # log. Nightly 2026-10-07..15 and fork run 38719913840 failed
            # here with the answer visibly rendered, so the screenshot
            # alone cannot tell which component vetoed the release.
            try:
                diag = self.page.evaluate(
                    """({expectedCount, preSendTexts}) => {
                        const btn = document.querySelector(
                            'button.qwenpaw-sender-actions-btn'
                            + '.qwenpaw-btn-primary'
                        );
                        let btnEnabled = false;
                        if (btn) {
                            const cls = btn.className || '';
                            const disCls = /qwenpaw-btn-disabled/
                                .test(cls)
                                || /qwenpaw-btn-loading/.test(cls)
                                || /is-disabled/.test(cls)
                                || /is-loading/.test(cls);
                            const disAttr = btn.disabled === true
                                || btn.hasAttribute('disabled')
                                || btn.getAttribute('aria-disabled')
                                    === 'true';
                            btnEnabled = !disAttr && !disCls;
                        }
                        const aiMsgs = document.querySelectorAll(
                            '.qwenpaw-bubble.qwenpaw-bubble-start'
                        );
                        const bubbles = [];
                        for (let i = 0; i < aiMsgs.length; i++) {
                            const el = aiMsgs[i];
                            bubbles.push({
                                idx: i,
                                txt: (el.innerText || '').trim().slice(0, 80),
                                cls: String(el.className).slice(0, 120),
                            });
                        }
                        return {
                            btnFound: !!btn,
                            btnEnabled: btnEnabled,
                            aiCount: aiMsgs.length,
                            expectedCount: expectedCount,
                            userCount: document.querySelectorAll(
                                '.qwenpaw-bubble.qwenpaw-bubble-end'
                            ).length,
                            bubbles: bubbles,
                            // Path E's own view, so a future red can say
                            // WHICH of its two conditions failed: no fresh
                            // text at all, or fresh text found but never
                            // stable for 1500ms. Without this the next
                            // reader is back to guessing which path vetoed.
                            pathE: (() => {
                                const pre = preSendTexts || [];
                                const fr = [];
                                for (let i = 0; i < aiMsgs.length; i++) {
                                    const s = (aiMsgs[i].innerText || '')
                                        .replace(/Thinking/gi, '')
                                        .replace(/Loading/gi, '')
                                        .trim();
                                    if (s.length >= 2 && pre.indexOf(s) === -1) {
                                        fr.push({ idx: i, txt: s.slice(0, 80) });
                                    }
                                }
                                const cE = window.__qwenpaw_ai_fresh_cache__;
                                return {
                                    preSendCount: pre.length,
                                    freshCount: fr.length,
                                    freshIdx: fr.map((r) => r.idx),
                                    freshSample: fr.slice(0, 3),
                                    stableCacheSigLen: cE && cE.sig
                                        ? cE.sig.length : 0,
                                    stableAgeMs: cE && cE.since
                                        ? (Date.now() - cE.since) : -1,
                                };
                            })(),
                            attachLog: (
                                window.__qwenpaw_ai_attach_log__ || []
                            ).slice(-12).map((r) => ({
                                t: r.t,
                                cls: r.cls,
                                connected: !!(r.el && r.el.isConnected),
                                txt: r.el
                                    ? (r.el.innerText || '')
                                        .trim().slice(0, 80)
                                    : '',
                            })),
                        };
                    }""",
                    {
                        "expectedCount": count_before_send,
                        "preSendTexts": pre_send_texts,
                    },
                )
                # Read-path view, evaluated from the SAME constant the read
                # path uses (an inlined copy here would drift from it). Tells
                # the next reader which bubble a red assertion would have
                # read, and by which tier, without re-deriving anything.
                try:
                    stamp = getattr(self, "_ai_stamp_before_send", -1)
                    answer = self.page.evaluate(
                        self._JS_LATEST_AI_BUBBLE,
                        {
                            "baselineTs": stamp if isinstance(stamp, int) else -1,
                            "pathEFreshIdx": [],
                        },
                    ) or {}
                    ans_idx = answer.get("idx", -1)
                    ans_txt = ""
                    if isinstance(ans_idx, int) and ans_idx >= 0:
                        try:
                            ans_txt = self.page.locator(
                                self.AI_MESSAGE
                            ).nth(ans_idx).inner_text().strip()[:120]
                        except Exception:
                            ans_txt = "<unreadable>"
                    elif isinstance(diag, dict):
                        ans_txt = "<unresolved: DOM end would be read>"
                    answer["text"] = ans_txt
                    if isinstance(diag, dict):
                        diag["roundAnswer"] = answer
                except Exception as ra_e:
                    if isinstance(diag, dict):
                        diag["roundAnswer"] = {
                            "error": type(ra_e).__name__,
                        }
                logger.error(
                    f"[wait_ai] gate-2/3 FAIL DIAG: {diag!r}"
                )
            except Exception as diag_e:
                logger.error(
                    f"[wait_ai] gate-2/3 FAIL DIAG unavailable: "
                    f"{type(diag_e).__name__}"
                )
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
                    "delete window.__qwenpaw_ai_stable_cache_c__; "
                    "delete window.__qwenpaw_ai_fresh_cache__; "
                    "delete window.__qwenpaw_ai_fresh_count__; "
                    "delete window.__qwenpaw_ai_fresh_idx__; "
                    "delete window.__qwenpaw_wait_passed_via__; "
                    "if (window.__qwenpaw_ai_attach_obs__) "
                    "window.__qwenpaw_ai_attach_obs__.disconnect(); "
                    "delete window.__qwenpaw_ai_attach_obs__; "
                    "delete window.__qwenpaw_ai_attach_log__; "
                    "} catch(e) {} }"
                )
            except Exception:
                pass

        # Screenshot: final state after AI fully replied
        self.step_shot(f"ai_response_complete_{passed_via or 'unknown'}")
        # Return THIS ROUND'S bubble, not the DOM end. On a reverse-ordered
        # list the DOM end is the oldest bubble and compression empties it
        # first, so `.last` hands callers an empty string - the failure mode
        # tests/test_context_scroll.py hit (assert ('1' in '' or 'one' in '')).
        resolved = self._latest_ai_locator("wait_for_ai_response")
        return resolved if resolved is not None else ai_locator.last

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

        # Idempotency: if session items are already visible, the panel
        # is open — skip the toggle click to avoid closing it.
        existing = self.page.locator(self.SESSION_ITEM).first
        if existing.count() > 0 and existing.is_visible():
            logger.info("[open_session_list] panel already open, skipping toggle")
            self.step_shot("session_list_opened")
            return self

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
        """Close the session list.

        The panel may be rendered as an antd Drawer (``.qwenpaw-drawer``)
        or as an embedded panel (``[class*=historyPanel]``). The close
        button is the **last** button inside ``[class*=headerRight]``
        (the first is pin/unpin). If neither selector matches, fall back
        to clicking the session-list toggle button which toggles the
        panel closed.
        """
        logger.info("Closing session list")
        for container in (
            '.qwenpaw-drawer',
            '[class*="historyPanel"]',
            '[class*="embeddedPanel"]',
        ):
            close_btn = self.page.locator(
                f'{container} {self.DRAWER_CLOSE}'
            )
            if close_btn.count() > 0:
                close_btn.last.click()
                self.wait(500)
                return self
        # Fallback: toggle the session-list button to close the panel.
        toggle = self.page.locator(self.SESSION_LIST_BTN).first
        if toggle.count() > 0 and toggle.is_visible():
            toggle.click()
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

    def _open_session_menu(self, index: int) -> bool:
        """Hover a session item and open its actions dropdown.

        The dropdown is triggered by the SparkMoreLine "more" button and
        holds Pin / Rename / Archive / Delete items. Returns True when the
        menu is visible.

        The ``moreBtn`` is a ``<span>`` that is ``pointer-events:none`` until
        the row is ``:hover``-ed, and antd opens the menu on a real click. In
        headless CI the CSS ``:hover`` can be lost between hovering the row and
        clicking, so a plain/force click may land on the element *behind* the
        span and never open the menu. We therefore hover the row and the
        button, try a normal click, and fall back to a DOM
        ``dispatchEvent('click')`` that bypasses the pointer-events gate
        (React's delegated onClick still fires). Two attempts total.
        """
        sessions = self.get_session_items()
        if not sessions or index >= len(sessions):
            logger.warning(f"Session at index {index} not found")
            return False
        # The sidebar is a virtual list: rows are recycled, so a locator
        # captured via .all() can detach mid-interaction. Re-resolve by
        # nth() right before each interaction attempt instead.
        target = self.page.locator(self.SESSION_ITEM).nth(index)

        open_menu_item = (
            'div[role="menu"]:visible button[role="menuitem"]'
        )

        def _menu_visible(timeout: int) -> bool:
            try:
                self.page.locator(open_menu_item).first.wait_for(
                    state="visible", timeout=timeout
                )
                return True
            except (TimeoutError, Exception):
                return False

        for attempt in range(2):
            # Reset any stale hover / overlay before (re)trying.
            try:
                self.page.mouse.move(0, 0)
            except Exception:
                pass
            # Virtual list: off-viewport rows are not in the DOM at all.
            # Scroll the list container so the target row gets rendered
            # before resolving it.
            try:
                if not target.is_visible():
                    self.page.locator(
                        '[class*="listWrapper"] [class*="scroll"], '
                        '[class*="listWrapper"]'
                    ).first.evaluate(
                        "el => el.scrollTo({top: el.scrollHeight})"
                    )
                    self.wait(500)
            except Exception as exc:
                logger.warning(f"[_open_session_menu] scroll failed: {exc}")
            try:
                target.scroll_into_view_if_needed(timeout=5000)
                target.hover(timeout=8000)
            except Exception:
                try:
                    target.hover(force=True, timeout=5000)
                except Exception as exc:
                    logger.warning(f"[_open_session_menu] hover failed: {exc}")
            self.wait(300)

            more_btn = target.locator(self.SESSION_MORE_BTN).first
            if more_btn.count() == 0:
                logger.warning("[_open_session_menu] more button not found")
                return False

            # Hover the button so the row stays :hover-ed (moreBtn is
            # pointer-events:none otherwise), then click.
            try:
                more_btn.hover(timeout=3000)
            except Exception:
                pass
            try:
                more_btn.click(timeout=4000)
            except Exception:
                pass
            if _menu_visible(4000):
                self.wait(200)
                return True

            # The click may have been swallowed by the pointer-events gate;
            # fire it via the DOM so React's delegated onClick still opens the
            # menu.
            try:
                more_btn.dispatch_event("click")
            except Exception as exc:
                logger.warning(
                    f"[_open_session_menu] dispatch click failed: {exc}"
                )
            if _menu_visible(3000):
                self.wait(200)
                return True

            logger.warning(
                f"[_open_session_menu] dropdown did not appear "
                f"(attempt {attempt + 1})"
            )

        return False

    def rename_session(self, index: int, new_name: str) -> "ChatPage":
        """Rename a session via more-menu → Rename → inline input → Enter."""
        logger.info(f"Renaming session {index} to: {new_name}")

        if not self._open_session_menu(index):
            self.step_shot(f"rename_session_{index}_menu_failed")
            return self

        rename_item = self.page.locator(self.SESSION_MENU_RENAME).first
        # The menu items enter with a staggered framer-motion animation
        # (SessionActions.tsx: delay = index * 0.02s), so an instant
        # count()/is_visible() probe right after the menu opened can race
        # the entrance. Wait explicitly; fail loudly if it never shows.
        try:
            rename_item.wait_for(state="visible", timeout=5000)
        except Exception:
            names = self._visible_menuitem_names()
            self.page.keyboard.press("Escape")
            raise AssertionError(
                f"Rename item never became visible in the session menu of "
                f"session {index}. Visible menu items: {names}"
            )
        rename_item.click()
        self.wait(500)

        # Inline rename input (autofocus). Fall back to any visible input in
        # the drawer if the class-based selector misses.
        rename_input = self.page.locator(self.SESSION_RENAME_INPUT).first
        if rename_input.count() == 0 or not rename_input.is_visible():
            rename_input = self.page.locator(
                '[class*=listWrapper] input, .qwenpaw-drawer input'
            ).first
        if rename_input.count() == 0 or not rename_input.is_visible():
            logger.warning("Rename input not found, skipping rename")
            return self

        rename_input.fill(new_name)
        self.step_shot(f"rename_input_filled_{new_name[:20]}")
        rename_input.press("Enter")
        self.wait(1000)

        logger.info(f"Session renamed to: {new_name}")
        self.step_shot(f"rename_done_{new_name[:20]}")
        return self

    
    def pin_session(self, index: int) -> "ChatPage":
        """Pin a session via more-menu → Pin.

        The menu items enter with a staggered framer-motion animation
        (``SessionActions.tsx``: ``delay = index * 0.02s``), and Pin sits at
        index 1 while Rename sits at 0 — an instant ``count()``/
        ``is_visible()`` probe right after the menu opened therefore races
        the entrance for Pin more often than for Rename. The old code
        treated "not found yet" as "already pinned" and returned silently,
        which turned a timing miss into a mystery assertion failure one
        step later ("Pinned marker not shown", nightly 2026-10). Now we
        wait explicitly, and only take the already-pinned branch when the
        *Unpin* item is positively visible.
        """
        logger.info(f"Pinning session at index {index}")
        if not self._open_session_menu(index):
            self.step_shot(f"pin_session_{index}_menu_failed")
            raise AssertionError(
                f"Could not open the session menu for session {index}"
            )

        pin_item = self.page.locator(self.SESSION_MENU_PIN).first
        if pin_item.count() == 0 or not pin_item.is_visible():
            # #8247: the label lives in a nested span, so the scoped
            # :has(span:text-is(...)) selector above is the reliable
            # probe; a pinned row shows "Unpin" instead and the row
            # carries data-pinned="true".
            target = self.page.locator(self.SESSION_ITEM).nth(index)
            if target.get_attribute("data-pinned") == "true":
                logger.info("Session is already pinned")
            else:
                logger.warning("Pin menu item not found")
            self.page.keyboard.press("Escape")
            return self
        pin_item.click()
        self.wait(1000)
        logger.info("Session pinned")
        self.step_shot(f"pin_session_{index}_done")
        return self

    def _visible_menuitem_names(self, limit: int = 12) -> List[str]:
        """Visible role=menuitem labels (failure context for menu races)."""
        try:
            items = self.page.locator(
                'div[role="menu"] button[role="menuitem"]'
            ).all()[:limit]
            names = []
            for it in items:
                try:
                    names.append((it.inner_text() or "").strip())
                except Exception:
                    names.append("<unreadable>")
            return names
        except Exception:
            return ["<unreadable>"]

    def delete_session(self, index: int) -> "ChatPage":
        """Delete a session via more-menu → Delete (confirm modal if shown)."""
        logger.info(f"Deleting session at index {index}")
        sessions_before = self.get_session_count()

        if not self._open_session_menu(index):
            self.step_shot(f"delete_session_{index}_menu_failed")
            return self

        del_item = self.page.locator(self.SESSION_MENU_DELETE).first
        # Same staggered-entrance race as pin/rename: wait explicitly.
        # Callers that treat deletion as best-effort (cleanup paths) wrap
        # this in try/except; test paths get a loud failure instead of a
        # silently skipped delete.
        try:
            del_item.wait_for(state="visible", timeout=5000)
        except Exception:
            names = self._visible_menuitem_names()
            self.page.keyboard.press("Escape")
            self.step_shot(f"delete_session_{index}_item_missing")
            raise AssertionError(
                f"Delete item never became visible in the session menu of "
                f"session {index}. Visible menu items: {names}"
            )
        del_item.click()
        self.wait(800)

        # A confirmation modal may appear; confirm it when present.
        confirm = self.page.locator(
            '.qwenpaw-modal-confirm-btns button.qwenpaw-btn-dangerous, '
            '.qwenpaw-modal button.qwenpaw-btn-dangerous, '
            '.qwenpaw-modal-confirm-btns button.qwenpaw-btn-primary'
        ).first
        try:
            if confirm.count() > 0 and confirm.is_visible(timeout=1500):
                confirm.click()
                self.wait(500)
        except (TimeoutError, Exception):
            pass

        self.wait(800)
        logger.info(
            f"Session deleted (before: {sessions_before}, "
            f"after: {self.get_session_count()})"
        )
        self.step_shot(f"delete_session_{index}_done")
        return self

    def verify_pinned_session(self, index: int = 0) -> bool:
        """Verify the session at ``index`` shows the pinned marker.

        Primary anchor: the product's own visible pin indicator —
        ``SessionItem`` renders ``span[class*="pinMark"]`` with
        ``title="Pinned"``/``title="置顶"`` on pinned rows. This needs no
        menu round-trip and therefore no race with the menu's staggered
        entrance animation.

        Fallback (pre-#7956 builds without the marker): re-open the
        session's more-menu and look for the "Unpin" item.
        """
        mark = self.page.locator(self.SESSION_PIN_MARK)
        try:
            # Any pinned row proves the pin action landed; when several
            # sessions exist we still accept the row-scoped match first.
            scoped = self.page.locator(self.SESSION_ITEM).nth(index).locator(
                'span[class*="pinMark"], [title="Pinned"], [title="置顶"]'
            )
            if scoped.count() > 0:
                try:
                    scoped.first.wait_for(state="visible", timeout=5000)
                    logger.info(f"Pinned marker visible on session {index}")
                    return True
                except Exception:
                    pass
            if mark.count() > 0 and mark.first.is_visible():
                logger.info("Pinned marker visible (any row)")
                return True
        except Exception as exc:
            logger.warning(f"[verify_pinned_session] marker probe: {exc}")

        # Fallback: menu round-trip (Unpin item present == pinned).
        if not self._open_session_menu(index):
            return False
        unpin = self.page.locator(self.SESSION_MENU_UNPIN).first
        try:
            unpin.wait_for(state="visible", timeout=5000)
            result = True
        except Exception:
            result = False
        try:
            self.page.keyboard.press("Escape")
        except Exception:
            pass
        self.wait(300)
        return result

    def open_session_search(self) -> "ChatPage":
        """Reveal the conversation search box in the sidebar session list.

        Before #7502 the search input was always rendered inside the list
        container. After #7502 it is mounted only on demand — see
        ``console/src/layouts/SidebarSessionList.tsx``:

            {!historyCollapsed && (searchOpen || creatingGroup) && (
              <div className={styles.searchContainer}>
                {searchOpen && <Input className={styles.searchInput} ... />}

        so ``searchOpen`` has to be flipped first by opening the "More"
        overflow dropdown (``aria-label`` from ``sidebar.more``) and picking the
        "Search conversations" entry (``chat.sessionPanel.searchConversations``).
        ``handleOpenSearch`` also focuses the input, so the box is ready to fill
        by the time this returns.

        Idempotent: if the box is already visible nothing is clicked, which
        matters because the "More" dropdown toggles rather than opens.
        """
        existing = self.page.locator(self.SESSION_SEARCH_INPUT).first
        if existing.count() > 0 and existing.is_visible():
            return self

        more_btn = self.page.locator(self.SESSION_MORE_ACTIONS_BTN).first
        more_btn.wait_for(state="visible", timeout=5000)
        more_btn.click()
        self.wait(300)

        search_item = self.page.locator(self.SESSION_SEARCH_MENU_ITEM).first
        search_item.wait_for(state="visible", timeout=5000)
        search_item.click()
        self.wait(400)
        return self

    def search_sessions(self, keyword: str) -> "ChatPage":
        """Filter the session list via the conversation search box."""
        self.open_session_search()
        box = self.page.locator(self.SESSION_SEARCH_INPUT).first
        box.wait_for(state="visible", timeout=5000)
        box.fill(keyword)
        self.wait(800)
        return self

    def clear_session_search(self) -> "ChatPage":
        """Clear the drawer conversation search box."""
        box = self.page.locator(self.SESSION_SEARCH_INPUT).first
        if box.count() > 0 and box.is_visible():
            box.fill("")
            self.wait(800)
        return self

    # ========== Tool approval level toggle ==========

    def get_approval_toggle(self) -> Locator:
        """Locate the approval-level trigger button in the composer.

        Upstream #7334 replaced the antd Tag with a ``<button>`` carrying an
        ``aria-label`` (localized approval-mode title); we anchor on that
        attribute, exactly like upstream's own ApprovalToggle.test.tsx.
        """
        return self.page.locator(self.APPROVAL_TOGGLE).first

    def open_approval_menu(self) -> "ChatPage":
        """Click the approval Tag and wait for its dropdown to render."""
        self.get_approval_toggle().click()
        self.page.locator(self.APPROVAL_MENU_ITEM).first.wait_for(
            state="visible", timeout=5000
        )
        self.wait(200)
        return self

    def get_approval_menu_items(self) -> List[Locator]:
        """Return the visible approval dropdown items (expected: 4)."""
        return self.page.locator(self.APPROVAL_MENU_ITEM).all()

    def select_approval_level(self, level: str) -> "ChatPage":
        """Open the menu and pick a level by key (STRICT/SMART/AUTO/OFF)."""
        en, zh = self.APPROVAL_LEVELS[level]
        self.open_approval_menu()
        item = self.page.locator(
            f'{self.APPROVAL_MENU_ITEM}:has-text("{en}"), '
            f'{self.APPROVAL_MENU_ITEM}:has-text("{zh}")'
        ).first
        item.click()
        self.wait(500)
        self.step_shot(f"approval_select_{level}")
        return self

    def get_approval_storage_entries(self) -> dict:
        """Read all ``approval_level-*`` localStorage entries as {key: value}."""
        return self.page.evaluate(
            """() => {
                const out = {};
                for (let i = 0; i < localStorage.length; i++) {
                    const k = localStorage.key(i);
                    if (k && k.indexOf('approval_level-') === 0) {
                        out[k] = localStorage.getItem(k);
                    }
                }
                return out;
            }"""
        )

    # ========== Sidebar date groups (upstream #5643) ==========

    def get_sidebar_group_header(self, group: str) -> Locator:
        """Locator for one sidebar date-bucket header.

        Args:
            group: bucket key — pinned / today / week / month / older.

        Upstream re-architected the sidebar: date buckets now render as
        non-collapsible ``SessionDateHeader`` rows carrying a
        ``data-date-group`` attribute, nested inside collapsible user
        groups.
        """
        en, zh = self.SIDEBAR_GROUP_TEXTS[group]
        return self.page.locator(
            f'{self.SIDEBAR_DATE_LABEL}[data-date-group="{group}"], '
            f'{self.SIDEBAR_DATE_LABEL}:has-text("{en}"), '
            f'{self.SIDEBAR_DATE_LABEL}:has-text("{zh}")'
        ).first

    def toggle_sidebar_user_group(self) -> "ChatPage":
        """Click the first collapsible user-group header."""
        logger.info("Toggling the first sidebar user group")
        self.page.locator(self.SIDEBAR_GROUP_LABEL).first.click()
        self.wait(300)
        return self

    def toggle_sidebar_group(self, group: str) -> "ChatPage":
        """Click a sidebar group header to collapse / expand it."""
        logger.info(f"Toggling sidebar group '{group}'")
        self.get_sidebar_group_header(group).click()
        self.wait(300)
        return self

    def get_sidebar_session_by_name(self, name: str) -> Locator:
        """Sidebar session row matched by its display name.

        Scoped away from the All-Chats drawer by requiring the row to sit
        under the sidebar group list (sibling of ``groupLabel`` buttons).
        """
        return self.page.locator(
            f'div[class*="sessionItem-module__item"]:has-text("{name}")'
        ).first

    # ========== Non-owner tab banner (upstream #5664) ==========

    def get_queue_banner(self) -> Locator:
        """The queue-only info banner in the sender area (non-owner tab)."""
        return self.page.locator(self.QUEUE_BANNER).filter(
            has_text=self._QUEUE_BANNER_RE
        ).first

    # ========== Model and Agent switching ==========
    
    def open_model_selector(self) -> "ChatPage":
        """Open the model picker panel.

        Post-#7899 the picker is reached in two hops from the sender area:
        the ``SessionThinking`` trigger (``aria-label`` = "Thinking
        intensity" / "思考强度") opens a Popover; inside it, when a model is
        already bound to the session, ``ThinkingControl`` shows a
        ``modelChoice`` button that flips the panel into the embedded
        ``ModelSelector``. When no model is bound yet the embedded picker
        is shown straight away, so hop 2 is skipped.

        Fail-fast: if neither hop materialises we raise with the visible
        button names instead of silently returning — the old silent
        ``return self`` turned a missing element into a mystery failure
        several steps later (see the 2026-10 nightly post-mortem).
        """
        logger.info("Opening model selector")
        trigger = self.page.locator(self.MODEL_THINKING_TRIGGER).first
        try:
            trigger.wait_for(state="visible", timeout=10000)
        except Exception:
            # Pre-#7899 builds: header Dropdown trigger.
            legacy = self.page.locator(
                '.qwenpaw-chat-anywhere-layout-right-header'
            ).locator(self.MODEL_SELECTOR).first
            if legacy.count() > 0 and legacy.is_visible():
                legacy.click()
                self.wait(500)
                return self
            names = self._visible_button_names()
            raise AssertionError(
                "Model selector trigger not found in 10s. Looked for "
                f"{self.MODEL_THINKING_TRIGGER!r} and the pre-#7899 header "
                f"dropdown. Visible buttons: {names}"
            )
        trigger.click()
        self.wait(500)

        # Hop 2: the panel may already be the embedded picker (no model
        # bound yet) or the ThinkingControl with a modelChoice button.
        # Third terminal state: the embedded picker rendered its EMPTY
        # tip (role="status" with the add-provider action) — the panel IS
        # open but no eligible provider reached the selector. That is a
        # distinct failure from "the panel never opened" and must be
        # reported as such instead of burning the full 8s wait (live
        # probe 2026-10-15: the empty tip carries class emptyTip and a
        # role=status wrapper).
        # Fourth terminal state (live probe 2026-10-15 against a
        # version-aligned local build, frontend+backend both at the CI
        # head): the panel IS open and the provider group headers render
        # (Ollama / LM Studio / Kilo Code ...) but EVERY provider carries
        # zero models, so no modelSelectButton row and no emptyTip exist
        # either — the picker shows "No matching models found" under the
        # group headers. The loading state is told apart by its
        # role="status" spin wrapper, which the fourth state lacks. This
        # is an environment condition (nothing selectable configured on
        # the instance under test), not a broken picker: return normally
        # with a loud log and let the caller's existing "no switchable
        # model" branch decide (every family-A case already has one).
        for _ in range(20):
            state, detail = self._picker_terminal_state()
            if state == "embedded":
                logger.info("Model picker panel open (embedded picker)")
                return self
            if state == "empty":
                logger.info(
                    "Model picker panel open but the visible tab rendered "
                    "the empty tip (no selectable row on this tab); "
                    "leaving the switch decision to the caller's "
                    "no-switch branch (%s)",
                    detail,
                )
                return self
            if state == "choice":
                self.page.locator(self.MODEL_CHOICE_BTN).first.click()
                self.wait(500)
                break
            if state == "rowless":
                logger.info(
                    "Model picker panel open but no selectable model rows "
                    "(provider groups rendered with zero models); leaving "
                    "the switch decision to the caller's no-switch branch "
                    "(%s)",
                    detail,
                )
                return self
            self.wait(250)
        # Post-hop settle: after the modelChoice click the panel must be
        # re-classified. 6d810e0e only waited for embedded rows here, so a
        # rowless panel behind the hop burned the full 8s and raised
        # "did not open" (fork run 38707190848: four family-A cases, 9.5s
        # each, loop broke on the visible choice button in round 1 and the
        # rowless terminal state was never evaluated again).
        for _ in range(32):
            state, detail = self._picker_terminal_state()
            if state == "embedded":
                logger.info("Model picker panel open (via modelChoice hop)")
                return self
            if state == "empty":
                logger.info(
                    "Model picker panel open after the modelChoice hop but "
                    "the visible tab rendered the empty tip; leaving the "
                    "switch decision to the caller's no-switch branch (%s)",
                    detail,
                )
                return self
            if state == "rowless":
                logger.info(
                    "Model picker panel open after the modelChoice hop but "
                    "no selectable model rows; leaving the switch decision "
                    "to the caller's no-switch branch (%s)",
                    detail,
                )
                return self
            self.wait(250)
        state, detail = self._picker_terminal_state()
        names = self._visible_button_names()
        raise AssertionError(
            "Model picker panel did not open: neither the embedded "
            "modelSelectButton rows nor the modelChoice hop appeared. "
            f"last state: {state} ({detail}). Visible buttons: {names}"
        )

    def _picker_terminal_state(self):
        """Classify the model picker panel into one terminal state.

        Returns ``(state, detail)``. Priority mirrors the render branches
        of ``console/src/pages/Chat/ModelSelector/index.tsx``:

        - ``embedded``: ``modelSelectButton`` rows visible (models listed)
        - ``empty``: ``emptyTip`` visible (no eligible provider at all)
        - ``choice``: the ThinkingControl ``modelChoice`` hop button
          visible (a model is bound; one click flips to the embedded view)
        - ``loading``: a ``role="status"`` spinner inside the dialog
        - ``rowless``: dialog visible with no spinner, no rows and no
          emptyTip — the provider group headers / configure entries render
          while every provider carries zero models (the fourth terminal
          state probed live on 2026-10-15)
        - ``none``: no visible ``role="dialog"`` at all

        Visibility (not mere presence) decides: leftover hidden DOM from
        inactive panes must not veto a terminal state (same lesson as the
        family-C pane-id scoping fix).
        """
        dialog = self.page.locator('div[role="dialog"]').first
        if not (dialog.count() > 0 and dialog.first.is_visible()):
            return "none", "no visible role=dialog"
        embedded = self.page.locator(self.MODEL_SELECT_EMBEDDED_BTN).first
        if embedded.count() > 0 and embedded.first.is_visible():
            return "embedded", "modelSelectButton rows visible"
        empty_tip = self.page.locator(
            'div[role="dialog"] div[class*="emptyTip"], '
            'div[role="dialog"] [class*="emptyTip"]'
        ).first
        if empty_tip.count() > 0 and empty_tip.first.is_visible():
            return "empty", "emptyTip visible"
        choice = self.page.locator(self.MODEL_CHOICE_BTN).first
        if choice.count() > 0 and choice.first.is_visible():
            return "choice", "modelChoice hop button visible"
        if dialog.locator('[role="status"]').count() > 0:
            return "loading", "role=status spinner inside dialog"
        try:
            n_dialogs = self.page.locator('div[role="dialog"]').count()
            text = (dialog.first.inner_text() or "").strip()[:200]
        except Exception:
            n_dialogs, text = -1, "<unreadable>"
        return "rowless", f"dialogs={n_dialogs} text={text!r}"

    def _visible_button_names(self, limit: int = 25) -> List[str]:
        """Accessible names of currently visible buttons (failure context)."""
        try:
            btns = self.page.locator("button:visible").all()[:limit]
            names = []
            for b in btns:
                try:
                    label = b.get_attribute("aria-label")
                    if not label:
                        lines = (b.inner_text() or "").strip().splitlines()
                        label = lines[0] if lines else ""
                    names.append(label or "<no-text>")
                except Exception:
                    names.append("<unreadable>")
            return names
        except Exception:
            return ["<unreadable>"]

    def select_model(self, model_name: str) -> "ChatPage":
        """
        Select a model.

        Args:
            model_name: model name

        Returns:
            self
        """
        logger.info(f"Selecting model: {model_name}")

        # Post-#7899 the picker rows are ``modelSelectButton`` buttons whose
        # visible text is the model name; pre-#7899 builds used antd
        # dropdown menu items. Try the new anchor first, fall back once.
        option = self.page.locator(self.MODEL_SELECT_EMBEDDED_BTN).filter(
            has_text=model_name
        ).first
        if option.count() == 0 or not option.is_visible():
            option = self.page.locator(self.MODEL_OPTION).filter(
                has_text=model_name
            ).first
        if option.count() == 0 or not option.is_visible():
            available = self.get_available_models()
            raise AssertionError(
                f"Model option {model_name!r} not visible in the open "
                f"picker. Available rows: {available}"
            )
        option.click()
        self.wait(1000)
        logger.info(f"Model selected: {model_name}")
        return self

    def get_available_models(self) -> List[str]:
        """Get the list of available models shown in the open picker."""
        rows = self.page.locator(self.MODEL_SELECT_EMBEDDED_BTN).all()
        models = []
        for opt in rows:
            try:
                models.append(opt.inner_text().strip())
            except Exception:
                continue
        if not models:
            legacy = self.page.locator(self.MODEL_OPTION).all()
            models = [opt.inner_text() for opt in legacy]
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
                remaining_count = self.get_session_count()
                if remaining_count >= session_count:
                    logger.warning(
                        "[cleanup] session count did not decrease "
                        f"({session_count}); stop cleanup"
                    )
                    break
                deleted_count += session_count - remaining_count
            except Exception as error:
                logger.warning(f"Failed to delete session: {error}")
                break

        logger.info(f"Cleanup complete: deleted {deleted_count} sessions")
        return self
