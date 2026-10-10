/*
 * SSE 解析层 —— 逐函数移植 PR #7378 apps/qwenpaw-mobile/src/api/sse.ts（纯逻辑，与传输无关）。
 * 对拍基准：PR sse.test.ts 五组向量（跨块拼接 / 多行 data / 增量文本 / 分类 / 错误）。
 * 传输层（TCP socket 手拼 HTTP GET 收流）在下一块接入，解析层先行锁定协议语义。
 */

export interface SseEvent {
  event: string;   // '' = 无 event: 行
  data: string;
}

export interface StreamDelta {
  messageId: string;
  kind: string;    // message / reasoning / tool
  text: string;
}

export class SseParser {
  private buffer: string = '';

  push(chunk: string): SseEvent[] {
    this.buffer += chunk.replace(/\r\n/g, '\n');
    const blocks: string[] = this.buffer.split('\n\n');
    this.buffer = blocks.pop() ?? '';
    const out: SseEvent[] = [];
    for (const b of blocks) {
      const evs: SseEvent[] = parseBlock(b);
      for (const e of evs) {
        out.push(e);
      }
    }
    return out;
  }

  finish(): SseEvent[] {
    const block: string = this.buffer;
    this.buffer = '';
    return block.trim().length > 0 ? parseBlock(block) : [];
  }
}

function parseBlock(block: string): SseEvent[] {
  let event: string = '';
  const data: string[] = [];
  const lines: string[] = block.split('\n');
  for (const line of lines) {
    if (line.startsWith(':')) {
      continue;
    }
    const separator: number = line.indexOf(':');
    const field: string = separator < 0 ? line : line.slice(0, separator);
    const value: string = separator < 0 ? '' : line.slice(separator + 1).replace(/^ /, '');
    if (field === 'event') {
      event = value;
    }
    if (field === 'data') {
      data.push(value);
    }
  }
  if (data.length === 0) {
    return [];
  }
  return [{ event: event, data: data.join('\n') }];
}

export function eventText(event: SseEvent): string {
  if (event.data === '[DONE]') {
    return '';
  }
  const payload: Record<string, Object> | null = jsonPayload(event.data);
  if (payload === null) {
    return event.data;
  }
  if (payload['object'] === 'content' && payload['delta'] === true) {
    const t: Object = payload['text'];
    return typeof t === 'string' ? t as string : '';
  }
  if (payload['object'] === 'message' && payload['status'] === 'in_progress') {
    return messageDeltaText(payload['content']);
  }
  return '';
}

export function streamError(event: SseEvent): string | null {
  const payload: Record<string, Object> | null = jsonPayload(event.data);
  if (payload === null) {
    return null;
  }
  const error: Object = payload['error'];
  if (typeof error === 'string') {
    const s: string = (error as string).trim();
    return s.length > 0 ? s : '模型调用失败';
  }
  if (payload['object'] !== 'response' || payload['status'] !== 'failed') {
    return null;
  }
  if (typeof error === 'object' && error !== null && !Array.isArray(error)) {
    const detail: Record<string, Object> = error as Record<string, Object>;
    let message: Object = detail['message'];
    if (message === undefined) {
      message = detail['detail'];
    }
    if (message === undefined) {
      message = detail['code'];
    }
    if (typeof message === 'string' && (message as string).trim().length > 0) {
      return (message as string).trim();
    }
  }
  return '模型调用失败';
}

export class StreamEventClassifier {
  private readonly messageTypes: Map<string, string> = new Map<string, string>();

  consume(event: SseEvent): StreamDelta | null {
    const payload: Record<string, Object> | null = jsonPayload(event.data);
    if (payload === null) {
      return null;
    }
    if (payload['object'] === 'message') {
      const id: Object = payload['id'];
      const messageId: string = typeof id === 'string' ? id as string : '';
      const kind: string = messageKind(payload['type']);
      if (messageId.length > 0) {
        this.messageTypes.set(messageId, kind);
      }
      const text: string = messageDeltaText(payload['content']);
      if (text.length === 0) {
        return null;
      }
      return { messageId: messageId.length > 0 ? messageId : 'stream', kind: kind, text: text };
    }
    if (payload['object'] !== 'content' || payload['delta'] !== true) {
      return null;
    }
    const msgId: Object = payload['msg_id'];
    const messageId: string = typeof msgId === 'string' ? msgId as string : 'stream';
    const text: Object = payload['text'];
    if (typeof text !== 'string' || (text as string).length === 0) {
      return null;
    }
    const kind: string = this.messageTypes.get(messageId) ?? 'message';
    return { messageId: messageId, kind: kind, text: text as string };
  }
}

function jsonPayload(value: string): Record<string, Object> | null {
  if (value === '[DONE]') {
    return null;
  }
  try {
    const parsed: Object = JSON.parse(value);
    if (parsed !== null && typeof parsed === 'object' && !Array.isArray(parsed)) {
      return parsed as Record<string, Object>;
    }
    return null;
  } catch (e) {
    return null;
  }
}

// 工具调用类型精确集合 —— 逐条对齐 PR #7378 apps/qwenpaw-mobile/src/api/messages.ts TOOL_TYPES。
// 真实后端 wire 用 type=plugin_call / plugin_call_output（不含子串 "tool"），
// 且 role 恒为 assistant/user（无 tool role）——判定须按 type 精确集合，而非子串。
const TOOL_TYPES: string[] = [
  'plugin_call', 'plugin_call_output', 'plugin_result',
  'function_call', 'function_call_output', 'mcp_tool_call', 'mcp_tool_call_output',
];

export function isToolType(type: string): boolean {
  return TOOL_TYPES.indexOf(type) >= 0;
}

// 消息级 kind 判定（对齐 PR #7378 toDisplayMessage）：
//   type === 'reasoning'                     → 'reasoning'
//   TOOL_TYPES.has(type) || role === 'tool'  → 'tool'
//   其余                                      → 'message'
export function messageKindOf(type: string, role: string): string {
  if (type === 'reasoning') {
    return 'reasoning';
  }
  if (isToolType(type) || role === 'tool') {
    return 'tool';
  }
  return 'message';
}

function messageKind(value: Object): string {
  const t: string = typeof value === 'string' ? value as string : '';
  return messageKindOf(t, '');
}

function messageDeltaText(content: Object): string {
  if (!Array.isArray(content)) {
    return '';
  }
  const items: Object[] = content as Object[];
  const parts: string[] = [];
  for (const item of items) {
    if (item === null || item === undefined || typeof item !== 'object') {
      parts.push('');
      continue;
    }
    const part: Record<string, Object> = item as Record<string, Object>;
    if (part['delta'] === true && typeof part['text'] === 'string') {
      parts.push(part['text'] as string);
    } else {
      parts.push('');
    }
  }
  return parts.join('');
}
