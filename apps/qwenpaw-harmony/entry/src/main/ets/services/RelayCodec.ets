/*
 * Relay 帧编解码 —— qwenpaw-api-contract v0.1.0 src/relay.ts 的 ArkTS 移植
 * 来源：PR agentscope-ai/QwenPaw#7378 head 3a05b97a（冻结契约基线，见工作区 contracts/）
 *
 * 逐帧一致性要求（contracts/README 版本纪律第 4 条）：
 *  - 行为与 relay.ts 相同；node24 对拍：PR relayProtocol.test.ts 4/4 PASS
 *  - canonical 字节向量（HELLO/PONG/DATA hex）见 CodecSelfTest.ets
 *
 * 与 TS 原版的刻意偏差（ArkTS 语言约束，行为不变）：
 *  1. assertRelayHeader 用普通函数 + throw（ArkTS 无 assertion functions），调用方语义相同
 *  2. unknown/类型守卫 → Object + 显式 as 转换
 *  3. 稳定 JSON 通过 headerToRecord 显式拷贝 6 个字段（undefined 字段不写入，与 JSON.stringify 行为一致）
 *  4. TextEncoder/TextDecoder 非 ArkTS 全局 → @kit.ArkTS util（UTF-8，行为相同）
 */

import { util } from '@kit.ArkTS';

export const RELAY_PROTOCOL_VERSION: number = 1;
export const CONTRACT_VERSION: string = '0.1.0';

export type RelayFrameType =
  | 'hello'
  | 'open'
  | 'data'
  | 'end'
  | 'result_meta'
  | 'cancel'
  | 'error'
  | 'ping'
  | 'pong'
  | 'session_event'
  | 'event_ack'
  | 'resume';

export interface RelayFrameHeader {
  v: number;
  type: RelayFrameType;
  stream_id?: string;
  request_id?: string;
  sequence?: number;
  metadata?: Record<string, Object>;
}

export interface RelayFrame {
  header: RelayFrameHeader;
  payload: Uint8Array;
}

export const RELAY_OPERATIONS: string[] = [
  'agent.list',
  'agent.get',
  'session.list',
  'session.get',
  'session.create',
  'session.update',
  'session.archive',
  'session.delete',
  'message.send',
  'run.cancel',
  'approval.resolve',
  'attachment.upload.begin',
  'attachment.upload.chunk',
  'attachment.upload.complete',
  'attachment.download'
];

const HEADER_PREFIX_BYTES: number = 4;
const MAX_HEADER_BYTES: number = 64 * 1024;

const frameTypes: Set<string> = new Set<string>([
  'hello',
  'open',
  'data',
  'end',
  'result_meta',
  'cancel',
  'error',
  'ping',
  'pong',
  'session_event',
  'event_ack',
  'resume'
]);

const streamFrameTypes: Set<string> = new Set<string>([
  'open',
  'data',
  'end',
  'result_meta',
  'cancel',
  'error'
]);

export function encodeRelayFrame(frame: RelayFrame): Uint8Array {
  assertRelayHeader(frame.header);
  const header: Uint8Array = new util.TextEncoder().encode(stableJson(headerToRecord(frame.header)));
  if (header.byteLength > MAX_HEADER_BYTES) {
    throw new Error('Relay frame header is too large');
  }
  const wire: Uint8Array = new Uint8Array(HEADER_PREFIX_BYTES + header.byteLength + frame.payload.byteLength);
  new DataView(wire.buffer).setUint32(0, header.byteLength, false);
  wire.set(header, HEADER_PREFIX_BYTES);
  wire.set(frame.payload, HEADER_PREFIX_BYTES + header.byteLength);
  return wire;
}

export function decodeRelayFrame(value: ArrayBuffer | Uint8Array): RelayFrame {
  const wire: Uint8Array = value instanceof Uint8Array ? value : new Uint8Array(value);
  if (wire.byteLength < HEADER_PREFIX_BYTES) {
    throw new Error('Relay frame is missing its header length');
  }
  const headerLength: number = new DataView(wire.buffer, wire.byteOffset, wire.byteLength).getUint32(0, false);
  if (headerLength <= 0 || headerLength > MAX_HEADER_BYTES) {
    throw new Error('Relay frame header length is invalid');
  }
  const headerEnd: number = HEADER_PREFIX_BYTES + headerLength;
  if (wire.byteLength < headerEnd) {
    throw new Error('Relay frame header is truncated');
  }
  let header: Object;
  try {
    header = JSON.parse(new util.TextDecoder('utf-8').decode(wire.subarray(HEADER_PREFIX_BYTES, headerEnd))) as Object;
  } catch (e) {
    throw new Error('Relay frame header is not valid JSON');
  }
  assertRelayHeader(header);
  const frame: RelayFrame = { header: header as RelayFrameHeader, payload: wire.slice(headerEnd) };
  return frame;
}

