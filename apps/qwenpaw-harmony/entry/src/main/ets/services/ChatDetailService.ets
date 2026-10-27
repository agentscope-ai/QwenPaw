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
import { atlsStream, AtStreamHandle, atlsRequest, buildMultipart, MultipartBody } from './AtlsTransport';
import { doRequest, jsonOf, ConnectError } from './ConnectionService';
import { SseParser, SseEvent, StreamDelta, StreamEventClassifier, streamError, messageKindOf, isToolType } from './SseParser';
import { t, tf } from './I18n';

// 会话详情关闭事件：会话列表据此重载
export const CHAT_CLOSED_EVENT: string = 'qp_chat_closed';

// ============ 显示模型（逐字段对齐 PR #7378 api/types.ts）============
export interface DisplayPart {
  type: string;        // text / image / video / audio / file
  text?: string;
  url?: string;
  name?: string;
  // 文件卡副标题（工具产出文件的变化类型：新建 / 修改 / 发送）；其它媒体分片不用
  note?: string;
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
  // 工具调用的原始参数（JSON 文本）：工具产出文件清单要从 file_path 取值渲染，
  // 不能只靠 toolInput（那是给人看的格式化详情）
  toolArgs?: string;
  pending?: boolean;
  error?: string;
}

export interface DisplayTurn {
  id: string;
  user: DisplayMessage | null;
  // 服务端到达顺序的响应段（reasoning / tool / message 各占一段）：呈现层按 console 的 block 规则
  // （pages/Chat/messageDisplay.ts groupResponseMessages）分组 —— 生成中逐段可见、结束后只留最后
  // 一段文本；此处不预切 process/answer，避免丢掉段与段之间的先后顺序。
  responses: DisplayMessage[];
  pending: boolean;
}

// 响应分组块：message = 可见的气泡段，steps = 收起来的过程组（思考 / 工具）
export interface ResponseBlock {
  kind: string;
  messages: DisplayMessage[];
}

export interface ChatSnapshot {
  turns: DisplayTurn[];
  running: boolean;
  // 该会话归属的 user_id（缺省 'default' = 服务端/console 的默认身份）：
  // 服务端按 (session_id, user_id) 定位 chat，发/重连都必须带它
  userId: string;
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
  // 身份改用「内容派生」（role + 序号 + 文本/媒体指纹）：服务端每次读都重发全新的消息 id
  //（实测同一会话连取两次，263 条 id 全变），若拿它当身份，3s 轮询会把整列表判定为"全变了"
  // → 列表反复重建 + 滚动跳动。
  const id: string = stableMessageId(role, index, parts);
  const out: DisplayMessage = { id: id, role: role, kind: kind, parts: parts };
  if (tool !== null) {
    out.toolName = tool.name;
    out.toolState = tool.state;
    out.toolCallId = tool.callId;
    out.toolInput = tool.input;
    out.toolOutput = tool.output;
    out.toolArgs = tool.toolArgs;
  }
  return out;
}

// 消息稳定标识：同内容必得同 id（服务端 id 不稳定，不能当身份）
function stableMessageId(role: string, index: number, parts: DisplayPart[]): string {
  let text: string = '';
  let media: string = '';
  for (const p of parts) {
    if (p.type === 'text') {
      text += p.text !== undefined ? p.text : '';
    } else {
      media += `${p.type}:${p.url !== undefined ? p.url : ''};`;
    }
  }
  return `${role}-${index}-${text.length}-${media.length}-${text.substring(0, 24)}`;
}

// user_message 回显帧 → 显示分片：帧内 content 与落盘消息的 content 同形，复用同一套解析
export function userEchoParts(contentJson: string): DisplayPart[] {
  if (contentJson.length === 0) {
    return [];
  }
  try {
    return contentParts(JSON.parse(contentJson));
  } catch (e) {
    return [];
  }
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
  const part: DisplayPart = { type: type, url: url, name: name.length > 0 ? name : t($r('app.string.common_file')) };
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
  toolArgs?: string;
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
  // 原始参数（JSON 文本）另存一份：工具产出文件清单要按 file_path 取值（格式化后的 input 取不到）
  const toolArgs: string | undefined = typeof argsVal === 'string' ? argsVal as string : undefined;
  return { name: name, state: state, callId: callId, input: input, output: output, parts: parts, toolArgs: toolArgs };
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
  const base: string = name.length > 0 ? name : t($r('app.string.common_file'));
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
  let pending: boolean = false;
  for (const m of messages) {
    if (m.pending === true) {
      pending = true;
    }
  }
  return {
    id: user !== null ? user.id : messages[0].id,
    user: user,
    responses: responses,
    pending: pending
  };
}

