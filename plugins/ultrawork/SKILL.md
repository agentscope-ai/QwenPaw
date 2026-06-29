# Ultrawork — Parallel Delegation Loop

You are operating in **Ultrawork mode**: maximum parallelism through todo decomposition and systematic completion.

## Core Protocol

1. **Decompose**: Break the task into independent, actionable todos. Save them to `.qwenpaw/loop_state/ultrawork-state.json`:
   ```json
   {
     "todos": [
       {"id": 1, "title": "...", "done": false}
     ]
   }
   ```

2. **Execute**: For each todo:
   - Work on it directly, or use `spawn_subagent` to delegate to a parallel worker
   - Mark as `done: true` in the state file upon completion

3. **Monitor**: After each completed todo:
   - Read the state file
   - If there are more incomplete todos → continue
   - If all todos are done → output summary

4. **Auto-exit**: Unlike Ralph, Ultrawork exits automatically when all todos are cleared. No explicit `/cancel` needed.

## Rules

- **Maximize parallelism**: If todos are independent, use `spawn_subagent` to run them concurrently.
- **Update state immediately** after completing each todo.
- **Keep todos atomic**: Each todo should be completable in 1-3 tool calls.
- **Do not create new todos** unless the original decomposition missed something critical.
