/*
 * 会话详情服务 —— 历史 + 流式对话（对齐 PR #7378 apps/qwenpaw-mobile/src/api/messages.ts + client.ts）。
 *
 * 历史解析按 7378 的「wire → display message → turn」三级模型逐函数移植：
 *   GET  {base}/api/chats/{id}                → { messages: WireMessage[], status }
 *   POST {base}/api/console/chat (stream)     → SSE 流（SseParser 增量解析）
 *   POST {base}/api/console/chat/stop         → 停止当前轮次
 *
 * 消息分级 kind 判定与 7378 一致：type==='reasoning' → reasoning；
 * type 属工具类型精确集合（plugin_call / function_call / …）或 role==='tool' → tool；其余 → message。
 * 真实后端 wire 用 type=plugin_call / plugin_call_output（不含子串 "tool"）且 role 恒为 assistant/user，
 * 故判定必须走精确集合而非子串匹配（此前 indexOf('tool') 漏判导致工具消息挤进普通气泡）。
 */

import { http } from '@kit.NetworkKit';
import { util } from '@kit.ArkTS';
import { doRequest, jsonOf, ConnectError } from './ConnectionService';
import { SseParser, SseEvent, StreamDelta, StreamEventClassifier, streamError, messageKindOf, isToolType } from './SseParser';

// 会话详情关闭事件：会话列表据此重载
export const CHAT_CLOSED_EVENT: string = 'qp_chat_closed';

// ============ 显示模型（逐字段对齐 PR #7378 api/types.ts）============
export interface DisplayPart {
  type: string;        // text / image / video / audio / file
  text?: string;
  url?: string;
  name?: string;
}

export interface DisplayMessage {
  id: string;
  role: string;        // user / assistant / tool
  kind: string;        // message / reasoning / tool
  parts: DisplayPart[];
  toolName?: string;
  toolState?: string;
  toolCallId?: string;
  toolInput?: string;
  toolOutput?: string;
  pending?: boolean;
  error?: string;
}

export interface DisplayTurn {
  id: string;
  user: DisplayMessage | null;
  process: DisplayMessage[];
  answer: DisplayMessage | null;
  resultMedia: DisplayPart[];
  pending: boolean;
}

export interface ChatSnapshot {
  turns: DisplayTurn[];
  running: boolean;
}

// ============ 常量（对齐 PR #7378 messages.ts）============
const MEDIA_TYPES: string[] = ['image', 'video', 'audio', 'file'];
const PROCESS_TEXT_LIMIT: number = 8000;

// ============ JSON 取值辅助（ArkTS：JSON.parse 返回 Object，需显式收窄）============
function asRecord(v: Object): Record<string, Object> | null {
  if (v !== null && typeof v === 'object' && !Array.isArray(v)) {
    return v as Record<string, Object>;
  }
  return null;
}

function asArray(v: Object): Object[] | null {
  if (Array.isArray(v)) {
    return v as Object[];
  }
  return null;
}

function strOf(rec: Record<string, Object>, key: string): string {
  const v: Object = rec[key];
  return typeof v === 'string' ? v as string : '';
}

function strUndef(v: Object | undefined): string | undefined {
  return typeof v === 'string' && (v as string).length > 0 ? v as string : undefined;
}

// ============ wire → display message（对齐 PR #7378 toDisplayMessage）============
export function toDisplayMessages(records: Object[]): DisplayMessage[] {
  const out: DisplayMessage[] = [];
  for (let i = 0; i < records.length; i++) {
    const m: DisplayMessage | null = toDisplayMessage(records[i] as Record<string, Object>, i);
    if (m !== null) {
      out.push(m);
    }
  }
  return out;
}

function toDisplayMessage(message: Record<string, Object>, index: number): DisplayMessage | null {
  const type: string = strOf(message, 'type').length > 0 ? strOf(message, 'type') : 'message';
  const roleRaw: string = strOf(message, 'role');
  const role: string = roleRaw === 'user'
    ? 'user'
    : (isToolType(type) || roleRaw === 'tool') ? 'tool' : 'assistant';
  const kind: string = messageKindOf(type, roleRaw);
  const tool: ToolInfo | null = kind === 'tool' ? extractTool(message) : null;
  const parts: DisplayPart[] = kind === 'tool'
    ? (tool !== null ? tool.parts : [])
    : contentParts(message['content']);
  if (parts.length === 0 && kind !== 'tool') {
    return null;
  }
  const id: string = strOf(message, 'id').length > 0 ? strOf(message, 'id') : `${role}-${index}`;
  const out: DisplayMessage = { id: id, role: role, kind: kind, parts: parts };
  if (tool !== null) {
    out.toolName = tool.name;
    out.toolState = tool.state;
    out.toolCallId = tool.callId;
    out.toolInput = tool.input;
    out.toolOutput = tool.output;
  }
  return out;
}

