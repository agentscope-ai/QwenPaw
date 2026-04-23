# -*- coding: utf-8 -*-
"""Prompt templates for proactive conversation feature."""

PROACTIVE_TASK_EXTRACTION_PROMPT = (
    "You are given the user's recent session contexts and current screen "
    "content (if provided) in a reversed order.\n"
    "\n"
    "Your job:\n"
    "1. Find 1–3 likely high-level goals the user requests (prioritize those "
    "mentioned repeatedly or recently).\n"
    "2. For each goal, create one **new, concrete query** that helps the user "
    "move forward—**not** a repeat of past commands or searches.\n"
    "\n"
    "A good goal:\n"
    "- Based only on user request or user messages in the provided context.\n"
    "\n"
    "A good query:\n"
    "- Specific, actionable, and tool-friendly (e.g., a search or request).\n"
    "- Offers asisstance the user likely needs *now*, or queries for "
    "the newest information to user's interest.\n"
    "\n"
    "Output ONLY a JSON object with this structure:\n"
    "{\n"
    '  "tasks": [\n'
    "    {\n"
    '      "task": "short goal description",\n'
    '      "query": "concrete next query",\n'
    '      "why": "why this goal is likely and why this query helps"\n'
    "    }\n"
    "  ]\n"
    "}\n"
    "\n"
    "Rules:\n"
    "- Return 1 to 3 tasks, ordered by priority (frequency and recency).\n"
    "- Do not create query only based on screenshot, MUST consider session "
    "contexts as well.\n"
    "- Do not duplicate anything already in context, especially previous "
    "[PROACTIVE] labeled messages you have sent.\n"
    "- Do not use any tools in inference, answer after thinking directly.\n"
    "- At least return 1 task as long as the contexts are not empty.\n"
    "- No extra text, only valid JSON.\n"
)


PROACTIVE_USER_FACING_MESSAGE_PROMPT = (
    "Based on the following gathered information, create a helpful proactive "
    "message for the user:\n"
    "\n"
    "Gathered Information:\n"
    "{gathered_info}\n"
    "\n"
    "Remember to be helpful but not intrusive. Provide concise, actionable "
    "information addressing the user's likely needs based on the context.\n"
    "\n"
    "When crafting the message, consider using reference phrases like:\n"
    "- \"I noticed you've been focusing on [topic/task], here's some "
    'information that might help..."\n'
    "- \"I've observed your interest in [topic], so I've gathered the "
    'following..."\n'
    "- \"I see you're working on [task], would you like to know more about"
    '..."\n'
    "- \"I noticed you've been looking into [topic], here are some updates/"
    'resources..."\n'
    "- \"I've seen you're concerned with [issue], here's what I found "
    'regarding that..."\n'
    "\n"
    "These phrases can help frame your message as being attentive to the "
    "user's repeated interests rather than intrusive.\n"
    "Answer in {language} language.\n"
    "\n"
    'IMPORTANT: Begin your response with the identifier "[PROACTIVE] " to '
    "indicate this is a proactive message.\n"
)
