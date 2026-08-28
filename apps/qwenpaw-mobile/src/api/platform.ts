import * as Crypto from "expo-crypto";
import * as Device from "expo-device";
import * as WebBrowser from "expo-web-browser";
import { Platform } from "react-native";
import {
  startOAuthLoopback,
  stopOAuthLoopback,
  waitForOAuthCallback,
} from "qwenpaw-oauth-loopback";

import {
  base64Url,
  buildPlatformAuthorizeUrl,
  isPlatformOAuthAppCallback,
  isPlatformOAuthLoopbackCallback,
  parsePlatformOAuthCallback,
  PLATFORM_APP_CALLBACK_URL,
  PLATFORM_CLI_CLIENT_ID,
  resolveAndroidOAuthCallback,
  selectAndroidOAuthBrowserPackage,
  shouldUseEmbeddedAndroidOAuth,
} from "../features/platform/platformOAuth";
import { openEmbeddedPlatformOAuthSession } from "../features/platform/EmbeddedPlatformOAuth";
import {
  clearPlatformSession,
  loadPlatformSession,
  type PlatformSession,
  savePlatformSession,
} from "../storage/platformSession";
import {
  isInvalidPlatformSessionError,
  parseRetryAfter,
  PlatformRequestError,
} from "./platformError";
import {
  platformRefreshModes,
  platformRefreshRequest,
  type PlatformRefreshMode,
} from "./platformSessionModel";
import { colors } from "../theme/tokens";

export const PLATFORM_BASE_URL = "https://platform.agentscope.io";
const REFRESH_EARLY_SECONDS = 300;

export class PlatformOAuthCancelledError extends Error {
  constructor() {
    super("已取消 GitHub 登录");
    this.name = "PlatformOAuthCancelledError";
  }
}

export function isPlatformOAuthCancelledError(
  value: unknown,
): value is PlatformOAuthCancelledError {
  return value instanceof PlatformOAuthCancelledError;
}

interface JsonObject {
  [key: string]: unknown;
}

let refreshPromise: Promise<PlatformSession | null> | null = null;

export async function loginAgentScopePlatform(
  account: string,
  password: string,
): Promise<PlatformSession> {
  const response = await fetch(`${PLATFORM_BASE_URL}/api/v1/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ account, password }),
  });
  if (!response.ok) throw await platformResponseError(response);
  const payload = (await response.json()) as JsonObject;
  const session = extractPlatformSession(payload, undefined, "web");
  await savePlatformSession(session);
  return session;
}

export async function loginAgentScopePlatformWithGitHub(): Promise<PlatformSession> {
  const verifier = base64Url(await randomBase64(48));
  const challenge = base64Url(
    await Crypto.digestStringAsync(
      Crypto.CryptoDigestAlgorithm.SHA256,
      verifier,
      { encoding: Crypto.CryptoEncoding.BASE64 },
    ),
  );
  const state = base64Url(await randomBase64(24));
  const port = await startOAuthLoopback();
  const redirectUri = `http://127.0.0.1:${port}/callback/qwenpaw-mobile`;
  const authorizeUrl = buildPlatformAuthorizeUrl({
    codeChallenge: challenge,
    redirectUri,
    state,
  });
  try {
    const callbackUrl =
      Platform.OS === "android"
        ? await openAndroidAuthSession(authorizeUrl, redirectUri)
        : await openAppleAuthSession(authorizeUrl);
    if (!callbackUrl) {
      throw new PlatformOAuthCancelledError();
    }
    const callbackIsValid =
      isPlatformOAuthLoopbackCallback(callbackUrl, redirectUri) ||
      isPlatformOAuthAppCallback(callbackUrl);
    if (!callbackIsValid) {
      throw new Error("Platform 登录回跳地址无效，请重新登录");
    }
    const code = parsePlatformOAuthCallback(callbackUrl, state);
    const response = await fetch(
      `${PLATFORM_BASE_URL}/api/cli/v1/oauth/token`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          grant_type: "authorization_code",
          client_id: PLATFORM_CLI_CLIENT_ID,
          code,
          redirect_uri: redirectUri,
          code_verifier: verifier,
        }),
      },
    );
    if (!response.ok) throw await platformResponseError(response);
    const payload = (await response.json()) as JsonObject;
    const initial = extractPlatformSession(payload, undefined, "cli");
    const session = await finalizeCliOAuthSession(initial);
    await savePlatformSession(session);
    return session;
  } finally {
    await stopOAuthLoopback().catch(() => undefined);
  }
}

