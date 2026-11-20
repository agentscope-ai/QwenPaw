/*
 * AgentScope Platform 会话 —— 移植 PR #7378 api/platform.ts + storage/platformSession.ts
 * + api/platformError.ts + api/platformSessionModel.ts（一期只要社区所需的账号密码登录与票据续期）。
 *
 * 与 7378 的差异（有意）：
 *   - GitHub OAuth 的**回跳服务端**未移植：本端不起 loopback 监听，回跳靠内嵌 Web 加载前拦截
 *     （见 services/PlatformOAuth.ets）；换取令牌走 platformOAuthExchange。
 *   - 令牌持久化用应用沙箱 preferences（7378 用 SecureStore/钥匙串）。已知差距：明文存沙箱，
 *     商用前需补 HUKS 安全存储（与 ConnectionStore 同口径）。
 *   - Platform 地址一期固定为官方域名（7378 用 EXPO_PUBLIC_PLATFORM_BASE_URL 编译期注入）。
 */

import { http } from '@kit.NetworkKit';
import { preferences } from '@kit.ArkData';
import { Context } from '@kit.AbilityKit';
import { atlsRequest } from './AtlsTransport';
import { objOf, strOf, numOf } from './JsonUtil';
import { OAUTH_CLIENT_ID } from './PlatformOAuth';
import { t, tf } from './I18n';

export const DEFAULT_PLATFORM_BASE_URL: string = 'https://platform.agentscope.io';
export const PLATFORM_BASE_URL: string = DEFAULT_PLATFORM_BASE_URL;

const STORE_NAME: string = 'qwenpaw.platform.session';
const KEY_SESSION: string = 'qwenpaw.mobile.platform-session.v1';
const REQUEST_TIMEOUT_MS: number = 15000;
// 提前续期窗口（秒）：与 7378 REFRESH_EARLY_SECONDS 一致
const REFRESH_EARLY_SECONDS: number = 300;

export interface PlatformSession {
  accessToken: string;
  refreshToken: string;
  // 绝对过期时刻（epoch 秒）——与 7378 口径一致
  expiresAt: number;
  refreshMode: string;   // 'web' | 'cli' | ''
  username: string;
}

export class PlatformRequestError extends Error {
  status: number;
  code: string;
  retryAfterMs: number;

  constructor(message: string, status: number, code: string, retryAfterMs: number) {
    super(message);
    this.name = 'PlatformRequestError';
    this.status = status;
    this.code = code;
    this.retryAfterMs = retryAfterMs;
  }
}

function isInvalidSessionError(e: Error): boolean {
  if (!(e instanceof PlatformRequestError)) {
    return false;
  }
  const err: PlatformRequestError = e as PlatformRequestError;
  if (err.status === 401) {
    return true;
  }
  return err.code === 'ASP.AUTH.SESSION_INVALID' || err.code === 'SESSION_INVALID' ||
    err.code === 'UNAUTHORIZED' || err.code === 'UNAUTHENTICATED';
}

// Retry-After：秒数或 HTTP 日期（对齐 7378 parseRetryAfter）
function parseRetryAfter(value: string): number {
  if (value.length === 0) {
    return 0;
  }
  const seconds: number = Number(value);
  if (isFinite(seconds) && seconds >= 0) {
    return seconds * 1000;
  }
  const date: number = Date.parse(value);
  if (!isFinite(date)) {
    return 0;
  }
  return Math.max(0, date - Date.now());
}

export interface PlatformResponse {
  status: number;
  body: string;
  // 响应下发的 cookie（平台响应也可能带会话 cookie；网关复签要把它回带到实例域名，
  // 见 PlatformGateway：不同域之间不会自动共享，必须显式放进请求 header）
  cookies: string;
}

// 单次 HTTP（atls）：body 为 null 表示无请求体；token 为空则不带 Authorization
export async function platformFetchRaw(path: string, method: http.RequestMethod,
  body: string | null, token: string): Promise<PlatformResponse> {
  const header: Record<string, Object> = { 'Accept': 'application/json' };
  if (body !== null) {
    header['Content-Type'] = 'application/json';
  }
  if (token.length > 0) {
    header['Authorization'] = `Bearer ${token}`;
  }
  const resp: http.HttpResponse = await atlsRequest({
    url: `${PLATFORM_BASE_URL}${path}`,
    method: method,
    header: header,
    bodyText: body,
    connectMs: REQUEST_TIMEOUT_MS,
    readMs: REQUEST_TIMEOUT_MS
  });
  const result: Object = resp.result;
  return {
    status: resp.responseCode,
    body: typeof result === 'string' ? result as string : '',
    cookies: typeof resp.cookies === 'string' ? resp.cookies as string : ''
  };
}