// 末段助理文本（console 'result-only' 与 7378 buildTurn 同一判定：最后一个有内容的 assistant message）
export function answerIndexOf(responses: DisplayMessage[]): number {
  for (let i = responses.length - 1; i >= 0; i--) {
    const m: DisplayMessage = responses[i];
    if (m.role === 'assistant' && m.kind === 'message'
      && (m.parts.length > 0 || m.error !== undefined)) {
      return i;
    }
  }
  return -1;
}

// 工具产出媒体（排除可见答案自身的媒体；对齐 7378 buildTurn 的 resultMedia）
export function resultMediaOf(responses: DisplayMessage[], answerIndex: number): DisplayPart[] {
  const answerKeys: string[] = [];
  if (answerIndex >= 0) {
    for (const p of responses[answerIndex].parts) {
      if (p.type !== 'text') {
        answerKeys.push(mediaKey(p));
      }
    }
  }
  const allMedia: DisplayPart[] = [];
  for (let i = 0; i < responses.length; i++) {
    if (i === answerIndex) {
      continue;
    }
    for (const p of responses[i].parts) {
      if (p.type !== 'text') {
        allMedia.push(p);
      }
    }
  }
  return uniqueMedia(allMedia).filter(
    (p: DisplayPart): boolean => answerKeys.indexOf(mediaKey(p)) < 0
  );
}

// 响应分段（逐条对齐 console pages/Chat/messageDisplay.ts groupResponseMessages）：
//   生成中（created / in_progress）= 'text-only'：message 段逐段可见，其间的思考 / 工具按原位收进 steps 组；
//   已结束 = 'result-only'（默认偏好 result-collapsed）：只留最后一段 message 可见，其余全部收进 steps 组。
export function responseBlocks(responses: DisplayMessage[], pending: boolean): ResponseBlock[] {
  const lastMessageIndex: number = pending ? -1 : answerIndexOf(responses);
  const blocks: ResponseBlock[] = [];
  let run: DisplayMessage[] = [];
  const flush = (): void => {
    if (run.length > 0) {
      blocks.push({ kind: 'steps', messages: run });
      run = [];
    }
  };
  for (let i = 0; i < responses.length; i++) {
    const m: DisplayMessage = responses[i];
    const visible: boolean = pending
      ? (m.role === 'assistant' && m.kind === 'message')
      : (i === lastMessageIndex);
    if (visible) {
      flush();
      blocks.push({ kind: 'message', messages: [m] });
    } else {
      run.push(m);
    }
  }
  flush();
  return blocks;
}

// 分片数组里的文本拼接（气泡 / 过程行取展示文本用；多段 text 之间以空格相连）
export function textOfParts(parts: DisplayPart[]): string {
  let out: string = '';
  for (const p of parts) {
    if (p.type === 'text' && p.text !== undefined) {
      out = out.length > 0 ? `${out} ${p.text}` : p.text;
    }
  }
  return out;
}

// 分片数组里的文本总长（历史摘要 / 过程行内容指纹用）
export function partsTextLen(parts: DisplayPart[]): number {
  let n: number = 0;
  for (const p of parts) {
    if (p.type === 'text' && p.text !== undefined) {
      n += p.text.length;
    }
  }
  return n;
}

// 流式工具事件的媒体分片：与历史快照同一套抽取（参数里的 file_path / image_path… 、
// 输出里的文件路径）。运行中持续抽取使清单数据随流就绪；清单行的渲染在页面按回合终态
// 门控（对齐 console maybeDone：run 到 Completed/Canceled/Failed 才出清单）。
export function toolMediaParts(inputText: string | undefined, outputText: string | undefined): DisplayPart[] {
  const out: DisplayPart[] = [];
  if (inputText !== undefined && inputText.length > 0) {
    for (const p of mediaPartsFromArguments(inputText)) {
      out.push(p);
    }
  }
  if (outputText !== undefined && outputText.length > 0) {
    for (const p of mediaPartsFromUnknown(outputText)) {
      out.push(p);
    }
  }
  return out;
}

