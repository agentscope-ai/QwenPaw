/*
 * atls 传输层包装（ArkTS ⇄ libatls.so 原生边界）
 *
 * 全工程 HTTP 统一走自研 atls 栈（OpenSSL 3.5.9，规格与错误契约见
 * src/main/cpp/atls_http.h 头注释）：系统 http 的 TLS 指纹（OpenSSL 3.0 代 +
 * h2 ALPN + CBC/DHE 传统套件）在特定链路被中间设备按「SNI 域族 × 客户端指纹」
 * 重置，atls 的 OpenSSL 3.5 代指纹在实测链路中被放行。
 *
 * 本层只做三件事，不掺业务：
 *   1. 原生边界 + 错误收敛——传输层失败统一抛 AtTransportError（保留
 *      "atls:<kind>: <detail>" 原消息，kind 为 C 侧 atls_kind_name 稳定串）
 *   2. 形态适配——单次请求返回 http.HttpResponse 同形对象（result 文本/二进制
 *      双形态、header 小写 key、cookies = Set-Cookie 捕获的 Cookie 头格式），
 *      既有 doRequest/jsonOf 等调用面零改动
 *   3. 流式与 multipart——SSE 流（onData 分块 + stop() 取消）与 multipart
 *      体构造（设备侧文件拼装，多个上传点共用）
 */

import atls, {
  AtlsProbeResult,
  AtlsRequestOpts,
  AtlsResponse,
  AtlsStreamInfo,
  AtlsStreamOpts
} from 'libatls.so';
import { http } from '@kit.NetworkKit';
import { fileIo } from '@kit.CoreFileKit';
import { util } from '@kit.ArkTS';
import { BusinessError } from '@kit.BasicServicesKit';

// 传输层失败（连不上 / 超时 / DNS / TLS / 对端中断），区别于 HTTP 4xx/5xx 响应
export class AtTransportError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'AtTransportError';
  }
}

// "atls:<kind>: <detail>" → kind（前缀与 kind 名两侧共用 C 侧 atls_kind_name 一份定义）
export function atlsKindOf(message: string): string {
  if (message.indexOf('atls:') !== 0) {
    return '';
  }
  const end: number = message.indexOf(':', 5);
  return end < 0 ? message.slice(5) : message.slice(5, end);
}

// 原生 reject 值收敛为 AtTransportError（保原消息）
function toTransportError(e: Error): AtTransportError {
  const be = e as BusinessError;
  const msg: string = typeof be.message === 'string' && be.message.length > 0 ? be.message : String(e);
  return new AtTransportError(msg);
}

// ---------- 诊断出口（连通性自检 / 取证用） ----------

export function atlsTlsProbe(host: string, port: number, timeoutMs: number): Promise<AtlsProbeResult> {
  return atls.tlsProbe(host, port, timeoutMs);
}

export function atlsVersion(): string {
  return atls.version();
}

// ---------- 单次请求（http.HttpResponse 同形） ----------

export interface AtRequestOpts {
  url: string;
  method: http.RequestMethod;
  header?: Record<string, Object>;
  // 文本体 / 二进制体二选一（同时给时二进制体胜）
  bodyText?: string | null;
  bodyBytes?: ArrayBuffer | null;
  connectMs: number;
  readMs: number;
  // true = result 保留 ArrayBuffer（下载类）；false（缺省）= 解码为文本
  binary?: boolean;
}

// Set-Cookie 原值数组 → Cookie 请求头格式（仅取 name=value 段，丢弃属性段）
export function cookieJarOf(setCookies: string[]): string {
  const parts: string[] = [];
  for (const c of setCookies) {
    const i: number = c.indexOf(';');
    const pair: string = i < 0 ? c : c.slice(0, i);
    if (pair.trim().length > 0) {
      parts.push(pair.trim());
    }
  }
  return parts.join('; ');
}

function utf8Decode(buf: ArrayBuffer): string {
  return util.TextDecoder.create('utf-8').decodeToString(new Uint8Array(buf));
}

// 原生边界薄包装（显式 Promise 返回）：homecheck 推不出 NAPI d.ts 的返回类型
// （UnknownType），直接 await 原生调用会触发 await-thenable
function nativeRequest(opts: AtlsRequestOpts): Promise<AtlsResponse> {
  return atls.request(opts);
}

export async function atlsRequest(opts: AtRequestOpts): Promise<http.HttpResponse> {
  const header: Record<string, string> = {};
  if (opts.header !== undefined) {
    for (const k of Object.keys(opts.header)) {
      header[k] = String(opts.header[k]);
    }
  }
  const no: AtlsRequestOpts = {
    url: opts.url,
    method: opts.method as string,
    headers: header,
    bodyText: opts.bodyText !== undefined && opts.bodyText !== null ? opts.bodyText : null,
    bodyBytes: opts.bodyBytes !== undefined && opts.bodyBytes !== null ? opts.bodyBytes : null,
    connectMs: opts.connectMs,
    readMs: opts.readMs
  };
  let resp: AtlsResponse;
  try {
    resp = await nativeRequest(no);
  } catch (e) {
    throw toTransportError(e as Error);
  }
  const h: Record<string, string> = resp.headers;
  const headerOut: Record<string, Object> = {};
  for (const k of Object.keys(h)) {
    headerOut[k] = h[k];
  }
  const body: ArrayBuffer | null = resp.body;
  const binary: boolean = opts.binary === true;
  let result: string | ArrayBuffer;
  if (binary) {
    result = body !== null ? body : '';
  } else {
    result = body !== null ? utf8Decode(body) : '';
  }
  // atls 不逐阶段计时（C 层只到"整请求完成"），performanceTiming 全零；
  // 既有调用面不读该字段，占位仅为满足 HttpResponse 契约
  const out: http.HttpResponse = {
    responseCode: resp.status,
    result: result,
    resultType: binary ? http.HttpDataType.ARRAY_BUFFER : http.HttpDataType.STRING,
    header: headerOut,
    cookies: cookieJarOf(resp.setCookies),
    performanceTiming: {
      dnsTiming: 0,
      tcpTiming: 0,
      tlsTiming: 0,
      firstSendTiming: 0,
      firstReceiveTiming: 0,
      redirectTiming: 0,
      responseHeaderTiming: 0,
      responseBodyTiming: 0,
      totalFinishTiming: 0,
      totalTiming: 0
    }
  };
  return out;
}