async function openAndroidAuthSession(
  authorizeUrl: string,
  redirectUri: string,
): Promise<string | null> {
  if (shouldUseEmbeddedAndroidOAuth({
    brand: Device.brand,
    manufacturer: Device.manufacturer,
    sdkVersion: Number(Platform.Version),
  })) {
    return openEmbeddedPlatformOAuthSession(authorizeUrl, redirectUri);
  }
  const support = await WebBrowser.getCustomTabsSupportingBrowsersAsync()
    .catch(() => null);
  if (!support) {
    return openEmbeddedPlatformOAuthSession(authorizeUrl, redirectUri);
  }
  const browserPackage = selectAndroidOAuthBrowserPackage(support);
  if (!browserPackage) {
    return openEmbeddedPlatformOAuthSession(authorizeUrl, redirectUri);
  }
  const nativeCallback = waitForOAuthCallback();
  const browserCallback = WebBrowser.openAuthSessionAsync(
    authorizeUrl,
    PLATFORM_APP_CALLBACK_URL,
    {
      browserPackage,
      createTask: false,
      enableDefaultShareMenuItem: false,
      showTitle: true,
      toolbarColor: colors.accent,
    },
  ).then((result) =>
    result.type === "success" && "url" in result && result.url
      ? result.url
      : null,
  );
  return resolveAndroidOAuthCallback(nativeCallback, browserCallback);
}

async function openAppleAuthSession(
  authorizeUrl: string,
): Promise<string | null> {
  const result = await WebBrowser.openAuthSessionAsync(
    authorizeUrl,
    PLATFORM_APP_CALLBACK_URL,
    { preferEphemeralSession: false },
  );
  return result.type === "success" && "url" in result && result.url
    ? result.url
    : null;
}

export async function sendPlatformVerificationCode(
  account: string,
): Promise<void> {
  const response = await fetch(
    `${PLATFORM_BASE_URL}/api/v1/auth/send-verify-email-code`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ account, purpose: "register" }),
    },
  );
  if (!response.ok) throw await platformResponseError(response);
}

export async function registerAgentScopePlatform(
  account: string,
  password: string,
  verifyCode: string,
): Promise<void> {
  const response = await fetch(`${PLATFORM_BASE_URL}/api/v1/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ account, password, verifyCode }),
  });
  if (!response.ok) throw await platformResponseError(response);
}

export async function getPlatformAccessToken(): Promise<string | null> {
  const session = await loadPlatformSession();
  if (!session) return null;
  const now = Math.floor(Date.now() / 1000);
  if (session.expiresAt > now + REFRESH_EARLY_SECONDS) {
    return session.accessToken;
  }
  if (!refreshPromise) {
    refreshPromise = refreshPlatformSession(session).finally(() => {
      refreshPromise = null;
    });
  }
  return (await refreshPromise)?.accessToken ?? null;
}

export async function platformRequest<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  let token = await getPlatformAccessToken();
  if (!token) throw new Error("请先登录 AgentScope Platform");
  let response = await platformFetch(path, init, token);
  if (!response.ok) {
    const error = await platformResponseError(response);
    if (!isInvalidPlatformSessionError(error)) throw error;
    const refreshed = await forceRefreshPlatformSession();
    if (!refreshed) throw error;
    token = refreshed.accessToken;
    response = await platformFetch(path, init, token);
    if (!response.ok) throw await platformResponseError(response);
  }
  if (response.status === 204) return undefined as T;
  const payload = (await response.json()) as { data: T };
  return payload.data;
}

async function refreshPlatformSession(
  current: PlatformSession,
): Promise<PlatformSession | null> {
  try {
    const session = await requestPlatformSessionRefresh(current);
    await savePlatformSession(session);
    return session;
  } catch (error) {
    if (isInvalidPlatformSessionError(error)) {
      await clearPlatformSession();
      return null;
    }
    throw error;
  }
}

async function forceRefreshPlatformSession(): Promise<PlatformSession | null> {
  const session = await loadPlatformSession();
  if (!session) return null;
  if (!refreshPromise) {
    refreshPromise = refreshPlatformSession(session).finally(() => {
      refreshPromise = null;
    });
  }
  return refreshPromise;
}

async function requestPlatformSessionRefresh(
  current: PlatformSession,
): Promise<PlatformSession> {
  let lastError: Error | null = null;
  for (const mode of platformRefreshModes(current.refreshMode)) {
    const request = platformRefreshRequest(mode, current.refreshToken);
    const response = await fetch(`${PLATFORM_BASE_URL}${request.path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request.body),
    });
    if (response.ok) {
      const payload = (await response.json()) as JsonObject;
      return extractPlatformSession(payload, current.username, mode);
    }
    const error = await platformResponseError(response);
    lastError = error;
    if (current.refreshMode || !isInvalidPlatformSessionError(error)) {
      throw error;
    }
  }
  throw lastError ?? new Error("Platform 登录续期失败");
}

