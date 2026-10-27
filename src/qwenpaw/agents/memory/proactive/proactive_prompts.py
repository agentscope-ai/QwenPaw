# -*- coding: utf-8 -*-
"""Rendering templates for ReMe proactive agenda delivery.

QwenPaw never asks a model to write these: the agenda ReMe produced is
already user-facing prose (``opener`` / ``next_action``), so delivery is
pure string assembly.  That is also what keeps the agent from treating an
agenda item as an instruction to execute -- it only ever presents one.
"""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .proactive_agenda import AgendaItem

SUPPORTED_LANGUAGES = ("zh", "en")
DEFAULT_LANGUAGE = "en"

_TEXTS: dict[str, dict[str, str]] = {
    "zh": {
        "receipt_header": "**主动议程建议**（{date}，共 {count} 条）",
        "receipt_footer": (
            "想深入了解或直接执行其中某一条，把编号告诉我就行。"
            "我只负责呈现建议，不会自行执行。"
        ),
        "inbox_title_idle": "主动议程建议 ({count})",
        "inbox_title_cron": "今日主动议程 ({count})",
        "inbox_footer": (
            "以上条目来自长期记忆的主动议程。收件箱不支持直接执行，"
            "想推进哪一条，在聊天里告诉我编号或标题即可。"
        ),
        "next_action": "↳ 可以让我：{text}",
        "due": "⏰ 截止/时间：{text}",
        "empty_after_refresh": (
            "今天暂时没有值得主动提醒你的新议程。我会继续留意记忆里的"
            "变化，有新内容时在空闲阶段推送到收件箱。"
        ),
        "empty_after_refresh_forced": (
            "已从 topic extraction 重新生成过一次议程，今天仍然没有值得"
            "主动提醒你的新内容。有新素材时我会推送到收件箱。"
        ),
        "empty_throttled": (
            "距上次议程刷新不足 {minutes} 分钟，本次沿用现有议程；"
            "目前没有未读条目。"
        ),
        "empty_all_delivered": (
            "最近的 {count} 条议程已经推送过，{days} 天冷却期内不再重复"
            "展示。"
        ),
        "empty_unavailable": (
            "暂时读不到主动议程：长期记忆（ReMe）未启动或议程读取失败。"
            "可在 运行配置 → 长期记忆 中检查配置后重试。"
        ),
        "disabled": (
            "主动议程未启用。请在 运行配置 → 长期记忆 中打开"
            "「主动议程 (Proactive)」开关后再使用 /proactive。"
        ),
        "rebuild_started": (
            "当前没有待展示的主动议程。我已在后台让 ReMe 从 topic "
            "extraction 开始重建今天的议程，通常需要几分钟。完成后我会"
            "单独发一条回执，不会一直占着这个会话。"
        ),
        "rebuild_started_inbox": "重建出的议程也会放进收件箱，方便稍后查看。",
        "rebuild_in_progress": (
            "主动议程已经在后台重建中，通常需要几分钟；完成后我会单独发"
            "一条回执，不用重复触发。"
        ),
        "rebuild_done_inbox": (
            "**主动议程已重建**（{count} 条，用时约 {seconds} 秒）\n\n"
            "已放入收件箱。想推进哪一条，在这里告诉我编号或标题就行。"
        ),
        "rebuild_empty": (
            "主动议程已重建（用时约 {seconds} 秒），但今天没有值得主动"
            "提醒你的新条目。有新素材时我会推送到收件箱。"
        ),
        "rebuild_failed": "主动议程这次没有重建成功（{error}）。稍后可以再试一次 /proactive。",
    },
    "en": {
        "receipt_header": "**Proactive agenda** ({date}, {count} item(s))",
        "receipt_footer": (
            "Tell me which number you want explored or carried out. I only "
            "present these suggestions; I never execute them on my own."
        ),
        "inbox_title_idle": "Proactive agenda suggestions ({count})",
        "inbox_title_cron": "Today's proactive agenda ({count})",
        "inbox_footer": (
            "These items come from the proactive agenda distilled from "
            "long-term memory. The inbox cannot run them: tell me the "
            "number or title in chat to take one forward."
        ),
        "next_action": "-> You could ask me to: {text}",
        "due": "-> Due/at: {text}",
        "empty_after_refresh": (
            "Nothing worth raising today. I'll keep watching your memory "
            "and drop anything new into your inbox while idle."
        ),
        "empty_after_refresh_forced": (
            "I rebuilt the agenda from topic extraction and there is still "
            "nothing worth raising today. New material will land in your "
            "inbox."
        ),
        "empty_throttled": (
            "The agenda was refreshed less than {minutes} minutes ago, so "
            "I reused it; nothing unread right now."
        ),
        "empty_all_delivered": (
            "The latest {count} item(s) were already delivered and stay "
            "hidden for {days} day(s) to avoid repeats."
        ),
        "empty_unavailable": (
            "The proactive agenda is unavailable right now: long-term "
            "memory (ReMe) is not started or the read failed. Check Run "
            "Config -> Long-term Memory and try again."
        ),
        "disabled": (
            "Proactive agenda is disabled. Enable it under Run Config -> "
            "Long-term Memory before using /proactive."
        ),
        "rebuild_started": (
            "Nothing to present right now. I started rebuilding today's "
            "agenda from topic extraction in the background, which usually "
            "takes a few minutes. The receipt follows as a separate message "
            "instead of holding this chat open."
        ),
        "rebuild_started_inbox": (
            "The rebuilt agenda also lands in your inbox, so you can read "
            "it later."
        ),
        "rebuild_in_progress": (
            "The agenda is already being rebuilt in the background, which "
            "takes a few minutes. The receipt follows as a separate message; "
            "no need to trigger it again."
        ),
        "rebuild_done_inbox": (
            "**Proactive agenda rebuilt** ({count} item(s), about "
            "{seconds}s)\n\n"
            "It is in your inbox now. Tell me the number or title here to "
            "take one forward."
        ),
        "rebuild_empty": (
            "The agenda was rebuilt (about {seconds}s) and nothing is worth "
            "raising today. New material will land in your inbox."
        ),
        "rebuild_failed": (
            "The proactive agenda rebuild did not succeed this time "
            "({error}). Try /proactive again later."
        ),
    },
}

