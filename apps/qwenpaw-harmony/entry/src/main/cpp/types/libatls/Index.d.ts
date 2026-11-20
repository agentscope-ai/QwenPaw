// atls 原生传输层类型声明（实现：src/main/cpp/napi_init.cpp）
//
// 错误协议：传输层失败 reject Error("atls:<kind>: <detail>")，
// kind 与 C 侧 atls_kind_name 一份定义（atls_http.h）。

export interface AtlsRequestOpts {
  url: string;
  // GET/POST/PUT/DELETE/HEAD/PATCH（http.RequestMethod 的值即字符串）
  method?: string;
  headers?: Record<string, string>;
  // 文本体与二进制体二选一（同时给时二进制体覆盖文本体）
  bodyText?: string | null;
  bodyBytes?: ArrayBuffer | null;
  connectMs?: number;
  readMs?: number;
  // beginCancelSlot() 返回的槽 id；-1 或省略 = 不可取消
  cancelId?: number;
}

export interface AtlsResponse {
  status: number;
  // 小写 key；重复键后者胜（set-cookie 除外，见 setCookies）
  headers: Record<string, string>;
  // 全部 Set-Cookie 头原值（多条各占一项）
  setCookies: string[];
  // 空体 = null
  body: ArrayBuffer | null;
}

export interface AtlsProbeResult {
  // 协商协议（如 TLSv1.3）
  protocol: string;
  // 协商套件（如 TLS_AES_128_GCM_SHA256）
  cipher: string;
}

export interface AtlsStreamInfo {
  status: number;
  headers: Record<string, string>;
  setCookies: string[];
}

export interface AtlsStreamOpts extends AtlsRequestOpts {
  // 数据块回调（块 ≤8KB，帧边界无关——SSE 行帧由上层解析器重建）
  onData: (chunk: ArrayBuffer) => void;
  // 最终响应头回调（3xx 跟跳后仅最终响应触发一次；省略 = 不要）
  onHeaders?: (info: AtlsStreamInfo) => void;
}

// 运行时 NAPI 原生模块（default import 得到的模块对象含下列全部成员）
export const request: (opts: AtlsRequestOpts) => Promise<AtlsResponse>;
// 流式请求：onHeaders/onData 按到达顺序在 JS 线程派发；
// resolve 于流正常完结，reject Error("atls:<kind>: <detail>") 于传输层失败。
// 中止：cancelRequest(opts.cancelId)（C 侧轮询粒度 ≤200ms）。
export const requestStream: (opts: AtlsStreamOpts) => Promise<AtlsStreamInfo>;
export const tlsProbe: (host: string, port: number, timeoutMs: number) => Promise<AtlsProbeResult>;
export const version: () => string;
export const beginCancelSlot: () => number;
export const cancelRequest: (id: number) => void;