async function finalizeCliOAuthSession(
  initial: PlatformSession,
): Promise<PlatformSession> {
  try {
    return await requestPlatformSessionRefresh(initial);
  } catch {
    return initial;
  }
}

async function platformFetch(
  path: string,
  init: RequestInit,
  token: string,
): Promise<Response> {
  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${token}`);
  headers.set("Accept", "application/json");
  if (init.body && !(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  return fetch(`${PLATFORM_BASE_URL}${path}`, {
    ...init,
    headers,
    credentials: "include",
  });
}

function extractPlatformSession(
  payload: JsonObject,
  fallbackUsername?: string,
  refreshMode?: PlatformRefreshMode,
): PlatformSession {
  const first = objectValue(payload.data) ?? payload;
  const data = objectValue(first.data) ?? first;
  const user = objectValue(data.user);
  const accessToken = String(data.accessToken ?? data.access_token ?? "");
  const refreshToken = String(data.refreshToken ?? data.refresh_token ?? "");
  const expiresIn = Number(data.expiresIn ?? data.expires_in ?? 0);
  if (!accessToken || !refreshToken || !Number.isFinite(expiresIn)) {
    throw new Error("Platform 登录未返回有效凭据");
  }
  const now = Math.floor(Date.now() / 1000);
  return {
    accessToken,
    refreshToken,
    expiresAt: expiresIn > now ? expiresIn : now + expiresIn,
    refreshMode,
    username: String(user?.username ?? user?.name ?? fallbackUsername ?? ""),
  };
}

function objectValue(value: unknown): JsonObject | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as JsonObject)
    : null;
}

async function randomBase64(length: number): Promise<string> {
  const bytes = await Crypto.getRandomBytesAsync(length);
  let binary = "";
  for (const value of bytes) binary += String.fromCharCode(value);
  return btoa(binary);
}

async function platformResponseError(response: Response): Promise<Error> {
  let message = `Platform 请求失败（${response.status}）`;
  let code: string | undefined;
  try {
    const body = (await response.json()) as {
      code?: string;
      detail?: string;
      errorCode?: string;
      error?: {
        code?: string;
        detail?: string;
        hint?: string;
        message?: string;
      };
      message?: string;
    };
    message =
      body.error?.message ||
      body.error?.detail ||
      body.detail ||
      body.message ||
      message;
    code = body.error?.code || body.code || body.errorCode;
    if (code && !message.includes(code)) message = `${code}: ${message}`;
  } catch {
    // Preserve the HTTP status when the response is not JSON.
  }
  return new PlatformRequestError(message, {
    code,
    retryAfterMs: parseRetryAfter(response.headers.get("Retry-After")),
    status: response.status,
  });
}