// 错误体解析（对齐 7378 platformResponseError：优先 error.message/detail，其次 detail/message）
function responseError(status: number, body: string): PlatformRequestError {
  let message: string = tf($r('app.string.platform_err_request'), status);
  let code: string = '';
  let retryAfterMs: number = 0;
  try {
    const parsed: Record<string, Object> = JSON.parse(body) as Record<string, Object>;
    const errObj: Object = parsed['error'];
    let detail: string = '';
    if (errObj !== undefined && errObj !== null && typeof errObj === 'object') {
      const e: Record<string, Object> = errObj as Record<string, Object>;
      detail = typeof e['message'] === 'string' ? e['message'] as string
        : (typeof e['detail'] === 'string' ? e['detail'] as string : '');
      code = typeof e['code'] === 'string' ? e['code'] as string : '';
    }
    if (detail.length === 0 && typeof parsed['detail'] === 'string') {
      detail = parsed['detail'] as string;
    }
    if (detail.length === 0 && typeof parsed['message'] === 'string') {
      detail = parsed['message'] as string;
    }
    if (detail.length > 0) {
      message = detail;
    }
    if (code.length === 0) {
      if (typeof parsed['code'] === 'string') {
        code = parsed['code'] as string;
      } else if (typeof parsed['errorCode'] === 'string') {
        code = parsed['errorCode'] as string;
      }
    }
  } catch (e) {
    // 非 JSON：保留 HTTP 状态文案
  }
  if (code.length > 0 && message.indexOf(code) < 0) {
    message = `${code}: ${message}`;
  }
  return new PlatformRequestError(message, status, code, retryAfterMs);
}

// 登录/续期响应 → 会话（对齐 7378 extractPlatformSession 的字段兼容口径）
function extractSession(payload: Record<string, Object>, fallbackUsername: string,
  refreshMode: string): PlatformSession {
  const first: Record<string, Object> = objOf(payload['data']) !== null
    ? objOf(payload['data']) as Record<string, Object> : payload;
  const data: Record<string, Object> = objOf(first['data']) !== null
    ? objOf(first['data']) as Record<string, Object> : first;
  const user: Record<string, Object> | null = objOf(data['user']);
  let accessToken: string = strOf(data, 'accessToken', '');
  if (accessToken.length === 0) {
    accessToken = strOf(data, 'access_token', '');
  }
  let refreshToken: string = strOf(data, 'refreshToken', '');
  if (refreshToken.length === 0) {
    refreshToken = strOf(data, 'refresh_token', '');
  }
  let expiresIn: number = numOf(data, 'expiresIn', 0);
  if (expiresIn === 0) {
    expiresIn = numOf(data, 'expires_in', 0);
  }
  if (accessToken.length === 0 || refreshToken.length === 0) {
    throw new Error(t($r('app.string.platform_err_login_no_cred')));
  }
  let username: string = fallbackUsername;
  if (user !== null) {
    const name: string = strOf(user, 'username', '');
    username = name.length > 0 ? name : strOf(user, 'name', fallbackUsername);
  }
  const now: number = Math.floor(Date.now() / 1000);
  const session: PlatformSession = {
    accessToken: accessToken,
    refreshToken: refreshToken,
    expiresAt: expiresIn > now ? expiresIn : now + expiresIn,
    refreshMode: refreshMode,
    username: username
  };
  return session;
}

export async function loadPlatformSession(ctx: Context): Promise<PlatformSession | null> {
  try {
    const store: preferences.Preferences = await preferences.getPreferences(ctx, STORE_NAME);
    const raw: preferences.ValueType = await store.get(KEY_SESSION, '');
    if (typeof raw !== 'string' || (raw as string).length === 0) {
      return null;
    }
    const o: Record<string, Object> = JSON.parse(raw as string) as Record<string, Object>;
    const session: PlatformSession = {
      accessToken: strOf(o, 'accessToken', ''),
      refreshToken: strOf(o, 'refreshToken', ''),
      expiresAt: numOf(o, 'expiresAt', 0),
      refreshMode: strOf(o, 'refreshMode', ''),
      username: strOf(o, 'username', '')
    };
    if (session.accessToken.length === 0 || session.refreshToken.length === 0) {
      return null;
    }
    return session;
  } catch (e) {
    return null;
  }
}

export async function savePlatformSession(ctx: Context, session: PlatformSession): Promise<void> {
  const store: preferences.Preferences = await preferences.getPreferences(ctx, STORE_NAME);
  await store.put(KEY_SESSION, JSON.stringify(session));
  await store.flush();
}

