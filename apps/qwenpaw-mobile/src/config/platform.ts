export const DEFAULT_PLATFORM_BASE_URL = "https://platform.agentscope.io";

export function resolvePlatformBaseUrl(value?: string): string {
  if (!value?.trim()) return DEFAULT_PLATFORM_BASE_URL;
  try {
    const url = new URL(value.trim());
    const loopback = ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname);
    if (
      (url.protocol !== "https:" && !(url.protocol === "http:" && loopback)) ||
      url.username ||
      url.password ||
      url.pathname !== "/" ||
      url.search ||
      url.hash
    ) {
      return DEFAULT_PLATFORM_BASE_URL;
    }
    return url.origin;
  } catch {
    return DEFAULT_PLATFORM_BASE_URL;
  }
}

export const PLATFORM_BASE_URL = resolvePlatformBaseUrl(
  process.env.EXPO_PUBLIC_PLATFORM_BASE_URL,
);

export const PLATFORM_HOST = new URL(PLATFORM_BASE_URL).host;
