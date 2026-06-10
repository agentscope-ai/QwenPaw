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
import { handlePlanToolStreamRefresh } from "./lib/taskCardStreamRefresh";
import {
  isTaskCardRefreshTool,
  type PlanToolStreamEvent,
} from "./lib/planToolStream";

export type { PlanToolStreamEvent } from "./lib/planToolStream";
/** Legacy alias — ui task-card still listens for create_plan via onPlanTool. */
const TASK_CARD_STREAM_TOOL = "create_plan";

function notifyPlanToolInStream(
  name: string | undefined,
  phase: PlanToolStreamEvent["phase"],
  onPlanTool?: (event: PlanToolStreamEvent) => void,
): void {
  if (!name || !isTaskCardRefreshTool(name)) return;

  if (onPlanTool && name === TASK_CARD_STREAM_TOOL) {
    onPlanTool({ name, phase });
  }

  handlePlanToolStreamRefresh({ name, phase });
}

function stringifyToolValue(value: unknown): string {
  if (typeof value === 'string') return value;
  if (value == null) return '';
  if (typeof value === 'object') {
    try {
      return JSON.stringify(value, null, 2);
    } catch {
      return String(value);
    }
  }
  return String(value);
}

function inspectToolData(
  data: any,
  metadata: { node_id?: string; graph_id?: string } | undefined,
  onToolCall: ((data: { call_id: string; name: string; arguments: string }, metadata?: { node_id?: string; graph_id?: string }) => void) | undefined,
  onToolResult: ((data: { call_id: string; name: string; output: string }, metadata?: { node_id?: string; graph_id?: string }) => void) | undefined,
  onPlanTool: ((event: PlanToolStreamEvent) => void) | undefined,
  toolNameByCallId: Map<string, string>,
): void {
  if (!data || typeof data !== 'object') return;
  const callId = String(data.call_id || data.id || '');
  const name =
    (typeof data.name === 'string' && data.name) ||
    (callId ? toolNameByCallId.get(callId) : '') ||
    '';

  if (data.output !== undefined) {
    if (!name) return;
    const resultData = {
      call_id: callId,
      name,
      output: stringifyToolValue(data.output),
    };
    if (isTaskCardRefreshTool(resultData.name)) {
      console.info("[datapaw:sse] tool result", {
        name: resultData.name,
        callId: resultData.call_id,
        hasMetadata: Boolean(metadata),
      });
    }
    notifyPlanToolInStream(resultData.name, "result", onPlanTool);
    onToolResult?.(resultData, metadata);
    return;
  }

  if (data.arguments !== undefined || data.input !== undefined) {
    if (!name) return;
    if (callId) toolNameByCallId.set(callId, name);
    const toolData = {
      call_id: callId,
      name,
      arguments: stringifyToolValue(data.arguments ?? data.input),
    };
    if (isTaskCardRefreshTool(toolData.name)) {
      console.info("[datapaw:sse] tool call", {
        name: toolData.name,
        callId: toolData.call_id,
        hasMetadata: Boolean(metadata),
      });
    }
    notifyPlanToolInStream(toolData.name, "call", onPlanTool);
    onToolCall?.(toolData, metadata);
  }
}

function inspectToolFrame(
  parsed: any,
  onToolCall: ((data: { call_id: string; name: string; arguments: string }, metadata?: { node_id?: string; graph_id?: string }) => void) | undefined,
  onToolResult: ((data: { call_id: string; name: string; output: string }, metadata?: { node_id?: string; graph_id?: string }) => void) | undefined,
  onPlanTool: ((event: PlanToolStreamEvent) => void) | undefined,
  toolNameByCallId: Map<string, string>,
): void {
  if (!parsed || typeof parsed !== 'object') return;

  if (parsed.object === 'content' && parsed.type === 'data') {
    inspectToolData(parsed.data, parsed.metadata, onToolCall, onToolResult, onPlanTool, toolNameByCallId);
    return;
  }

  const type = typeof parsed.type === 'string' ? parsed.type.toLowerCase() : '';
  const isMessageLike = parsed.object === 'message' || Array.isArray(parsed.content);
  if (
    isMessageLike &&
    (type === 'plugin_call' || type === 'plugin_call_output') &&
    Array.isArray(parsed.content)
  ) {
    for (const contentItem of parsed.content) {
      if (contentItem?.type === 'data') {
        inspectToolData(contentItem.data, parsed.metadata, onToolCall, onToolResult, onPlanTool, toolNameByCallId);
      }
    }
  }

  if (parsed.object === 'response' && Array.isArray(parsed.output)) {
    for (const outputMessage of parsed.output) {
      inspectToolFrame(outputMessage, onToolCall, onToolResult, onPlanTool, toolNameByCallId);
    }
  }
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
  const toolNameByCallId = new Map<string, string>();

  /**
   * Process a single complete line from the SSE stream.
   * Returns the line (with its original line ending) to pass downstream,
   * or an empty string if the line should be filtered out.
   */
  function processLine(line: string): string {
    if (line.endsWith('\r')) {
      line = line.slice(0, -1);
    }

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

          inspectToolFrame(parsed, onToolCall, onToolResult, onPlanTool, toolNameByCallId);

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
