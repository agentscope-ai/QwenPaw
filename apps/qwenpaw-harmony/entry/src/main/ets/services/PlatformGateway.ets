/*
 * 云端实例（Platform 上创建的 QwenPaw）的网关复签 —— 对齐 7378
 * `api/platformGateway.ts` + `api/platformGatewayModel.ts` 的行为。
 *
 * 机制（7378 原样）：云端实例的地址是 Platform 网关域名，直接请求会拿到网关登录页而不是 API 的 JSON；
 * 客户端要先用 **Platform 登录态**请求一次 `/api/v1/qwenpaw/{appId}`（本函数里的 accessPath）换放行，
 * 然后**重放**原请求。判定"拿到的是网关登录页"= 状态 401/403 且 Content-Type 含 text/html；
 * 同一 baseUrl 的复签**单飞去重**（并发只跑一次）。
 *
 * accessPath 从哪来：① 入栈/配对时由 Platform 返回（`/api/v1/qwenpaw/{appId}`）；② 主机名形如
 * `<appId>.qwenpaw.platform.agentscope.io` 时可直接反推。
 *
 * 放行态怎么带回实例请求：鸿蒙 NetworkKit 的 `HttpRequest.enableAutoCookie(true)`（API 26）会让
 * **同一 HttpRequest 实例的多次请求之间**自动携带/共享服务端下发的 cookie —— 见 services/ConnectionService
 * 里按 origin 复用实例的写法；响应侧 `HttpResponse.cookies` 也可直接读到下发值（本文件不解析它，
 * 交给平台自动共享，避免两套 cookie 逻辑）。
 */

import { common } from '@kit.AbilityKit';
import { http } from '@kit.NetworkKit';
import { url } from '@kit.ArkTS';
import { platformRequest, platformRequestRaw, PlatformResponse } from './PlatformSession';
import { tf } from './I18n';

/** Platform 网关登录取值：401/403 + Content-Type text/html（7378 isPlatformGatewayAuthResponse） */
export function isGatewayAuthResponse(status: number, contentType: string): boolean {
  return (status === 401 || status === 403) && contentType.toLowerCase().includes('text/html');
}

/** 从任意形态的入口值里取出 accessPath（7378 platformAccessPath）：整 URL 取 path，裸串找 /api/ 起点 */
export function gatewayAccessPath(value: string): string {
  const trimmed: string = value.trim();
  if (trimmed.length === 0) {
    return '';
  }
  if (trimmed.startsWith('http://') || trimmed.startsWith('https://')) {
    const at: number = trimmed.indexOf('/api/');
    return at >= 0 ? trimmed.substring(at) : '';
  }
  const at: number = trimmed.indexOf('/api/');
  return at >= 0 ? trimmed.substring(at) : (trimmed.startsWith('/api/') ? trimmed : '');
}