// 媒体分片合并（按 url 去重、保持原顺序）：流式合并同一工具段时避免同一文件重复出现
export function mergeMediaParts(base: DisplayPart[], add: DisplayPart[]): DisplayPart[] {
  const out: DisplayPart[] = base.slice();
  const seen: string[] = out.map((p: DisplayPart): string => mediaKey(p));
  for (const p of add) {
    const k: string = mediaKey(p);
    if (seen.indexOf(k) < 0) {
      seen.push(k);
      out.push(p);
    }
  }
  return out;
}

// ============ 回合文件清单（对齐 console features/files-workspace/ResponseArtifactList.tsx）============
// 与"媒体分片"不同：这里的文件来自工具调用的**参数**（file_path），因此：
//   · 支持相对路径（工具写工作区时就是相对路径）与任意扩展名（md/log/code…不白名单）；
//   · 只看 file 读写工具与 send_file_to_user（别的工具里出现的路径不算产出）；
//   · 失败态（denied / error / cancelled…）不算产出；
//   · 跑动过程中工具消息一到就在清单里出现（不需要等回合结束重取历史）。
const FILE_IO_TOOLS: string[] = ['appendfile', 'editfile', 'writefile'];
const SEND_FILE_TOOL: string = 'sendfiletouser';
const FAILED_TOOL_STATES: string[] = [
  'cancelled', 'canceled', 'denied', 'error', 'failed', 'interrupted', 'rejected'
];

export interface ResponseArtifact {
  name: string;
  path: string;
  note: string;    // 变化类型（i18n 资源名后缀：created / modified / sent）
}

// 工具名归一（去掉非字母数字再小写）：wire 上是 write_file / write file / WriteFile 都能认
function normalizedToolName(name: string): string {
  return name.replace(/[^a-z\d]/gi, '').toLowerCase();
}

function artifactNote(tool: string): string {
  if (tool === SEND_FILE_TOOL) {
    return 'sent';
  }
  return tool === 'writefile' ? 'created' : 'modified';
}

export function responseArtifactsOf(messages: DisplayMessage[]): ResponseArtifact[] {
  const out: ResponseArtifact[] = [];
  for (const m of messages) {
    if (m.kind !== 'tool' || m.toolName === undefined || m.toolName.length === 0) {
      continue;
    }
    const tool: string = normalizedToolName(m.toolName);
    if (tool !== SEND_FILE_TOOL && FILE_IO_TOOLS.indexOf(tool) < 0) {
      continue;
    }
    const state: string = (m.toolState !== undefined ? m.toolState : '').toLowerCase();
    if (FAILED_TOOL_STATES.indexOf(state) >= 0) {
      continue;
    }
    const args: Record<string, Object> | null = asRecord(parseJson(
      m.toolArgs !== undefined ? m.toolArgs : ''));
    if (args === null) {
      continue;
    }
    const raw: Object = args['file_path'];
    if (typeof raw !== 'string') {
      continue;
    }
    const path: string = (raw as string).trim();
    if (path.length === 0 || !isResolvablePath(path)) {
      continue;
    }
    const segs: string[] = path.replace(/\\/g, '/').split('/');
    const name: string = segs.length > 0 && segs[segs.length - 1].length > 0
      ? segs[segs.length - 1] : path;
    const at: number = out.findIndex((a: ResponseArtifact): boolean => a.path === path);
    if (at >= 0) {
      out.splice(at, 1);
    }
    out.push({ name: name, path: path, note: artifactNote(tool) });
  }
  return out.reverse();
}

// 可解析的路径：绝对路径 / home 简写 / 盘符，或干净的相对路径（不允许空段与 .. 上跳）
function isResolvablePath(path: string): boolean {
  const p: string = path.replace(/\\/g, '/');
  if (p.startsWith('/') || p.startsWith('~') || /^[a-z]:\//i.test(p)) {
    return true;
  }
  const decoded: string = p.replace(/^(?:\.\/)+/, '');
  if (decoded.length === 0 || /^[a-z]:/i.test(decoded)) {
    return false;
  }
  for (const seg of decoded.split('/')) {
    if (seg.length === 0 || seg === '.' || seg === '..') {
      return false;
    }
  }
  return true;
}