// ---------- 流式请求（SSE 等分块交付） ----------

export interface AtStreamOpts {
  url: string;
  method: http.RequestMethod;
  header: Record<string, Object>;
  bodyText: string | null;
  connectMs: number;
  // atls 读窗须有限：对端心跳/事件间隔小于该值即不误杀
  readMs: number;
  // 分块回调（≤8KB，帧边界无关——SSE 行帧由上层 SseParser 重建）
  onData: (chunk: ArrayBuffer) => void;
  // 最终响应头（3xx 跟跳后仅最终响应触发一次；可省略）
  onHeaders?: (info: AtlsStreamInfo) => void;
  // 收尾：null = 流正常完结（含对端干净关闭）；非 null = 传输层错误原消息
  onDone: (error: string | null) => void;
}

export interface AtStreamHandle {
  stop(): void;
}

class AtStream implements AtStreamHandle {
  private stopped: boolean = false;
  private readonly slotId: number;

  constructor(slotId: number) {
    this.slotId = slotId;
  }

  stop(): void {
    // 槽未回收 = 在途 → 置位取消（C 侧轮询 ≤200ms）；已收尾 = no-op
    if (!this.stopped) {
      this.stopped = true;
      atls.cancelRequest(this.slotId);
    }
  }
}

export function atlsStream(opts: AtStreamOpts): AtStreamHandle {
  const slotId: number = atls.beginCancelSlot();
  const header: Record<string, string> = {};
  for (const k of Object.keys(opts.header)) {
    header[k] = String(opts.header[k]);
  }
  const no: AtlsStreamOpts = {
    url: opts.url,
    method: opts.method as string,
    headers: header,
    bodyText: opts.bodyText,
    connectMs: opts.connectMs,
    readMs: opts.readMs,
    cancelId: slotId,
    onData: opts.onData
  };
  if (opts.onHeaders !== undefined) {
    no.onHeaders = opts.onHeaders;
  }
  let done: boolean = false;
  const finish: (error: string | null) => void = (error: string | null): void => {
    if (!done) {
      done = true;
      opts.onDone(error);
    }
  };
  atls.requestStream(no)
    .then((info: AtlsStreamInfo): void => {
      finish(null);
    })
    .catch((e: Error): void => {
      finish(e.message);
    });
  return new AtStream(slotId);
}

// ---------- multipart/form-data 体构造（多个上传点共用） ----------

export interface MultipartFilePart {
  // 表单字段名（服务端按该名收 list[UploadFile] / UploadFile）
  name: string;
  filePath: string;
  fileName: string;
  contentType: string;
}

export interface MultipartBody {
  body: ArrayBuffer;
  // 含 boundary 的完整 Content-Type 头值
  contentType: string;
}

// 单请求 multipart 体上限（服务端解压 + 热加载慢，超大文件无意义；
// 系统 http 无此限制，超限即抛错由调用方给提示）
export const MULTIPART_MAX_BYTES: number = 512 * 1024 * 1024;

function readFileBytes(path: string): Uint8Array {
  const f: fileIo.File = fileIo.openSync(path, fileIo.OpenMode.READ_ONLY);
  try {
    const size: number = fileIo.statSync(f.fd).size;
    if (size <= 0) {
      return new Uint8Array(0);
    }
    const buf: ArrayBuffer = new ArrayBuffer(size);
    const read: number = fileIo.readSync(f.fd, buf);
    return new Uint8Array(read >= size ? buf : buf.slice(0, read));
  } finally {
    fileIo.closeSync(f);
  }
}

export function buildMultipart(parts: MultipartFilePart[]): MultipartBody {
  const boundary: string =
    `----atls${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`;
  const enc: util.TextEncoder = new util.TextEncoder();
  const chunks: Uint8Array[] = [];
  let total: number = 0;
  const push: (c: Uint8Array) => void = (c: Uint8Array): void => {
    chunks.push(c);
    total += c.length;
  };
  for (const p of parts) {
    const head: string = `--${boundary}\r\n` +
      `Content-Disposition: form-data; name="${p.name}"; filename="${p.fileName}"\r\n` +
      `Content-Type: ${p.contentType.length > 0 ? p.contentType : 'application/octet-stream'}\r\n\r\n`;
    push(enc.encodeInto(head));
    push(readFileBytes(p.filePath));
    push(enc.encodeInto(`\r\n`));
  }
  push(enc.encodeInto(`--${boundary}--\r\n`));
  if (total > MULTIPART_MAX_BYTES) {
    throw new AtTransportError(`attachment too large: ${total} bytes (limit ${MULTIPART_MAX_BYTES})`);
  }
  const out: Uint8Array = new Uint8Array(total);
  let off: number = 0;
  for (const c of chunks) {
    out.set(c, off);
    off += c.length;
  }
  return {
    body: out.buffer as ArrayBuffer,
    contentType: `multipart/form-data; boundary=${boundary}`
  };
}