// ============ content → display parts（对齐 PR #7378 contentParts / contentItemParts）============
function contentParts(content: Object): DisplayPart[] {
  if (typeof content === 'string') {
    return textParts(content as string);
  }
  const arr: Object[] | null = asArray(content);
  if (arr !== null) {
    const out: DisplayPart[] = [];
    for (const item of arr) {
      const rec: Record<string, Object> = item as Record<string, Object>;
      const sub: DisplayPart[] = contentItemParts(rec);
      for (const p of sub) {
        out.push(p);
      }
    }
    return out;
  }
  const rec: Record<string, Object> | null = asRecord(content);
  if (rec !== null) {
    return contentItemParts(rec);
  }
  return [];
}

function contentItemParts(item: Record<string, Object>): DisplayPart[] {
  const type: string = strOf(item, 'type');
  if (type === 'text' && typeof item['text'] === 'string') {
    return textParts(item['text'] as string);
  }
  if (type === 'image') {
    return mediaPart('image', firstObj(item, ['image_url', null]), item);
  }
  if (type === 'video') {
    return mediaPart('video', firstObj(item, ['video_url', null]), item);
  }
  if (type === 'audio') {
    return mediaPart('audio', firstObj(item, ['data', null]), item);
  }
  if (type === 'file') {
    return mediaPart('file', firstObj(item, ['file_url', null]), item);
  }
  if (MEDIA_TYPES.indexOf(type) >= 0) {
    return [];
  }
  if (typeof item['text'] === 'string') {
    return textParts(item['text'] as string);
  }
  return [];
}

// item[键] 若为空则回落 sourceUrl(item)（对齐 7378 contentItemParts 的 ?? sourceUrl(item)）
function firstObj(item: Record<string, Object>, keys: (string | null)[]): Object {
  for (const k of keys) {
    if (k !== null && item[k] !== undefined) {
      return item[k];
    }
  }
  return sourceUrl(item);
}

function textParts(value: string): DisplayPart[] {
  if (value.trim().length === 0) {
    return [];
  }
  const p: DisplayPart = { type: 'text', text: value };
  return [p];
}

function mediaPart(type: string, rawUrl: Object, item: Record<string, Object>): DisplayPart[] {
  if (typeof rawUrl !== 'string' || (rawUrl as string).trim().length === 0) {
    return [];
  }
  const url: string = rawUrl as string;
  let nameV: Object = item['filename'];
  if (typeof nameV !== 'string') {
    nameV = item['file_name'];
  }
  if (typeof nameV !== 'string') {
    nameV = item['name'];
  }
  const name: string = (typeof nameV === 'string' && nameV) ? nameV as string : fileName(url);
  const part: DisplayPart = { type: type, url: url, name: name.length > 0 ? name : '文件' };
  return [part];
}

function sourceUrl(item: Record<string, Object>): Object {
  const src: Record<string, Object> | null = asRecord(item['source']);
  if (src === null) {
    return '';
  }
  if (src['type'] === 'base64' && typeof src['data'] === 'string') {
    const mt: Object = src['media_type'];
    const mediaType: string = typeof mt === 'string' ? mt as string : 'application/octet-stream';
    return `data:${mediaType};base64,${src['data'] as string}`;
  }
  return src['url'];
}

// ============ 工具调用提取（对齐 PR #7378 extractTool）============
interface ToolInfo {
  name?: string;
  state?: string;
  callId?: string;
  input?: string;
  output?: string;
  parts: DisplayPart[];
}

