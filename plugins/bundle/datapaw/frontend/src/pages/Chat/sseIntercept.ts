/**
 * Wraps an SSE ReadableStream to intercept chat SSE side-channels and live text.
 *
 * - Lines whose JSON payload has `object === "task_status"` are **removed** from
 *   the downstream stream (DAG 状态改由 /api/tasks/dag/events 驱动，此处仅过滤避免 chat 报错).
 * - Lines with `object === "content", type === "text", delta === true` are
 *   forwarded to `onLiveText` for real-time display in the task drawer.
 * - All other content is passed through unchanged.
 * - On any error the stream degrades to full pass-through so the chat is never blocked.
 */
/** Session-level plan tools (no node_id) — trigger task-card fetch from chat SSE. */
export type PlanToolStreamEvent = { name: string; phase: "call" | "result" };

const TASK_CARD_PLAN_TOOLS = new Set(["create_plan", "finish_plan"]);

function notifyPlanToolInStream(
  name: string | undefined,
  phase: PlanToolStreamEvent["phase"],
  onPlanTool?: (event: PlanToolStreamEvent) => void,
): void {
  if (!onPlanTool || !name || !TASK_CARD_PLAN_TOOLS.has(name)) return;
  onPlanTool({ name, phase });
}

export function createInterceptedStream(
  originalBody: ReadableStream<Uint8Array>,
  onLiveText?: (text: string, metadata?: { node_id?: string; graph_id?: string }, msg_id?: string) => void,
  onToolCall?: (data: { call_id: string; name: string; arguments: string }, metadata?: { node_id?: string; graph_id?: string }) => void,
  onThinking?: (thinking: string, metadata?: { node_id?: string; graph_id?: string }) => void,
  onToolResult?: (data: { call_id: string; name: string; output: string }, metadata?: { node_id?: string; graph_id?: string }) => void,
  onPlanTool?: (event: PlanToolStreamEvent) => void,
): ReadableStream<Uint8Array> {
  const decoder = new TextDecoder('utf-8', { fatal: false });
  const encoder = new TextEncoder();

  // Buffer for incomplete lines that span across chunks.
  let lineBuffer = '';
  // Track whether the previous line was a filtered task_status data line,
  // so we can also suppress its trailing blank-line separator.
  let lastLineWasFiltered = false;

  /**
   * Process a single complete line from the SSE stream.
   * Returns the line (with its original line ending) to pass downstream,
   * or an empty string if the line should be filtered out.
   */
  function processLine(line: string): string {
    // Blank line = SSE event delimiter.
    // If the previous data line was filtered, swallow this blank line too.
    if (line === '') {
      if (lastLineWasFiltered) {
        lastLineWasFiltered = false;
        return '';
      }
      return '\n';
    }

    // Only inspect lines that start with "data:"
    if (line.startsWith('data:')) {
      const jsonStr = line.slice(5).trimStart();

      if (jsonStr) {
        try {
          const parsed = JSON.parse(jsonStr);

          if (parsed && parsed.object === 'task_status') {
            lastLineWasFiltered = true;
            return ''; // filter out — task card 由 tasks API 更新
          }

          // Forward live text delta to onLiveText callback (not filtered from stream)
          if (
            onLiveText &&
            parsed &&
            parsed.object === 'content' &&
            parsed.type === 'text' &&
            parsed.delta === true &&
            typeof parsed.text === 'string'
          ) {
            onLiveText(parsed.text, parsed.metadata, parsed.msg_id);
          }

          // 拦截工具调用事件 (tool_use - 有 arguments)
          if (
            onToolCall &&
            parsed &&
            parsed.object === 'content' &&
            parsed.type === 'data' &&
            parsed.data?.name &&
            (parsed.data.arguments !== undefined || parsed.data.input !== undefined)
          ) {
            const toolData = {
              call_id: parsed.data.call_id || parsed.data.id || '',
              name: parsed.data.name,
              arguments: parsed.data.arguments || parsed.data.input || '',
            };
            // 如果 arguments 是对象，转为 JSON 字符串
            if (typeof toolData.arguments === 'object' && toolData.arguments !== null) {
              toolData.arguments = JSON.stringify(toolData.arguments, null, 2);
            }
            notifyPlanToolInStream(toolData.name, "call", onPlanTool);
            onToolCall(toolData, parsed.metadata);
          }

          // 拦截工具结果事件 (tool_result - 有 output)
          if (
            onToolResult &&
            parsed &&
            parsed.object === 'content' &&
            parsed.type === 'data' &&
            parsed.data?.name &&
            parsed.data.output !== undefined
          ) {
            const resultData = {
              call_id: parsed.data.call_id || parsed.data.id || '',
              name: parsed.data.name,
              output: typeof parsed.data.output === 'object' ? JSON.stringify(parsed.data.output, null, 2) : (parsed.data.output || ''),
            };
            notifyPlanToolInStream(resultData.name, "result", onPlanTool);
            onToolResult(resultData, parsed.metadata);
          }

          // 拦截完整消息格式的工具调用 (object="message", type 包含 "plugin_call")
          if (
            onToolCall &&
            parsed &&
            parsed.object === 'message' &&
            parsed.type &&
            (parsed.type === 'plugin_call' || parsed.type === 'PLUGIN_CALL') &&
            Array.isArray(parsed.content)
          ) {
            for (const contentItem of parsed.content) {
              if (contentItem?.type === 'data' && contentItem?.data?.name) {
                const d = contentItem.data;
                const toolData = {
                  call_id: d.call_id || d.id || '',
                  name: d.name,
                  arguments: typeof d.arguments === 'object' ? JSON.stringify(d.arguments, null, 2) : (d.arguments || d.input || ''),
                };
                if (typeof toolData.arguments === 'object' && toolData.arguments !== null) {
                  toolData.arguments = JSON.stringify(toolData.arguments, null, 2);
                }
                notifyPlanToolInStream(toolData.name, "call", onPlanTool);
                onToolCall(toolData, parsed.metadata);
              }
            }
          }

          // 拦截完整消息格式的工具结果 (object="message", type 包含 "plugin_call_output")
          if (
            onToolResult &&
            parsed &&
            parsed.object === 'message' &&
            parsed.type &&
            (parsed.type === 'plugin_call_output' || parsed.type === 'PLUGIN_CALL_OUTPUT') &&
            Array.isArray(parsed.content)
          ) {
            for (const contentItem of parsed.content) {
              if (contentItem?.type === 'data' && contentItem?.data) {
                const d = contentItem.data;
                const resultData = {
                  call_id: d.call_id || d.id || '',
                  name: d.name || '',
                  output: typeof d.output === 'object' ? JSON.stringify(d.output, null, 2) : (d.output || ''),
                };
                notifyPlanToolInStream(resultData.name, "result", onPlanTool);
                onToolResult(resultData, parsed.metadata);
              }
            }
          }

          // 拦截思考内容事件（不从流中移除）
          if (
            onThinking &&
            parsed &&
            parsed.object === 'content' &&
            parsed.type === 'thinking' &&
            typeof parsed.thinking === 'string'
          ) {
            onThinking(parsed.thinking, parsed.metadata);
          }
        } catch {
          // JSON parse failed — fall through to pass-through
        }
      }
    }

    // Any non-filtered line resets the flag.
    lastLineWasFiltered = false;
    return line + '\n';
  }

  const transform = new TransformStream<Uint8Array, Uint8Array>({
    transform(chunk, controller) {
      try {
        // stream: true ensures multi-byte UTF-8 chars spanning chunks are handled
        const text = decoder.decode(chunk, { stream: true });
        const combined = lineBuffer + text;

        // Split on newline; the last element may be an incomplete line.
        const parts = combined.split('\n');
        lineBuffer = parts.pop() ?? '';

        let output = '';
        for (const part of parts) {
          output += processLine(part);
        }

        if (output.length > 0) {
          controller.enqueue(encoder.encode(output));
        }
      } catch {
        // On any unexpected error, pass the original chunk through untouched.
        controller.enqueue(chunk);
      }
    },

    flush(controller) {
      try {
        // Flush any remaining bytes from the decoder.
        const remaining = decoder.decode(new Uint8Array(), { stream: false });
        const final = lineBuffer + remaining;

        if (final.length > 0) {
          const result = processLine(final);
          if (result.length > 0) {
            controller.enqueue(encoder.encode(result));
          }
        }
      } catch {
        // Best-effort flush; nothing to do on failure.
      }
    },
  });

  return originalBody.pipeThrough(transform);
}