/** 由网关主机名反推 accessPath（7378 inferPlatformAccessPath） */
export function inferGatewayAccessPath(baseUrl: string): string {
  const suffix: string = '.qwenpaw.platform.agentscope.io';
  let host: string = '';
  try {
    const at: number = baseUrl.indexOf('://');
    const rest: string = at >= 0 ? baseUrl.substring(at + 3) : baseUrl;
    const slash: number = rest.indexOf('/');
    host = (slash >= 0 ? rest.substring(0, slash) : rest).toLowerCase();
  } catch (e) {
    return '';
  }
  if (!host.endsWith(suffix)) {
    return '';
  }
  const appId: string = host.substring(0, host.length - suffix.length);
  if (appId.length === 0) {
    return '';
  }
  for (let i = 0; i < appId.length; i++) {
    const c: string = appId.charAt(i);
    const ok: boolean = (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c === '-';
    if (!ok) {
      return '';
    }
  }
  return `/api/v1/qwenpaw/${appId}`;
}

/** 从 Platform 回包里取实例控制台地址（7378 platformConsoleBaseUrl，最多下钻 3 层 data） */
export function gatewayConsoleBaseUrl(payload: Object): string {
  let value: Object = payload;
  for (let depth = 0; depth < 3; depth++) {
    if (value === null || typeof value !== 'object' || Array.isArray(value)) {
      return '';
    }
    const rec: Record<string, Object> = value as Record<string, Object>;
    const raw: Object = rec['console_base_url'] !== undefined
      ? rec['console_base_url'] : rec['consoleBaseUrl'];
    if (typeof raw === 'string' && (raw as string).trim().length > 0) {
      const url: string = (raw as string).trim();
      return originOf(url);
    }
    if (rec['data'] === undefined) {
      return '';
    }
    value = rec['data'];
  }
  return '';
}

function originOf(raw: string): string {
  try {
    const u: url.URL = new url.URL(raw);
    if (u.protocol !== 'http:' && u.protocol !== 'https:') {
      return '';
    }
    return `${u.protocol}//${u.host}`;
  } catch (e) {
    return '';
  }
}

// 应用上下文与 platform 源连接登记：请求层（ConnectionService.doRequest）是无 ctx 的纯函数，
// 这里在启动时绑定一次应用上下文，并在连接装载/保存时登记"哪些 origin 需要走网关复签"。
let boundCtx: common.Context | null = null;
const platformOrigins: Map<string, string> = new Map<string, string>();

/** 启动时绑定应用上下文（EntryAbility.onCreate / 根页 aboutToAppear 各调一次即可） */
export function bindPlatformContext(ctx: common.Context): void {
  boundCtx = ctx;
}

export function platformContext(): common.Context | null {
  return boundCtx;
}

/** 登记 / 注销一个 platform 源连接（origin → accessPath） */
export function registerGatewayConnection(baseUrl: string, accessPath: string): void {
  const key: string = originKey(baseUrl);
  if (key.length === 0) {
    return;
  }
  if (accessPath.length > 0) {
    platformOrigins.set(key, accessPath);
  } else {
    platformOrigins.delete(key);
  }
}

export function gatewayAccessPathOf(baseUrl: string): string {
  const key: string = originKey(baseUrl);
  return key.length > 0 && platformOrigins.has(key) ? platformOrigins.get(key) as string : '';
}

/** 供请求层复用同一套 origin 归一（避免两处各写一份） */
export function gatewayOriginKey(baseUrl: string): string {
  return originKey(baseUrl);
}

/** 复签换到的 cookie（按 origin 存；请求层回带到实例域名） */
export function gatewayCookieOf(baseUrl: string): string {
  const key: string = originKey(baseUrl);
  return key.length > 0 && gatewayCookies.has(key) ? gatewayCookies.get(key) as string : '';
}

const gatewayCookies: Map<string, string> = new Map<string, string>();

function originKey(baseUrl: string): string {
  const trimmed: string = baseUrl.toLowerCase().replace(/\/+$/, '');
  const at: number = trimmed.indexOf('://');
  const rest: string = at >= 0 ? trimmed.substring(at + 3) : trimmed;
  const slash: number = rest.indexOf('/');
  const host: string = slash >= 0 ? rest.substring(0, slash) : rest;
  return host.length > 0 ? host : '';
}

// 同一 baseUrl 单飞去重（7378 gatewayRefreshes）
const refreshing: Map<string, Promise<void>> = new Map<string, Promise<void>>();

/** 用 Platform 登录态换放行（7378 ensurePlatformGateway）：同一 baseUrl 并发只跑一次 */
export function ensurePlatformGateway(ctx: common.Context, baseUrl: string,
  accessPath: string): Promise<void> {
  const key: string = baseUrl.replace(/\/+$/, '');
  const path: string = accessPath.length > 0 ? accessPath : inferGatewayAccessPath(key);
  if (path.length === 0) {
    return Promise.reject(new Error(tf($r('app.string.gateway_err_no_access_path'))));
  }
  const running: Promise<void> | undefined = refreshing.get(key);
  if (running !== undefined) {
    return running;
  }
  const next: Promise<void> = prime(ctx, key, path).then((): void => {
    refreshing.delete(key);
  }, (err: Error): void => {
    refreshing.delete(key);
    throw err;
  });
  refreshing.set(key, next);
  return next;
}

// Platform 侧换放行：回包的 console 地址必须与当前 baseUrl 一致，否则视为没换成
async function prime(ctx: common.Context, baseUrl: string, accessPath: string): Promise<void> {
  const resp: PlatformResponse = await platformRequestRaw(ctx, accessPath, http.RequestMethod.GET, null);
  if (resp.status < 200 || resp.status >= 300) {
    throw new Error(tf($r('app.string.gateway_err_cannot_resume')));
  }
  const refreshed: string = gatewayConsoleBaseUrl(parseJson(resp.body));
  if (refreshed.length === 0 || refreshed.replace(/\/+$/, '') !== baseUrl) {
    throw new Error(tf($r('app.string.gateway_err_cannot_resume')));
  }
  // 放行态回带：不同域名之间浏览器 jar 会自动带，鸿蒙不是浏览器 —— 显式把 cookie 存下来，
  // 请求层对实例域名逐次回带（官方 FAQ faqs-network-7：cookie 直接放 header 即可）
  if (resp.cookies.length > 0) {
    gatewayCookies.set(originKey(baseUrl), resp.cookies);
  }
}

function parseJson(body: string): Object {
  try {
    return JSON.parse(body) as Object;
  } catch (e) {
    return new Object();
  }
}

/** 配对入口解析（7378 resolvePlatformQwenPawAccess）：拿到实例地址 + accessPath */
export async function resolveGatewayAccess(ctx: common.Context,
  value: string): Promise<GatewayAccess> {
  const path: string = gatewayAccessPath(value);
  if (path.length === 0) {
    throw new Error(tf($r('app.string.gateway_err_no_entry')));
  }
  const payload: Object = await platformRequest(ctx, path, http.RequestMethod.GET, null);
  const baseUrl: string = gatewayConsoleBaseUrl(payload);
  if (baseUrl.length === 0) {
    throw new Error(tf($r('app.string.gateway_err_no_base_url')));
  }
  const out: GatewayAccess = { baseUrl: baseUrl, accessPath: path };
  return out;
}

export interface GatewayAccess {
  baseUrl: string;
  accessPath: string;
}