function extractTool(message: Record<string, Object>): ToolInfo {
  const contentArr: Object[] | null = asArray(message['content']);
  if (contentArr === null) {
    return { parts: [] };
  }
  const dataItems: Record<string, Object>[] = [];
  for (const c of contentArr) {
    const d: Record<string, Object> | null = asRecord((c as Record<string, Object>)['data']);
    if (d !== null) {
      dataItems.push(d);
    }
  }
  let callData: Record<string, Object> | null = null;
  for (const d of dataItems) {
    if (d['arguments'] !== undefined) {
      callData = d;
      break;
    }
  }
  if (callData === null && dataItems.length > 0) {
    callData = dataItems[0];
  }
  let resultData: Record<string, Object> | null = null;
  for (const d of dataItems) {
    if (d['output'] !== undefined) {
      resultData = d;
      break;
    }
  }
  const data: Record<string, Object> = callData !== null ? callData
    : (resultData !== null ? resultData : {});
  if (callData === null && resultData === null) {
    return { parts: [] };
  }
  // name = data.name ?? resultData.name
  let name: string | undefined = strUndef(data['name']);
  if (name === undefined && resultData !== null) {
    name = strUndef(resultData['name']);
  }
  // state = resultData.state ?? data.state
  let state: string | undefined;
  if (resultData !== null) {
    state = strUndef(resultData['state']);
  }
  if (state === undefined) {
    state = strUndef(data['state']);
  }
  // callId = data.call_id ?? resultData.call_id ?? data.id
  let callId: string | undefined = strUndef(data['call_id']);
  if (callId === undefined && resultData !== null) {
    callId = strUndef(resultData['call_id']);
  }
  if (callId === undefined) {
    callId = strUndef(data['id']);
  }
  let outputVal: Object | undefined;
  if (resultData !== null && resultData['output'] !== undefined) {
    outputVal = resultData['output'];
  } else {
    outputVal = data['output'];
  }
  const argsVal: Object | undefined = callData !== null ? callData['arguments'] : undefined;
  const input: string | undefined = callData !== null ? formatToolDetail(callData['arguments']) : undefined;
  const output: string | undefined = formatToolDetail(outputVal);
  const parts: DisplayPart[] = mediaPartsFromArguments(argsVal).concat(mediaPartsFromUnknown(outputVal));
  return { name: name, state: state, callId: callId, input: input, output: output, parts: parts };
}

function mediaPartsFromArguments(value: Object | undefined): DisplayPart[] {
  if (value === undefined) {
    return [];
  }
  const parsed: Object = parseJson(value);
  const rec: Record<string, Object> | null = asRecord(parsed);
  if (rec === null) {
    return [];
  }
  const keys: string[] = ['file_path', 'image_path', 'video_path', 'audio_path', 'path'];
  for (const k of keys) {
    const raw: Object = rec[k];
    if (typeof raw === 'string' && isPreviewableUrl(raw as string)) {
      return [pathMediaPart(raw as string)];
    }
  }
  return [];
}

function mediaPartsFromUnknown(value: Object | undefined): DisplayPart[] {
  if (value === undefined) {
    return [];
  }
  const parsed: Object = parseJson(value);
  if (typeof parsed === 'string') {
    return mediaPartsFromText(parsed as string);
  }
  const arr: Object[] | null = asArray(parsed);
  if (arr !== null) {
    const out: DisplayPart[] = [];
    for (const item of arr) {
      const sub: DisplayPart[] = mediaPartsFromUnknown(item);
      for (const p of sub) {
        out.push(p);
      }
    }
    return out;
  }
  const rec: Record<string, Object> | null = asRecord(parsed);
  if (rec === null) {
    return [];
  }
  const direct: DisplayPart[] = contentItemParts(rec).filter((p: DisplayPart): boolean => p.type !== 'text');
  if (direct.length > 0) {
    return direct;
  }
  if (rec['type'] === 'text' && typeof rec['text'] === 'string') {
    return mediaPartsFromText(rec['text'] as string);
  }
  const keys: string[] = ['output', 'content', 'result', 'data'];
  for (const k of keys) {
    if (rec[k] !== undefined) {
      const nested: DisplayPart[] = mediaPartsFromUnknown(rec[k]);
      if (nested.length > 0) {
        return nested;
      }
    }
  }
  return [];
}

function mediaPartsFromText(value: string): DisplayPart[] {
  const m: RegExpMatchArray | null = value.match(
    /(?:file:\/\/)?(?:\/[\w.\-]+)+(?:\/[\w.\-]+)*\.(?:png|jpe?g|gif|bmp|webp|svg|mp4|mov|mkv|webm|mp3|wav|flac|aac|ogg|pdf|docx?|xlsx?|pptx?|txt|zip)/i
  );
  return m !== null ? [pathMediaPart(m[0])] : [];
}