export async function clearPlatformSession(ctx: Context): Promise<void> {
  const store: preferences.Preferences = await preferences.getPreferences(ctx, STORE_NAME);
  await store.delete(KEY_SESSION);
  await store.flush();
}

// 续期请求（对齐 7378 platformRefreshRequest：cli 与 web 两套路径/字段）
async function requestRefresh(session: PlatformSession): Promise<PlatformSession> {
  const modes: string[] = session.refreshMode.length > 0 ? [session.refreshMode] : ['web', 'cli'];
  let lastError: Error | null = null;
  for (const mode of modes) {
    const cli: boolean = mode === 'cli';
    const path: string = cli ? '/api/cli/v1/auth/refresh' : '/api/v1/auth/refresh';
    const body: string = cli
      ? JSON.stringify({ 'refresh_token': session.refreshToken })
      : JSON.stringify({ 'refreshToken': session.refreshToken });
    let resp: PlatformResponse;
    try {
      resp = await platformFetchRaw(path, http.RequestMethod.POST, body, '');
    } catch (e) {
      lastError = e as Error;
      continue;
    }
    if (resp.status >= 200 && resp.status < 300) {
      const payload: Record<string, Object> = JSON.parse(resp.body) as Record<string, Object>;
      return extractSession(payload, session.username, mode);
    }
    const err: PlatformRequestError = responseError(resp.status, resp.body);
    lastError = err as Error;
    if (session.refreshMode.length > 0 || !isInvalidSessionError(err as Error)) {
      throw err;
    }
  }
  throw lastError !== null ? lastError : new Error(t($r('app.string.platform_err_refresh')));
}

// 内存态会话 + 单飞续期（对齐 7378 PlatformTokenCoordinator 的语义）
let cached: PlatformSession | null = null;
let refreshing: Promise<PlatformSession | null> | null = null;

async function ensureCached(ctx: Context): Promise<PlatformSession | null> {
  if (cached === null) {
    cached = await loadPlatformSession(ctx);
  }
  return cached;
}

async function refreshOnce(ctx: Context): Promise<PlatformSession | null> {
  if (refreshing === null) {
    refreshing = (async (): Promise<PlatformSession | null> => {
      const current: PlatformSession | null = await ensureCached(ctx);
      if (current === null) {
        return null;
      }
      try {
        const next: PlatformSession = await requestRefresh(current);
        await savePlatformSession(ctx, next);
        cached = next;
        return next;
      } catch (e) {
        if (isInvalidSessionError(e as Error)) {
          await clearPlatformSession(ctx);
          cached = null;
          return null;
        }
        throw e as Error;
      } finally {
        refreshing = null;
      }
    })();
  }
  return refreshing;
}

// 当前有效访问令牌：距过期 ≤ 300s 先续期；无会话返回空串
export async function getPlatformAccessToken(ctx: Context): Promise<string> {
  let session: PlatformSession | null = await ensureCached(ctx);
  if (session === null) {
    return '';
  }
  const now: number = Math.floor(Date.now() / 1000);
  if (session.expiresAt - now <= REFRESH_EARLY_SECONDS) {
    const next: PlatformSession | null = await refreshOnce(ctx);
    if (next === null) {
      return '';
    }
    session = next;
  }
  return session.accessToken;
}

export async function platformLogin(ctx: Context, account: string, password: string): Promise<PlatformSession> {
  const body: string = JSON.stringify({ 'account': account, 'password': password });
  const resp: PlatformResponse =
    await platformFetchRaw('/api/v1/auth/login', http.RequestMethod.POST, body, '');
  if (resp.status < 200 || resp.status >= 300) {
    throw responseError(resp.status, resp.body);
  }
  const session: PlatformSession =
    extractSession(JSON.parse(resp.body) as Record<string, Object>, '', 'web');
  await savePlatformSession(ctx, session);
  cached = session;
  return session;
}