export function assertRelayHeader(value: Object): void {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('Relay frame header must be an object');
  }
  const header: Record<string, Object> = value as Record<string, Object>;
  if (header['v'] !== RELAY_PROTOCOL_VERSION) {
    throw new Error(`Unsupported Relay protocol version: ${String(header['v'])}`);
  }
  if (typeof header['type'] !== 'string' || !frameTypes.has(header['type'] as string)) {
    throw new Error('Relay frame type is unsupported');
  }
  if (header['sequence'] !== undefined &&
    (!Number.isSafeInteger(header['sequence'] as number) || Number(header['sequence']) < 0)) {
    throw new Error('Frame sequence must be a non-negative integer');
  }
  if (header['metadata'] !== undefined &&
    (!header['metadata'] || typeof header['metadata'] !== 'object' || Array.isArray(header['metadata']))) {
    throw new Error('Relay frame metadata must be an object');
  }
  const frameType: string = header['type'] as string;
  if (streamFrameTypes.has(frameType) && !nonEmptyString(header['stream_id'])) {
    throw new Error(`${frameType} frame requires stream_id`);
  }
  if (frameType === 'open') {
    const md: Record<string, Object> =
      header['metadata'] !== undefined ? header['metadata'] as Record<string, Object> : ({} as Record<string, Object>);
    if (!nonEmptyString(header['request_id'])) {
      throw new Error('Open frame requires request_id');
    }
    if (!nonEmptyString(md['operation_id']) || !isRelayOperation(md['operation_id'] as string)) {
      throw new Error('Open frame operation_id is unsupported');
    }
    if (!Number.isSafeInteger(md['schema_version'] as number) || Number(md['schema_version']) < 1) {
      throw new Error('Open frame schema_version is invalid');
    }
  }
  if (frameType === 'session_event') {
    const md: Record<string, Object> =
      header['metadata'] !== undefined ? header['metadata'] as Record<string, Object> : ({} as Record<string, Object>);
    const missing: string[] = ['session_id', 'event_id', 'event_type'].filter((key: string) => !nonEmptyString(md[key]));
    if (!Number.isSafeInteger(md['session_revision'] as number)) {
      missing.push('session_revision');
    }
    if (!Number.isSafeInteger(header['sequence'] as number)) {
      missing.push('sequence');
    }
    if (missing.length > 0) {
      throw new Error(`Session event is missing: ${missing.join(', ')}`);
    }
  }
  if (frameType === 'event_ack' &&
    (!Number.isSafeInteger(header['sequence'] as number) ||
      !nonEmptyString((header['metadata'] as Record<string, Object> | undefined)?.['session_id']))) {
    throw new Error('Event acknowledgement requires session_id and sequence');
  }
}

export function isRelayOperation(value: string): boolean {
  return RELAY_OPERATIONS.includes(value);
}

function nonEmptyString(value: Object | undefined): boolean {
  return typeof value === 'string' && (value as string).length > 0;
}

function headerToRecord(header: RelayFrameHeader): Record<string, Object> {
  const r: Record<string, Object> = {};
  r['v'] = header.v;
  r['type'] = header.type;
  if (header.stream_id !== undefined) {
    r['stream_id'] = header.stream_id;
  }
  if (header.request_id !== undefined) {
    r['request_id'] = header.request_id;
  }
  if (header.sequence !== undefined) {
    r['sequence'] = header.sequence;
  }
  if (header.metadata !== undefined) {
    r['metadata'] = header.metadata;
  }
  return r;
}

function stableJson(value: Record<string, Object>): string {
  const keys: string[] = Object.keys(value).sort();
  const sorted: Record<string, Object> = {};
  for (const key of keys) {
    sorted[key] = value[key];
  }
  return JSON.stringify(sorted);
}