function pathMediaPart(url: string): DisplayPart {
  const name: string = fileName(url);
  const base: string = name.length > 0 ? name : '文件';
  const dot: number = base.lastIndexOf('.');
  const ext: string = dot >= 0 ? base.substring(dot + 1).toLowerCase() : '';
  let type: string = 'file';
  if (['png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp', 'svg'].indexOf(ext) >= 0) {
    type = 'image';
  } else if (['mp4', 'mov', 'mkv', 'webm'].indexOf(ext) >= 0) {
    type = 'video';
  } else if (['mp3', 'wav', 'flac', 'aac', 'ogg'].indexOf(ext) >= 0) {
    type = 'audio';
  }
  const part: DisplayPart = { type: type, url: url, name: base };
  return part;
}

function isPreviewableUrl(value: string): boolean {
  return value.startsWith('/') || value.startsWith('file://')
    || value.startsWith('http://') || value.startsWith('https://');
}

// ============ 工具详情格式化 + 脱敏（对齐 PR #7378 formatToolDetail / sanitizeToolValue）============
function formatToolDetail(value: Object | undefined): string | undefined {
  if (value === undefined || value === null
    || (typeof value === 'string' && (value as string) === '')) {
    return undefined;
  }
  const parsed: Object = parseJson(value);
  const sanitized: Object = sanitizeToolValue(parsed);
  let detail: string;
  if (typeof sanitized === 'string') {
    detail = sanitized as string;
  } else {
    try {
      detail = JSON.stringify(sanitized, undefined, 2);
    } catch (e) {
      detail = '';
    }
  }
  if (detail.trim().length === 0) {
    return undefined;
  }
  return detail.length > PROCESS_TEXT_LIMIT
    ? `${detail.substring(0, PROCESS_TEXT_LIMIT)}…`
    : detail;
}

// 凭据类键（token/password/secret/authorization/cookie）的值替换为 ••••••（对齐 7378，防止敏感值入 UI）
function sanitizeToolValue(value: Object): Object {
  const arr: Object[] | null = asArray(value);
  if (arr !== null) {
    const out: Object[] = [];
    for (const item of arr) {
      out.push(sanitizeToolValue(item));
    }
    return out;
  }
  if (value === null || typeof value !== 'object') {
    return value;
  }
  const rec: Record<string, Object> = value as Record<string, Object>;
  const outRec: Record<string, Object> = {};
  const keys: string[] = Object.keys(rec);
  for (const k of keys) {
    outRec[k] = /token|password|secret|authorization|cookie/i.test(k)
      ? '••••••'
      : sanitizeToolValue(rec[k]);
  }
  return outRec;
}

function parseJson(value: Object): Object {
  if (typeof value !== 'string') {
    return value;
  }
  try {
    return JSON.parse(value as string);
  } catch (e) {
    return value;
  }
}

function fileName(value: string): string {
  const norm: string = value.replace(/\\/g, '/');
  const segs: string[] = norm.split('/');
  let base: string = segs.length > 0 ? segs[segs.length - 1] : '';
  const q: number = base.indexOf('?');
  if (q >= 0) {
    base = base.substring(0, q);
  }
  return base;
}

// ============ display messages → turns（对齐 PR #7378 toDisplayTurns / buildTurn）============
export function toDisplayTurns(messages: DisplayMessage[]): DisplayTurn[] {
  const turns: DisplayTurn[] = [];
  let current: DisplayMessage[] = [];
  const flush = (): void => {
    if (current.length === 0) {
      return;
    }
    turns.push(buildTurn(current));
    current = [];
  };
  for (const m of messages) {
    if (m.role === 'user' && current.length > 0) {
      flush();
    }
    current.push(m);
  }
  flush();
  return turns;
}

