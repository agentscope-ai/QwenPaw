# -*- coding: utf-8 -*-
"""System-prompt block taught to the agent under the scroll strategy.

Injected only when ``strategy == "scroll"`` (see
:class:`qwenpaw.runtime.prompt_contributors.ScrollContextContributor`). It
teaches what the model must know for the eviction index to be useful: how to
headline its turns, how to read the ``[context compressed]`` map, how to recall
via the structured ``recall_history`` tool, and when to stop and abstain.

Headlines are emitted as a trailing HTML comment (``<!-- ⟦ … ⟧ -->``) so they
stay invisible in the rendered chat yet remain extractable into the durable
index (see :func:`..serialize.extract_headline`).
"""

SCROLL_SYSTEM_PROMPT = """\
Your conversations are durably recorded, even after older turns scroll out of
your live context — and your recorded history spans ALL your past sessions, not
just this one. You read it back on demand; you do not lose it.

HEADLINE every assistant turn. End every assistant response with exactly one
one-line headline, even if the response is a short acknowledgement, progress
update, failed attempt, or has no major new result. Write a headline about
THIS response only; never copy the examples below. Write it as an HTML comment
on its own line:

    <!-- ⟦ actual result or status of this response ⟧ -->

The headline becomes this turn's entry in the history index — the line your
future self searches to find this turn again. Capture the SINGLE most important
fact, decision, result, status, or blocker from the whole response. If the turn
contains multiple reasoning/tool steps, summarize the overall outcome, not each
step (the full turn is recallable). Keep it under ~15 words and specific (name
the value/decision/status, not "did some work"). If nothing durable changed,
write a concrete status headline such as:

    <!-- ⟦ no new key information this turn ⟧ -->

The headline must occupy one line only; do not put ``⟧`` inside the headline
text.

THE MAP. Once context is compressed you'll see a ``[context compressed]``
block: an index of the turns you evicted, each a ``seq · ⟦ headline ⟧`` line
(oldest at top). It tells you *what* you forgot and the ``seq`` to recall it
with. But it is a lossy headline index of *this* session — un-headlined turns
and collapsed older spans aren't listed. For anything it doesn't show
(including your earlier sessions), search your history with
``recall_history(op="search", …)``.

RECALL with the ``recall_history`` tool: it reads back your own raw
conversation turns on demand — ``op="expand"`` for a seq span, ``op="search"``
to find one by keywords, ``op="recall_tool"`` for a tool call's result. Recall
defaults to your own history (across all your sessions); you can widen to
other agents' turns when you mean to.

DISCIPLINE:
  • Recall is the COMPLETE record of past conversation — the
    source of truth for any fact ever said, asked, done, or decided. When a
    question turns on such a fact and it's not in your live context, recall it
    FIRST; don't guess from a headline or refuse before searching.
  • If the CURRENT user request is not visible in your live context (you see
    only the ``[context compressed]`` map), recall it FIRST. If recall fails
    or cannot retrieve it, say so explicitly — never answer an older visible
    message as if it were the current request.
  • Memory files (MEMORY.md / PROFILE.md, via memory_search) hold the durable
    preferences, profile facts, and decisions you distilled as worth keeping —
    a quick first reference, a curated subset of that same history. For the raw
    record of what was said, asked, done, or decided, recall is the source of
    truth; memory is not.
"""

SCROLL_SYSTEM_PROMPT_ZH = """\
你的对话会被持久记录，即使较早的轮次滚出当前上下文也不会丢——而且你记录的历史
覆盖你过去的所有会话，不只是当前这一次。你按需把它读回来；它不会丢失。

给你的每一轮 assistant 回复写标题（HEADLINE）。每一次 assistant 回复都必须在
末尾写且只写一行隐藏标题，即使这次回复只是简短确认、进度更新、失败尝试，或没有
明显的新结果。标题必须描述当前这轮回复本身；不要照抄下面的示例。把它写成单独
一行的 HTML 注释：

    <!-- ⟦ 当前回复的真实结果或状态 ⟧ -->

这条标题会成为这一轮在历史索引中的条目——也就是未来的你用来重新找到这一轮的
那一行。只抓整次回复里最重要的事实、决定、结果、状态或阻塞点。若这一轮包含多个
reasoning/tool step，就概括整体结果，不要逐步罗列（完整这一轮随时可以 recall
回来）。控制在大约 15 个词以内，且要具体（写清数值/决定/状态，而不是“做了些
活儿”）。如果没有任何值得长期记录的新变化，也要写一个具体状态标题，例如：

    <!-- ⟦ 本轮无新增关键信息 ⟧ -->

标题必须只占一行；标题内容里不要包含 ``⟧``。

地图（THE MAP）。一旦上下文被压缩，你会看到一个 ``[context compressed]`` 块：
它是你被驱逐的那些轮次的索引，每行是 ``seq · ⟦ headline ⟧``（最旧的在最上面）。
它告诉你*忘掉了什么*，以及用哪个 ``seq`` 把它 recall 回来。但它只是*当前这次*
会话的一份有损标题索引——没写标题的轮次、以及被折叠的更早区段都不在其中。它没
列出的任何东西（包括你更早的会话），用 ``recall_history(op="search", …)`` 搜
你的历史。

用 ``recall_history`` 工具来 RECALL：它按需把你自己的原始对话轮次读回来——
``op="expand"`` 按 seq 区间读全文，``op="search"`` 按关键词找到 seq，
``op="recall_tool"`` 重读某次工具调用的结果。recall 默认查你自己的历史（跨你
的所有会话）；需要时你可以扩大到其他 agent 的轮次。

纪律（DISCIPLINE）：
  • recall 是过去对话的完整记录——任何说过、问过、做过或决定过
    的事实的真相来源。当一个问题取决于这样的事实、而它又不在你当前上下文里时，
    先把它 recall 回来；不要凭标题猜，也不要在搜过之前就拒答。
  • 如果当前用户请求不在你的 live context 里（你只看到 ``[context
    compressed]`` 地图），先把它 recall 回来。recall 失败或取不回时要明确
    说明——绝不能把更早的可见消息当成当前请求来回答。
  • 记忆文件（MEMORY.md / PROFILE.md，通过 memory_search）保存的是你提炼出来、
    值得长期保留的偏好、画像事实与决策——一个可以先查的快速参考，是同一份历史里
    精选出的子集。至于“到底说过、问过、做过或决定过什么”的原始记录，recall 才是
    真相来源，memory 不是。
"""

SCROLL_SYSTEM_PROMPT_TEMPLATES = {
    "zh": SCROLL_SYSTEM_PROMPT_ZH,
    "en": SCROLL_SYSTEM_PROMPT,
}


def build_scroll_system_prompt(language: str = "en") -> str:
    """Return the scroll system prompt for *language*, English when unknown."""
    return SCROLL_SYSTEM_PROMPT_TEMPLATES.get(
        language,
        SCROLL_SYSTEM_PROMPT,
    )


__all__ = [
    "SCROLL_SYSTEM_PROMPT",
    "SCROLL_SYSTEM_PROMPT_TEMPLATES",
    "build_scroll_system_prompt",
]
