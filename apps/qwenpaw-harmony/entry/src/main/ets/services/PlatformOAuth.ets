/*
 * AgentScope Platform · GitHub OAuth（PKCE + 内嵌 ArkWeb 回跳拦截）—— 纯逻辑层
 *
 * 对齐 7378 `src/features/platform/platformOAuth.ts`（授权 URL / 回跳判定 / PKCE 编码）
 * 与 `src/api/platform.ts` 的 `loginAgentScopePlatformWithGitHub`（授权码 + code_verifier 换令牌）。
 * 流程：生成 PKCE（verifier + S256 challenge）与 state → 内嵌 Web 打开 `{Platform}/cli/login?...`
 *      → 回跳地址（环回地址 + 固定路径）在**加载前**被拦下 → 校验 state 取 code
 *      → `POST /api/cli/v1/oauth/token`（authorization_code + code_verifier）换取令牌。
 *
 * 回跳地址用环回地址（与 7378 同口径：CLI 客户端允许任意 127.0.0.1 端口），本端**不需要真的起
 * HTTP 服务** —— 官方 `onLoadIntercept` 的时机是「Web 组件加载 url 之前」，回跳这次导航在发起
 * 请求前就被拦下（见 FAQ faqs-arkweb-195）。
 *
 * 本文件不 import 会话层（避免与 services/PlatformSession.ets 形成循环依赖）：
 * 平台地址由调用方传入。
 */
import { util, url } from '@kit.ArkTS';
import { cryptoFramework } from '@kit.CryptoArchitectureKit';
import { t } from './I18n';

// 与 7378 同值：Platform CLI 客户端与 scope
export const OAUTH_CLIENT_ID: string = 'agentscope-platform-cli';
export const OAUTH_SCOPE: string = 'platform:control';

// 环回回跳（仅作为 redirect_uri 标识；不监听端口）
const OAUTH_LOOPBACK_HOST: string = '127.0.0.1';
const OAUTH_LOOPBACK_PORT: number = 53682;
const OAUTH_CALLBACK_PATH: string = '/callback/qwenpaw-mobile';

export enum OAuthNavigation {
  ALLOW = 'allow',
  CALLBACK = 'callback',
  DENY = 'deny'
}

export interface OAuthPkce {
  verifier: string;
  challenge: string;
  state: string;
}

export function oauthRedirectUri(): string {
  return `http://${OAUTH_LOOPBACK_HOST}:${OAUTH_LOOPBACK_PORT}${OAUTH_CALLBACK_PATH}`;
}

// 授权 URL（参数顺序与 7378 一致，便于对照排查）
export function buildAuthorizeUrl(platformBaseUrl: string, codeChallenge: string,
  redirectUri: string, state: string): string {
  const query: url.URLParams = new url.URLParams();
  query.append('client_id', OAUTH_CLIENT_ID);
  query.append('redirect_uri', redirectUri);
  query.append('response_type', 'code');
  query.append('state', state);
  query.append('code_challenge', codeChallenge);
  query.append('code_challenge_method', 'S256');
  query.append('scope', OAUTH_SCOPE);
  return `${platformBaseUrl}/cli/login?${query.toString()}`;
}

// PKCE：verifier = 48 字节随机数的 base64url；challenge = SHA256(verifier) 的 base64url
export function createOAuthPkce(): OAuthPkce {
  const verifier: string = base64Url(randomBytes(48));
  const pkce: OAuthPkce = {
    verifier: verifier,
    challenge: sha256Base64Url(verifier),
    state: base64Url(randomBytes(24))
  };
  return pkce;
}

// 回跳判定（对齐 7378 isPlatformOAuthLoopbackCallback）：协议/主机/端口/路径全等，且不带凭据与片段
export function isLoopbackCallback(value: string, expectedRedirectUri: string): boolean {
  try {
    const got: url.URL = new url.URL(value);
    const want: url.URL = new url.URL(expectedRedirectUri);
    return got.protocol === 'http:'
      && got.hostname === want.hostname
      && got.port === want.port
      && got.pathname === OAUTH_CALLBACK_PATH
      && got.pathname === want.pathname
      && got.username.length === 0
      && got.password.length === 0
      && got.hash.length === 0;
  } catch (e) {
    return false;
  }
}

// 导航放行判定（对齐 7378 classifyEmbeddedOAuthNavigation）：
// 回跳 → CALLBACK（拦下并结束）；https / about → ALLOW；其余 → DENY
export function classifyOAuthNavigation(value: string, expectedRedirectUri: string): OAuthNavigation {
  if (isLoopbackCallback(value, expectedRedirectUri)) {
    return OAuthNavigation.CALLBACK;
  }
  try {
    const parsed: url.URL = new url.URL(value);
    const protocol: string = parsed.protocol;
    return (protocol === 'https:' || protocol === 'about:') ? OAuthNavigation.ALLOW : OAuthNavigation.DENY;
  } catch (e) {
    return OAuthNavigation.DENY;
  }
}

// 回跳解析（对齐 7378 parsePlatformOAuthCallback）：先透出平台错误态，再校验 state，最后取 code
export function parseOAuthCallback(value: string, expectedState: string): string {
  const callback: url.URL = new url.URL(value);
  const failed: string | null = callback.params.get('error');
  if (failed !== null && failed.length > 0) {
    const detail: string | null = callback.params.get('error_description');
    throw new Error((detail !== null && detail.length > 0) ? detail : failed);
  }
  const state: string | null = callback.params.get('state');
  if (state === null || state !== expectedState) {
    throw new Error(t($r('app.string.platform_err_state_check')));
  }
  const code: string | null = callback.params.get('code');
  if (code === null || code.length === 0) {
    throw new Error(t($r('app.string.platform_err_no_code')));
  }
  return code;
}

// base64url（去 padding，+→-、/→_），与 7378 base64Url 同口径
function base64Url(bytes: Uint8Array): string {
  const raw: string = new util.Base64Helper().encodeToStringSync(bytes, util.Type.BASIC_URL_SAFE);
  let out: string = raw.split('+').join('-').split('/').join('_');
  while (out.length > 0 && out.charAt(out.length - 1) === '=') {
    out = out.substring(0, out.length - 1);
  }
  return out;
}

function randomBytes(len: number): Uint8Array {
  const random: cryptoFramework.Random = cryptoFramework.createRandom();
  return random.generateRandomSync(len).data;
}

function sha256Base64Url(text: string): string {
  const md: cryptoFramework.Md = cryptoFramework.createMd('SHA256');
  const input: cryptoFramework.DataBlob = { data: new util.TextEncoder().encodeInto(text) };
  md.updateSync(input);
  return base64Url(md.digestSync().data);
}