/** 回合文件清单：工具产出文件 + 工具媒体分片（图片 / 截图等），按 url 去重（先文件后媒体）。 */
export function turnFilesOf(responses: DisplayMessage[]): DisplayPart[] {
  const out: DisplayPart[] = [];
  for (const a of responseArtifactsOf(responses)) {
    out.push({ type: 'file', url: a.path, name: a.name, note: a.note });
  }
  const seen: string[] = out.map((p: DisplayPart): string => mediaKey(p));
  for (const p of resultMediaOf(responses, answerIndexOf(responses))) {
    const k: string = mediaKey(p);
    if (seen.indexOf(k) < 0) {
      seen.push(k);
      out.push(p);
    }
  }
  return out;
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
    throw new ConnectError(tf($r('app.string.err_token_expired'), resp.responseCode));
  }
  if (resp.responseCode !== 200) {
    throw new ConnectError(tf($r('app.string.err_load_chat'), resp.responseCode));
  }
  const data: Record<string, Object> = jsonOf(resp);
  const arr: Object = data['messages'];
  let display: DisplayMessage[] = [];
  if (Array.isArray(arr)) {
    display = toDisplayMessages(arr as Object[]);
  }
  return {
    turns: toDisplayTurns(display),
    running: strOf(data, 'status') === 'running',
    userId: strOf(data, 'user_id')
  };
}

// ============ 流式对话（对齐 PR #7378 client.ts streamChat；传输 = atls 流式）============
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
  parts: ChatInputPart[], approvalLevel: string, userId: string,
  onDelta: (delta: StreamDelta) => void,
  onDone: (error: string | null) => void): ChatStreamHandle {
  const message: ChatInputMessage = { role: 'user', content: parts };
  // 身份口径：用会话自己的 user_id，缺省回落服务端默认身份 'default'
  // （console 的 DEFAULT_USER_ID = "default"；此前抄 7378 的 'mobile' 是 RN 应用自己的身份，
  //   对 console 建的会话不成立 → 服务端按 (session_id,user_id) 定位到别的 chat → 空流）
  const uid: string = userId.length > 0 ? userId : 'default';
  const payload: ChatStreamRequest = {
    input: [message],
    session_id: sessionId,
    user_id: uid,
    channel: 'console',
    stream: true
  };
  if (approvalLevel.length > 0) {
    const rc: StreamRequestContext = { approval_level: approvalLevel };
    payload.request_context = rc;
  }
  return openChatStream(baseUrl, token, agentId, payload, onDelta, onDone);
}

// 重连进行中的服务端会话（对齐 7378 client.reconnectChat：POST /console/chat {reconnect:true, session_id}）
export function reconnectChat(baseUrl: string, token: string, agentId: string, sessionId: string,
  userId: string,
  onDelta: (delta: StreamDelta) => void, onDone: (error: string | null) => void): ChatStreamHandle {
  const payload: ReconnectChatRequest = {
    reconnect: true,
    session_id: sessionId,
    user_id: userId.length > 0 ? userId : 'default',
    channel: 'console'
  };
  return openChatStream(baseUrl, token, agentId, payload, onDelta, onDone);
}

