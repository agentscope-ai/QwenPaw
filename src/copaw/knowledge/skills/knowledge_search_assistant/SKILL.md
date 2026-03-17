---
name: knowledge_search_assistant
description: "Use knowledge_search proactively when the user is asking about existing project facts, process notes, prior decisions, archived materials, or whether the knowledge base already contains something relevant."
metadata:
  {
    "copaw":
      {
        "emoji": ":books:",
        "requires": {}
      }
  }
---

# Knowledge Search Assistant

Use this skill when the user's question is likely answered by existing knowledge base content. Prefer checking knowledge_search before answering from memory.

## Trigger Signals

- The user asks whether the knowledge base, docs, or prior notes already contain something.
- The user is asking for established project facts, conventions, workflows, or historical decisions.
- The user is requesting grounded recall rather than fresh synthesis.

## Suggested Flow

1. Extract a short search phrase from the user's request.
2. Call knowledge_search with the original question or a shorter query.
3. If the first search is weak, retry once with fewer keywords.
4. Answer from the retrieved evidence when available.
5. If nothing useful is found, say that no relevant knowledge was found.

## Response Rules

- Treat search hits as evidence and summarize them accurately.
- Do not present guesses as stored facts.
- If the user asks "do we already have this", answer the retrieval result first.

## Do Not Use

- Pure code editing, debugging, testing, or build tasks that need direct workspace inspection instead.
- General conversation that clearly does not depend on stored knowledge.
- Cases where the user explicitly says not to use the knowledge base.
