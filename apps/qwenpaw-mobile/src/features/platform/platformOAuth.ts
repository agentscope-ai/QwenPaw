import { PLATFORM_BASE_URL } from "../../config/platform";

export const PLATFORM_CLI_CLIENT_ID = "agentscope-platform-cli";
export const PLATFORM_CLI_SCOPE = "platform:control";
export const PLATFORM_APP_CALLBACK_URL = "qwenpaw://platform-auth";
export const ANDROID_OAUTH_CALLBACK_GRACE_MS = 2_000;

export interface AndroidOAuthBrowserSupport {
  browserPackages: readonly string[];
  servicePackages: readonly string[];
  defaultBrowserPackage?: string;
  preferredBrowserPackage?: string;
}

export interface AndroidOAuthDevice {
  brand?: string | null;
  manufacturer?: string | null;
  sdkVersion: number;
}

export type EmbeddedOAuthNavigation = "allow" | "callback" | "deny";

const ANDROID_OAUTH_BROWSER_PRIORITY = [
  "com.android.chrome",
  "com.chrome.beta",
  "com.chrome.dev",
  "com.microsoft.emmx",
  "org.mozilla.firefox",
];

type OAuthCallbackSource = "browser" | "native";

interface OAuthCallbackResult {
  source: OAuthCallbackSource;
  url: string | null;
}

export function selectAndroidOAuthBrowserPackage(
  support: AndroidOAuthBrowserSupport,
): string | null {
  const providers = [...new Set(support.servicePackages)];
  if (
    support.defaultBrowserPackage &&
    providers.includes(support.defaultBrowserPackage)
  ) {
    return support.defaultBrowserPackage;
  }
  if (
    support.preferredBrowserPackage &&
    providers.includes(support.preferredBrowserPackage)
  ) {
    return support.preferredBrowserPackage;
  }
  return ANDROID_OAUTH_BROWSER_PRIORITY.find((packageName) =>
    providers.includes(packageName)
  ) ?? providers[0] ?? null;
}

export function shouldUseEmbeddedAndroidOAuth(
  device: AndroidOAuthDevice,
): boolean {
  if (device.sdkVersion < 24) return false;
  const vendor = `${device.brand ?? ""} ${device.manufacturer ?? ""}`
    .toLowerCase();
  return ["oneplus", "oppo", "realme"].some((name) => vendor.includes(name));
}

export function classifyEmbeddedOAuthNavigation(
  url: string,
  expectedRedirectUri: string,
): EmbeddedOAuthNavigation {
  if (isPlatformOAuthLoopbackCallback(url, expectedRedirectUri)) {
    return "callback";
  }
  try {
    const parsed = new URL(url);
    return parsed.protocol === "https:" || parsed.protocol === "about:"
      ? "allow"
      : "deny";
  } catch {
    return "deny";
  }
}

export function buildPlatformAuthorizeUrl({
  codeChallenge,
  redirectUri,
  state,
}: {
  codeChallenge: string;
  redirectUri: string;
  state: string;
}): string {
  const query = new URLSearchParams({
    client_id: PLATFORM_CLI_CLIENT_ID,
    redirect_uri: redirectUri,
    response_type: "code",
    state,
    code_challenge: codeChallenge,
    code_challenge_method: "S256",
    scope: PLATFORM_CLI_SCOPE,
  });
  return `${PLATFORM_BASE_URL}/cli/login?${query.toString()}`;
}

export function parsePlatformOAuthCallback(
  value: string,
  expectedState: string,
): string {
  const callback = new URL(value);
  const error = callback.searchParams.get("error");
  if (error) {
    throw new Error(callback.searchParams.get("error_description") || error);
  }
  const state = callback.searchParams.get("state");
  if (!state || state !== expectedState) {
    throw new Error("Platform 登录状态校验失败，请重新登录");
  }
  const code = callback.searchParams.get("code");
  if (!code) throw new Error("Platform 登录没有返回授权码");
  return code;
}

export function isPlatformOAuthAppCallback(value: string): boolean {
  try {
    const callback = new URL(value);
    return (
      callback.protocol === "qwenpaw:" &&
      callback.hostname === "platform-auth" &&
      (callback.pathname === "" || callback.pathname === "/")
    );
  } catch {
    return false;
  }
}

export function isPlatformOAuthLoopbackCallback(
  value: string,
  expectedRedirectUri: string,
): boolean {
  try {
    const callback = new URL(value);
    const expected = new URL(expectedRedirectUri);
    return (
      callback.protocol === "http:" &&
      callback.hostname === "127.0.0.1" &&
      callback.origin === expected.origin &&
      callback.pathname === "/callback/qwenpaw-mobile" &&
      callback.pathname === expected.pathname &&
      !callback.username &&
      !callback.password &&
      !callback.hash
    );
  } catch {
    return false;
  }
}

export function base64Url(value: string): string {
  return value.replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

export async function resolveAndroidOAuthCallback(
  nativeCallback: Promise<string | null>,
  browserCallback: Promise<string | null>,
  graceMs = ANDROID_OAUTH_CALLBACK_GRACE_MS,
): Promise<string | null> {
  const nativeResult = nativeCallback.then<OAuthCallbackResult>((url) => ({
    source: "native",
    url,
  }));
  const browserResult = browserCallback.then<OAuthCallbackResult>((url) => ({
    source: "browser",
    url,
  }));
  const first = await Promise.race([nativeResult, browserResult]);
  if (first.source === "native" || first.url) return first.url;
  return waitForCallbackGrace(nativeCallback, graceMs);
}

async function waitForCallbackGrace(
  callback: Promise<string | null>,
  graceMs: number,
): Promise<string | null> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    return await Promise.race([
      callback,
      new Promise<null>((resolve) => {
        timer = setTimeout(() => resolve(null), graceMs);
      }),
    ]);
  } finally {
    if (timer) clearTimeout(timer);
  }
}