// SSE 流传输与解析（发送 / 重连共用）：payload 由调用方按各自口径构造
function openChatStream(baseUrl: string, token: string, agentId: string, payload: Object,
  onDelta: (delta: StreamDelta) => void, onDone: (error: string | null) => void): ChatStreamHandle {
  const parser: SseParser = new SseParser();
  const classifier: StreamEventClassifier = new StreamEventClassifier();
  const decoder: util.TextDecoder = util.TextDecoder.create('utf-8');
  let settled: boolean = false;
  // 是否已收到任何流数据（首个 onData 块）。SSE 的对端关流（run 结束 / idle 超时）
  // 在 atls 下多为干净关闭（onDone null）；真 reset / 读窗超时报错。只要流已交付过数据，
  // 内容已落、onDone 后 reloadTurns 会与真相对齐，该关流非真错误 → 静默收尾（finish(null)），
  // 不把传输噪音抛给用户。
  let receivedAnyData: boolean = false;

  const finish = (error: string | null): void => {
    if (settled) {
      return;
    }
    settled = true;
    onDone(error);
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
  const handle: AtStreamHandle = atlsStream({
    url: `${baseUrl}/api/console/chat`,
    method: http.RequestMethod.POST,
    header: header,
    bodyText: JSON.stringify(payload),
    connectMs: 10000,
    // atls 读窗须有限：对端 SSE 心跳间隔小于该窗即不误杀（300s 兜底）
    readMs: 300000,
    onData: (chunk: ArrayBuffer): void => {
      receivedAnyData = true;
      const decodeOpts: DecodeStreamOptions = { stream: true };
      const chunkText: string = decoder.decodeWithStream(new Uint8Array(chunk), decodeOpts);
      const events: SseEvent[] = parser.push(chunkText);
      for (const ev of events) {
        emit(ev);
      }
    },
    onDone: (error: string | null): void => {
      if (error === null) {
        const rest: SseEvent[] = parser.finish();
        for (const ev of rest) {
          emit(ev);
        }
        finish(null);
        return;
      }
      const lowered: string = error.toLowerCase();
      const peerClose: boolean = lowered.indexOf('from the peer') >= 0
        || lowered.indexOf('closed by peer') >= 0
        || lowered.indexOf('reset by peer') >= 0
        || lowered.indexOf('reset') >= 0;
      // 对端关流（SSE run 结束 / idle 超时）：流已交付过数据 → 内容已落、reloadTurns 对齐真相，
      // 静默收尾；或明确的 peer 关流消息。真错误仍走服务端 SSE error 帧（emit→streamError），
      // 服务不可达则由紧随其后的 reloadTurns 抛出。仅"连接建立即失败、零数据"才抛传输错误。
      if (receivedAnyData || peerClose) {
        finish(null);
      } else {
        finish(error);
      }
    }
  });

  return new ChatStream((): void => {
    finish(null);
    handle.stop();
  });
}

export async function stopChat(baseUrl: string, token: string, agentId: string,
  chatId: string): Promise<void> {
  const resp: http.HttpResponse = await doRequest(
    `${baseUrl}/api/console/chat/stop?chat_id=${encodeURIComponent(chatId)}`,
    http.RequestMethod.POST, null, token.length > 0 ? token : null, agentId);
  if (resp.responseCode < 200 || resp.responseCode >= 300) {
    throw new ConnectError(tf($r('app.string.err_stop_failed'), resp.responseCode));
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
  const multipart: MultipartBody = buildMultipart([{
    name: 'file',
    filePath: filePath,
    fileName: fileName,
    contentType: mime
  }]);
  const header: Record<string, Object> = {
    'Content-Type': multipart.contentType,
    'Accept': 'application/json'
  };
  if (token.length > 0) {
    header['Authorization'] = `Bearer ${token}`;
  }
  if (agentId.length > 0) {
    header['X-Agent-Id'] = agentId;
  }
  const resp: http.HttpResponse = await atlsRequest({
    url: `${baseUrl}/api/console/upload`,
    method: http.RequestMethod.POST,
    header: header,
    bodyBytes: multipart.body,
    connectMs: 15000,
    readMs: 60000
  });
  if (resp.responseCode < 200 || resp.responseCode >= 300) {
    throw new ConnectError(tf($r('app.string.err_upload_failed'), resp.responseCode));
  }
  const data: Record<string, Object> = JSON.parse(resp.result as string) as Record<string, Object>;
  const url: string = strOf(data, 'url');
  const name: string = strOf(data, 'file_name');
  const size: Object = data['size'];
  if (url.length === 0) {
    throw new ConnectError(t($r('app.string.err_upload_no_url')));
  }
  const out: UploadResult = {
    url: url,
    fileName: name.length > 0 ? name : fileName,
    size: typeof size === 'number' ? size as number : 0
  };
  return out;
}

// ============ 路由参数 / 输入分片（保留，供页面层使用）============
export interface ChatRouteParam {
  chatId: string;
  chatName: string;
  sessionId: string;
  // 会话自己的 user_id（列表项带过来）：详情接口不返回它，丢了就只能回落 'default'，
  // 而 app 自建会话归属 'mobile' → 回落会挂到另一条同 session_id 的 chat 上空跑
  userId: string;
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

// 随发送下发的运行上下文（对齐 7378 api/client.ts：request_context.approval_level）
interface StreamRequestContext {
  approval_level: string;
}

interface ChatStreamRequest {
  input: ChatInputMessage[];
  session_id: string;
  user_id: string;
  channel: string;
  stream: boolean;
  request_context?: StreamRequestContext;
}

// 重连进行中的会话（对齐 7378 client.reconnectChat 的请求体）
interface ReconnectChatRequest {
  reconnect: boolean;
  session_id: string;
  user_id: string;
  channel: string;
}

interface DecodeStreamOptions {
  stream: boolean;
}
