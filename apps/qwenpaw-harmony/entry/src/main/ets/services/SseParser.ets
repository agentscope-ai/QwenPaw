/*
 * SSE 解析层 —— 逐函数移植 PR #7378 apps/qwenpaw-mobile/src/api/sse.ts（纯逻辑，与传输无关）。
 * 对拍基准：PR sse.test.ts 五组向量（跨块拼接 / 多行 data / 增量文本 / 分类 / 错误）。
 * 传输层（TCP socket 手拼 HTTP GET 收流）在下一块接入，解析层先行锁定协议语义。
 */

import { t } from './I18n';

export interface SseEvent {
  event: string;   // '' = 无 event: 行
  data: string;
}

export interface StreamDelta {
  messageId: string;
  kind: string;    // message / reasoning / tool / user
  text: string;
  // 工具事件的载荷不在 text 里：wire 实测 content 的 data 项携带
  // plugin_call = {call_id, name, arguments}、plugin_call_output = {call_id, name, output, state}
  toolName?: string;
  toolState?: string;
  toolInput?: string;
  toolOutput?: string;
  // user_message 回显帧的 content 序列化（JSON）：UI 侧据此构建本轮用户消息的分片
  userContent?: string;
}

// 取 content 里第一条带 data 对象的项（工具事件的载荷所在地）
function toolDataOf(content: Object): Record<string, Object> | null {
  if (!Array.isArray(content)) {
    return null;
  }
  for (const item of content as Object[]) {
    const raw: Object = (item as Record<string, Object>)['data'];
    if (typeof raw === 'object' && raw !== null && !Array.isArray(raw)) {
      return raw as Record<string, Object>;
    }
  }
  return null;
}

// 工具段增量：名称 / 参数 / 输出 / 状态至少带一项
function toolDeltaOf(messageId: string, data: Record<string, Object>, kind: string): StreamDelta | null {
  const name: Object = data['name'];
  const args: Object = data['arguments'];
  const out: Object = data['output'];
  const st: Object = data['state'];
  const hasName: boolean = typeof name === 'string' && (name as string).length > 0;
  const hasArgs: boolean = typeof args === 'string' && (args as string).length > 0;
  const hasOut: boolean = typeof out === 'string' && (out as string).length > 0;
  const hasState: boolean = typeof st === 'string' && (st as string).length > 0;
  if (!hasName && !hasArgs && !hasOut && !hasState) {
    return null;
  }
  return {
    messageId: messageId.length > 0 ? messageId : 'stream', kind: kind, text: '',
    toolName: hasName ? name as string : undefined,
    toolInput: hasArgs ? args as string : undefined,
    toolOutput: hasOut ? out as string : undefined,
    toolState: hasState ? st as string : undefined
  };
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

export function streamError(event: SseEvent): string | null {
  const payload: Record<string, Object> | null = jsonPayload(event.data);
  if (payload === null) {
    return null;
  }
  const error: Object = payload['error'];
  if (typeof error === 'string') {
    const s: string = (error as string).trim();
    return s.length > 0 ? s : t($r('app.string.sse_model_call_failed'));
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
  return t($r('app.string.sse_model_call_failed'));
}

export class StreamEventClassifier {
  private readonly messageTypes: Map<string, string> = new Map<string, string>();

  consume(event: SseEvent): StreamDelta | null {
    const payload: Record<string, Object> | null = jsonPayload(event.data);
    if (payload === null) {
      return null;
    }
    // user_message 回显帧：服务端在 run 开头把「用户自己那条消息」回显回来（无 object 字段，
    // 与 turn_usage / replay_end 帧同属 QwenPaw 专属帧，console SDK 与 RN 客户端不识别即忽略）。
    // content 项不带 delta 标记，形状与落盘消息的 content 一致，故不走 messageDeltaText。
    if (payload['type'] === 'user_message') {
      const eid: Object = payload['id'];
      const eidStr: string = typeof eid === 'string' ? eid as string : 'user_echo';
      let econtent: Object = payload['content'];
      if (econtent === undefined || econtent === null) {
        econtent = [];
      }
      return {
        messageId: eidStr, kind: 'user', text: userEchoText(econtent),
        userContent: JSON.stringify(econtent)
      };
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
        // 工具调用 / 工具输出的内容全是 data 项（无文本）——旧实现此处直接丢弃，
        // 结果在途回合里完全没有工具段（工具调用与文件读写编辑都不显示）
        if (kind === 'tool') {
          const data: Record<string, Object> | null = toolDataOf(payload['content']);
          if (data !== null) {
            return toolDeltaOf(messageId, data, kind);
          }
        }
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
      // 无文本载荷的 data 分片 = 工具事件（name / arguments / output / state 之一）。
      // 这里不能按"该 msg_id 的类型还没记录到"就丢弃（工具数据先于类型事件到达时会整段丢掉），
      // 更不能落成 message 段——空文本的 message 段会渲染成一张空白气泡卡片。
      if (payload['type'] === 'data') {
        const data: Record<string, Object> | null = toolDataOf([payload]);
        if (data !== null) {
          const k0: string = this.messageTypes.get(messageId) ?? 'tool';
          return toolDeltaOf(messageId, data, k0 === 'message' ? 'tool' : k0);
        }
      }
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

// user_message 回显帧的文本部分：content 项无 delta 标记，只取 text 项。
// 多段文本以单空格相连——与 ChatDetailService.textOfParts 同一口径，两端去重比较才成立
function userEchoText(content: Object): string {
  if (!Array.isArray(content)) {
    return '';
  }
  let out: string = '';
  for (const item of content as Object[]) {
    if (item === null || item === undefined || typeof item !== 'object') {
      continue;
    }
    const rec: Record<string, Object> = item as Record<string, Object>;
    if (rec['type'] === 'text' && typeof rec['text'] === 'string') {
      out = out.length > 0 ? `${out} ${rec['text'] as string}` : rec['text'] as string;
    }
  }
  return out;
}