function buildTurn(messages: DisplayMessage[]): DisplayTurn {
  let user: DisplayMessage | null = null;
  for (const m of messages) {
    if (m.role === 'user') {
      user = m;
      break;
    }
  }
  const responses: DisplayMessage[] = [];
  for (const m of messages) {
    if (m !== user) {
      responses.push(m);
    }
  }
  let answerIndex: number = -1;
  for (let i = responses.length - 1; i >= 0; i--) {
    const m: DisplayMessage = responses[i];
    if (m.role === 'assistant' && m.kind === 'message'
      && (m.parts.length > 0 || m.error !== undefined)) {
      answerIndex = i;
      break;
    }
  }
  const answer: DisplayMessage | null = answerIndex >= 0 ? responses[answerIndex] : null;
  const process: DisplayMessage[] = [];
  for (let i = 0; i < responses.length; i++) {
    if (i !== answerIndex) {
      process.push(responses[i]);
    }
  }
  const answerKeys: string[] = [];
  if (answer !== null) {
    for (const p of answer.parts) {
      if (p.type !== 'text') {
        answerKeys.push(mediaKey(p));
      }
    }
  }
  const allMedia: DisplayPart[] = [];
  for (const m of process) {
    for (const p of m.parts) {
      if (p.type !== 'text') {
        allMedia.push(p);
      }
    }
  }
  const resultMedia: DisplayPart[] = uniqueMedia(allMedia).filter(
    (p: DisplayPart): boolean => answerKeys.indexOf(mediaKey(p)) < 0
  );
  let pending: boolean = false;
  for (const m of messages) {
    if (m.pending === true) {
      pending = true;
    }
  }
  return {
    id: user !== null ? user.id : messages[0].id,
    user: user,
    process: process,
    answer: answer,
    resultMedia: resultMedia,
    pending: pending
  };
}

function mediaKey(part: DisplayPart): string {
  return part.type === 'text'
    ? `text:${part.text !== undefined ? part.text : ''}`
    : `${part.type}:${part.url !== undefined ? part.url : ''}`;
}

function uniqueMedia(parts: DisplayPart[]): DisplayPart[] {
  const seen: string[] = [];
  const out: DisplayPart[] = [];
  for (const p of parts) {
    const k: string = mediaKey(p);
    if (seen.indexOf(k) >= 0) {
      continue;
    }
    seen.push(k);
    out.push(p);
  }
  return out;
}

// ============ 历史拉取（返回 turn 结构）============
export async function fetchChatMessages(baseUrl: string, token: string, agentId: string,
  chatId: string): Promise<ChatSnapshot> {
  const resp: http.HttpResponse = await doRequest(
    `${baseUrl}/api/chats/${encodeURIComponent(chatId)}`, http.RequestMethod.GET, null,
    token.length > 0 ? token : null, agentId);
  if (resp.responseCode === 401 || resp.responseCode === 403) {
    throw new ConnectError(`票据已失效（HTTP ${resp.responseCode}），请重新连接。`);
  }
  if (resp.responseCode !== 200) {
    throw new ConnectError(`读取会话失败（HTTP ${resp.responseCode}）。`);
  }
  const data: Record<string, Object> = jsonOf(resp);
  const arr: Object = data['messages'];
  let display: DisplayMessage[] = [];
  if (Array.isArray(arr)) {
    display = toDisplayMessages(arr as Object[]);
  }
  return { turns: toDisplayTurns(display), running: strOf(data, 'status') === 'running' };
}

// ============ 流式对话（对齐 PR #7378 client.ts streamChat；传输 = http.requestInStream）============
export interface ChatStreamHandle {
  stop(): void;
}

class ChatStream implements ChatStreamHandle {
  private readonly onStop: () => void;

  constructor(onStop: () => void) {
    this.onStop = onStop;
  }

  stop(): void {
    this.onStop();
  }
}