EMPTY_STATE_KEYS = (
    "empty_after_refresh",
    "empty_after_refresh_forced",
    "empty_throttled",
    "empty_all_delivered",
    "empty_unavailable",
    "disabled",
)


def pick_language(agent_language: Any) -> str:
    """Normalise an agent language tag to a supported template key."""
    text = str(agent_language or "").strip().lower()
    if text.startswith("zh"):
        return "zh"
    return DEFAULT_LANGUAGE


def texts_for(agent_language: Any) -> dict[str, str]:
    return _TEXTS[pick_language(agent_language)]


def text_for(key: str, agent_language: Any, **kwargs: Any) -> str:
    """One localized template, formatted with ``kwargs``."""
    template = texts_for(agent_language).get(key, "")
    if not template:
        return ""
    try:
        return template.format(**kwargs)
    except (KeyError, IndexError):
        return template


def render_agenda_items(
    items: list["AgendaItem"],
    agent_language: Any,
    *,
    numbered: bool = True,
) -> str:
    """Render agenda items as a compact markdown block."""
    texts = texts_for(agent_language)
    blocks: list[str] = []
    for index, item in enumerate(items, start=1):
        prefix = f"**{index}. " if numbered else "**"
        head = f"{prefix}{item.label}**"
        if item.kind:
            head = f"{head} `{item.kind}`"
        lines = [head]
        if item.opener and item.opener != item.label:
            lines.append(item.opener)
        if item.due_at:
            lines.append(texts["due"].format(text=item.due_at))
        if item.next_action:
            lines.append(texts["next_action"].format(text=item.next_action))
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def render_agenda_receipt(
    items: list["AgendaItem"],
    agent_language: Any,
    *,
    date: str = "",
) -> str:
    """The in-chat ``/proactive`` receipt: header + items + footer."""
    texts = texts_for(agent_language)
    header = texts["receipt_header"].format(
        date=date or "-",
        count=len(items),
    )
    body = render_agenda_items(items, agent_language)
    return f"{header}\n\n{body}\n\n{texts['receipt_footer']}"


def build_inbox_body(
    items: list["AgendaItem"],
    agent_language: Any,
    *,
    date: str = "",
) -> str:
    """The inbox card body: reading-only, no execution affordance."""
    texts = texts_for(agent_language)
    body = render_agenda_items(items, agent_language)
    stamp = f"_{date}_" if date else ""
    head = f"{stamp}\n\n" if stamp else ""
    return f"{head}{body}\n\n{texts['inbox_footer']}"


def inbox_title(
    count: int,
    agent_language: Any,
    *,
    channel: str = "cron",
) -> str:
    texts = texts_for(agent_language)
    key = "inbox_title_idle" if channel == "idle" else "inbox_title_cron"
    return texts[key].format(count=count)
