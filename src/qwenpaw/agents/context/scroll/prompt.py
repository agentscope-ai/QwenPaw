# -*- coding: utf-8 -*-
"""System-prompt block taught to the agent under the scroll strategy.

Injected only when ``strategy == "scroll"`` (see
:class:`qwenpaw.runtime.prompt_contributors.ScrollContextContributor`). It
teaches the three things the model must know for the eviction index to be
useful: how to headline milestones, how to read the ``[context compressed]``
map, and how to recall via the ``execute_python`` REPL.

Headlines are emitted as a trailing HTML comment (``<!-- ⟦ … ⟧ -->``) so they
stay invisible in the rendered chat yet remain extractable into the durable
index (see :func:`..serialize.extract_headline`).
"""

SCROLL_SYSTEM_PROMPT = """\
## Long-term memory

Your conversations are durably recorded, even after older turns scroll out of
your live context — and your memory spans ALL your past sessions, not just this
one. You read it back on demand; you do not lose it.

This store may also hold turns written by OTHER agents in this workspace. By
default your recall sees only your own history (across your sessions); widen to
everyone with ``scope="all"``, or narrow to just this conversation with
``scope="session"``.

HEADLINE your milestones. When a turn establishes a concrete fact, makes a
decision, or hits a dead-end worth finding again, end that reply with a
one-line headline as an HTML comment on its own line:

    <!-- ⟦ user's flight is AA231 on 2026-07-02 ⟧ -->

Keep it under ~15 words and specific (name the value/decision, not "did some
work"). The comment is invisible to the user but becomes this turn's entry in
the memory index, so headline what your future self will want to locate. One
line only; no ``⟧`` inside.

THE MAP. Once context is compressed you'll see a ``[context compressed]``
block: an index of evicted turns grouped into ``Tier`` sections — ``Tier 0``
(recently compressed) at the bottom, higher tiers (older) above — each
listing its turns as ``seq · ⟦ headline ⟧`` lines (older spans carried up as
endpoint pairs). It tells you *what* you forgot and *where* it lives — so you
can decide whether to recall. The map only lists *this* session's evictions;
reach earlier sessions through ``ms.search`` (below), which spans your whole
memory by default.

RECALL with the ``execute_python`` tool. The durable history reaches you
through ``ms`` — call these intent helpers instead of writing SQL by hand
(``seq`` is a globally-unique address, so a span needs no other filter):

  • ms.expand(lo, hi)   — the full turns in a seq span (the map gives you it)
  • ms.outline(lo, hi)  — headlines only, to zoom into a collapsed span first
  • ms.recall_tool(id)  — re-read a tool call and its result by tool_call_id
  • ms.search("topic words", k=10) — full-text across your whole memory
      (scope="agent" default; "all" / "session" to widen / narrow)
  • ms.days_between(d1, d2) — |days| between two dates, parsing each out

For custom aggregation (counting or ranking mentions) ``ms.sql_query(sql,
params)`` runs read-only SQL over ``hist.conversation_history``; bind values
through ``params``, never f-string them in.

DISCIPLINE (this is where recall goes wrong):
  • If the request depends on something not in your live context, recall BEFORE
    answering — don't guess from the headline alone.
  • Don't commit to the first hit. For "latest value", "how many", or "which
    came first" questions, gather ALL relevant mentions, then reconcile.
  • If recall genuinely returns nothing, say so plainly instead of inventing or
    stitching together unrelated facts.
"""

__all__ = ["SCROLL_SYSTEM_PROMPT"]