export function streamChat(baseUrl: string, token: string, agentId: string, sessionId: string,
  parts: ChatInputPart[], onDelta: (delta: StreamDelta) => void,
  onDone: (error: string | null) => void): ChatStreamHandle {
  const req: http.HttpRequest = http.createHttp();
  const parser: SseParser = new SseParser();
  const classifier: StreamEventClassifier = new StreamEventClassifier();
  const decoder: util.TextDecoder = util.TextDecoder.create('utf-8');
  let settled: boolean = false;

  const finish = (error: string | null): void => {
    if (settled) {
      return;
    }
    settled = true;
    onDone(error);
    req.destroy();
  };

  const emit = (event: SseEvent): void => {
    if (settled) {
      return;
    }
    const err: string | null = streamError(event);
    if (err !== null) {
      finish(err);
      return;
    }
    const delta: StreamDelta | null = classifier.consume(event);
    if (delta !== null) {
      onDelta(delta);
    }
  };

  const header: Record<string, Object> = {
    'Content-Type': 'application/json',
    'Accept': 'text/event-stream'
  };
  if (token.length > 0) {
    header['Authorization'] = `Bearer ${token}`;
  }
  if (agentId.length > 0) {
    header['X-Agent-Id'] = agentId;
  }
  const message: ChatInputMessage = { role: 'user', content: parts };
  const payload: ChatStreamRequest = {
    input: [message],
    session_id: sessionId,
    user_id: 'mobile',
    channel: 'console',
    stream: true
  };
  const options: http.HttpRequestOptions = {
    method: http.RequestMethod.POST,
    header: header,
    extraData: JSON.stringify(payload),
    connectTimeout: 10000,
    readTimeout: 0,
    expectDataType: http.HttpDataType.STRING
  };

  req.on('dataReceive', (chunk: ArrayBuffer): void => {
    const decodeOpts: DecodeStreamOptions = { stream: true };
    const chunkText: string = decoder.decodeWithStream(new Uint8Array(chunk), decodeOpts);
    const events: SseEvent[] = parser.push(chunkText);
    for (const ev of events) {
      emit(ev);
    }
  });
  req.on('dataEnd', (): void => {
    const rest: SseEvent[] = parser.finish();
    for (const ev of rest) {
      emit(ev);
    }
    finish(null);
  });
  req.requestInStream(`${baseUrl}/api/console/chat`, options, (err: Error): void => {
    if (err !== undefined && err !== null) {
      finish(err.message);
    }
  });

  return new ChatStream((): void => {
    finish(null);
  });
}

export async function stopChat(baseUrl: string, token: string, agentId: string,
  chatId: string): Promise<void> {
  const resp: http.HttpResponse = await doRequest(
    `${baseUrl}/api/console/chat/stop?chat_id=${encodeURIComponent(chatId)}`,
    http.RequestMethod.POST, null, token.length > 0 ? token : null, agentId);
  if (resp.responseCode < 200 || resp.responseCode >= 300) {
    throw new ConnectError(`停止失败（HTTP ${resp.responseCode}）。`);
  }
}

// ============ 附件上传（对齐 PR #7378 client.ts upload）============
export interface UploadResult {
  url: string;
  fileName: string;
  size: number;
}

export async function uploadAttachment(baseUrl: string, token: string, agentId: string,
  filePath: string, fileName: string, mime: string): Promise<UploadResult> {
  const form: http.MultiFormData = {
    name: 'file',
    contentType: mime,
    remoteFileName: fileName,
    filePath: filePath
  };
  const header: Record<string, Object> = {
    'Content-Type': 'multipart/form-data',
    'Accept': 'application/json'
  };
  if (token.length > 0) {
    header['Authorization'] = `Bearer ${token}`;
  }
  if (agentId.length > 0) {
    header['X-Agent-Id'] = agentId;
  }
  const options: http.HttpRequestOptions = {
    method: http.RequestMethod.POST,
    header: header,
    multiFormDataList: [form],
    connectTimeout: 15000,
    readTimeout: 60000,
    expectDataType: http.HttpDataType.STRING
  };
  const req: http.HttpRequest = http.createHttp();
  try {
    const resp: http.HttpResponse = await req.request(`${baseUrl}/api/console/upload`, options);
    if (resp.responseCode < 200 || resp.responseCode >= 300) {
      throw new ConnectError(`附件上传失败（HTTP ${resp.responseCode}）。`);
    }
    const data: Record<string, Object> = JSON.parse(resp.result as string) as Record<string, Object>;
    const url: string = strOf(data, 'url');
    const name: string = strOf(data, 'file_name');
    const size: Object = data['size'];
    if (url.length === 0) {
      throw new ConnectError('附件上传失败：服务端未返回文件地址。');
    }
    const out: UploadResult = {
      url: url,
      fileName: name.length > 0 ? name : fileName,
      size: typeof size === 'number' ? size as number : 0
    };
    return out;
  } finally {
    req.destroy();
  }
}

// ============ 路由参数 / 输入分片（保留，供页面层使用）============
export interface ChatRouteParam {
  chatId: string;
  chatName: string;
  sessionId: string;
}

export interface ChatInputPart {
  type: string;
  text?: string;
  image_url?: string;
  video_url?: string;
  file_url?: string;
  file_name?: string;
  data?: string;
}

interface ChatInputMessage {
  role: string;
  content: ChatInputPart[];
}

interface ChatStreamRequest {
  input: ChatInputMessage[];
  session_id: string;
  user_id: string;
  channel: string;
  stream: boolean;
}

interface DecodeStreamOptions {
  stream: boolean;
}
