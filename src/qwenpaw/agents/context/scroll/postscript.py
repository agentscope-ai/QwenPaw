# -*- coding: utf-8 -*-
"""Opt-in per-question-type recall postscripts (for memory evaluation).

NOT wired into the runtime agent — there is no question-type label at
chat time. An evaluation harness (e.g. LongMemEval, where the qtype IS
known) can import :func:`compose_postscript` and append the result to the
probe question, layering a universal recall nudge with a per-category
standard.

Each postscript states the bar a correct answer must clear and the
dominant failure mode — not a step-by-step recipe (the model already
knows its tools from the system prompt). Categories follow the standard
memory-ability taxonomy; the text is a tunable starting point.
"""
from __future__ import annotations

# Appended to every probe, whatever the category.
UNIVERSAL_POSTSCRIPT = (
    "Recall from our past conversations with execute_python (ms.search / "
    "ms.sql_query over hist.conversation_history) before answering. "
    "Reply with a plain answer once you have enough evidence; if recall "
    "genuinely turns up "
    "nothing, abstain explicitly: \"I don't have that information from our "
    'conversations."'
)

# Overrides the category postscript when the question may be unanswerable.
ABSTENTION_POSTSCRIPT = (
    "This may be unanswerable. After >=2 distinct retrieval queries "
    "(different keywords AND different surfaces) return nothing useful, "
    "abstain EXPLICITLY: "
    '"I don\'t have that information from our conversations." A similar-but-'
    "different entity is NOT a match — abstain rather than substitute the "
    "closest one."
)

# Memory-ability taxonomy: IE, MR, KU, TR, ABS, CR, EO, IF, PF, SUM.
QTYPE_POSTSCRIPT: dict[str, str] = {
    "IE": (  # Information Extraction
        "Single-fact recall. Find the exact statement that answers the "
        "question and quote its value precisely; the failure is "
        "paraphrasing into a "
        "wrong or vaguer value."
    ),
    "MR": (  # Multi-hop Reasoning
        "Spans multiple turns/sessions. Combine evidence across ALL relevant "
        "pieces; surface each, then chain them. The failure is answering from "
        "one hop and missing the rest."
    ),
    "KU": (  # Knowledge Update
        "The user revised this over time — the answer is their LATEST "
        "statement, so the first mention is probably NOT it. Account for "
        "every mention, "
        "reconcile to ONE current value; the failures are committing to an "
        "earlier value or declaring 'no change' when a later one exists."
    ),
    "TR": (  # Temporal Reasoning
        "Resolve the time the question refers to PRECISELY relative to today "
        "('two weeks ago' is a specific date), and pick the event that "
        "matches that time. Distinguish WHEN it was said from WHEN it "
        "happened. Naming the wrong event is the failure; being off by a "
        "day on a count is fine."
    ),
    "ABS": ABSTENTION_POSTSCRIPT,  # Abstention
    "CR": (  # Contradiction Resolution
        "Statements may conflict. Surface every conflicting mention with its "
        "time, then resolve to the one that should win (usually the most "
        "recent or most specific); don't present a stack of contradictory "
        "values."
    ),
    "EO": (  # Event Ordering
        "Order matters. Establish each event's real time from its "
        "content, then sort across ALL candidates; for 'which came first "
        "/ most recent' the "
        "failure is returning the first event you happen to surface."
    ),
    "IF": (  # Instruction Following
        "Recall the user's earlier instruction verbatim and apply it "
        "exactly to this response; the failure is approximating or "
        "dropping a constraint."
    ),
    "PF": (  # Preference Following
        "The topic may never have been stated verbatim — cast a WIDE net "
        "(ms.search with synonyms / related terms) to surface preferences "
        "(likes, dislikes, constraints) and ground the answer in those. Exact "
        "keyword match will miss; 'I have no info' is the wrong frame here."
    ),
    "SUM": (  # Summarization
        "Gather the full set of relevant turns across the conversation before "
        "summarizing; the failure is summarizing only what's still in "
        "view and missing evicted material."
    ),
}


def compose_postscript(qtype: str | None, *, abstention: bool = False) -> str:
    """Universal nudge + the category standard (or abstention override)."""
    if abstention:
        return f"{UNIVERSAL_POSTSCRIPT}\n\n{ABSTENTION_POSTSCRIPT}"
    extra = QTYPE_POSTSCRIPT.get((qtype or "").upper())
    return (
        f"{UNIVERSAL_POSTSCRIPT}\n\n{extra}" if extra else UNIVERSAL_POSTSCRIPT
    )


__all__ = [
    "UNIVERSAL_POSTSCRIPT",
    "ABSTENTION_POSTSCRIPT",
    "QTYPE_POSTSCRIPT",
    "compose_postscript",
]
