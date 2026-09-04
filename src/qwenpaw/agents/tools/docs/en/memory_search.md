---
summary: Semantic search in MEMORY.md for past information
---

Semantic search in memory files to find relevant past conversations and decisions.

- **Prerequisites**:
  - Enable "Memory Management" in **Agent → Runtime Config**
  - If not configured, tool calls will return an error
- `query`: Semantic search query
- `max_results`: Max number of results (default 5)
- `min_score`: Minimum similarity threshold (default 0.1)
- Search scope: MEMORY.md and memory/*.md files in the current agent's workspace root directory