// GitHub OAuth 授权码换令牌 —— 对齐 7378 loginAgentScopePlatformWithGitHub 的令牌交换
// （POST /api/cli/v1/oauth/token，grant_type=authorization_code + code_verifier）与其后的
// finalizeCliOAuthSession（换到的令牌里通常没有用户名，续期一次补齐；续期失败就用初值）。
export async function platformOAuthExchange(ctx: Context, code: string, redirectUri: string,
  codeVerifier: string): Promise<PlatformSession> {
  const body: string = JSON.stringify({
    'grant_type': 'authorization_code',
    'client_id': OAUTH_CLIENT_ID,
    'code': code,
    'redirect_uri': redirectUri,
    'code_verifier': codeVerifier
  });
  const resp: PlatformResponse =
    await platformFetchRaw('/api/cli/v1/oauth/token', http.RequestMethod.POST, body, '');
  if (resp.status < 200 || resp.status >= 300) {
    throw responseError(resp.status, resp.body);
  }
  const session: PlatformSession =
    extractSession(JSON.parse(resp.body) as Record<string, Object>, '', 'cli');
  await savePlatformSession(ctx, session);
  cached = session;
  const hydrated: PlatformSession | null = await refreshOnce(ctx);
  return hydrated !== null ? hydrated : session;
}

export async function sendPlatformVerificationCode(account: string): Promise<void> {
  const body: string = JSON.stringify({ 'account': account, 'purpose': 'register' });
  const resp: PlatformResponse = await platformFetchRaw(
    '/api/v1/auth/send-verify-email-code', http.RequestMethod.POST, body, '');
  if (resp.status < 200 || resp.status >= 300) {
    throw responseError(resp.status, resp.body);
  }
}

export async function registerPlatform(account: string, password: string,
  verifyCode: string): Promise<void> {
  const body: string = JSON.stringify({
    'account': account, 'password': password, 'verifyCode': verifyCode
  });
  const resp: PlatformResponse =
    await platformFetchRaw('/api/v1/auth/register', http.RequestMethod.POST, body, '');
  if (resp.status < 200 || resp.status >= 300) {
    throw responseError(resp.status, resp.body);
  }
}

export async function platformLogout(ctx: Context): Promise<void> {
  cached = null;
  await clearPlatformSession(ctx);
}

// 带鉴权的 Platform 请求：401/会话失效时自动续期重试一次，返回信封 data 字段
/** 与 platformRequest 同语义（带登录态、失败单次续期），但返回整包（含 cookie）供网关复签用 */
export async function platformRequestRaw(ctx: Context, path: string, method: http.RequestMethod,
  body: string | null): Promise<PlatformResponse> {
  let token: string = await getPlatformAccessToken(ctx);
  if (token.length === 0) {
    throw new Error(t($r('app.string.platform_err_login_first')));
  }
  let resp: PlatformResponse = await platformFetchRaw(path, method, body, token);
  if (resp.status >= 200 && resp.status < 300) {
    return resp;
  }
  const err: PlatformRequestError = responseError(resp.status, resp.body);
  if (!isInvalidSessionError(err as Error)) {
    throw err;
  }
  const next: PlatformSession | null = await refreshOnce(ctx);
  if (next === null) {
    throw err;
  }
  resp = await platformFetchRaw(path, method, body, next.accessToken);
  if (resp.status < 200 || resp.status >= 300) {
    throw responseError(resp.status, resp.body);
  }
  return resp;
}

export async function platformRequest(ctx: Context, path: string, method: http.RequestMethod,
  body: string | null): Promise<Object> {
  let token: string = await getPlatformAccessToken(ctx);
  if (token.length === 0) {
    throw new Error(t($r('app.string.platform_err_login_first')));
  }
  let resp: PlatformResponse = await platformFetchRaw(path, method, body, token);
  if (resp.status < 200 || resp.status >= 300) {
    const err: PlatformRequestError = responseError(resp.status, resp.body);
    if (!isInvalidSessionError(err as Error)) {
      throw err;
    }
    const next: PlatformSession | null = await refreshOnce(ctx);
    if (next === null) {
      throw err;
    }
    resp = await platformFetchRaw(path, method, body, next.accessToken);
    if (resp.status < 200 || resp.status >= 300) {
      throw responseError(resp.status, resp.body);
    }
  }
  if (resp.status === 204 || resp.body.length === 0) {
    return new Object();
  }
  const payload: Record<string, Object> = JSON.parse(resp.body) as Record<string, Object>;
  const data: Object = payload['data'];
  return data !== undefined && data !== null ? data : payload;
}

// 公开读（社区列表/详情/评论）：不带鉴权，直接取信封 data
export async function platformPublicRequest(path: string): Promise<Object> {
  const resp: PlatformResponse = await platformFetchRaw(path, http.RequestMethod.GET, null, '');
  if (resp.status < 200 || resp.status >= 300) {
    throw new Error(tf($r('app.string.platform_err_community'), resp.status));
  }
  const payload: Record<string, Object> = JSON.parse(resp.body) as Record<string, Object>;
  const data: Object = payload['data'];
  return data !== undefined && data !== null ? data : payload;
}
