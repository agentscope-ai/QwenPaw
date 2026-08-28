import type { Connection } from "./types";
import { platformRequest } from "./platform";
import {
  inferPlatformAccessPath,
  isPlatformGatewayAuthResponse,
  platformAccessPath,
  platformConsoleBaseUrl,
} from "./platformGatewayModel";

const gatewayRefreshes = new Map<string, Promise<void>>();

export class PlatformGatewayError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "PlatformGatewayError";
  }
}

export async function ensurePlatformGateway(
  baseUrl: string,
  accessPath?: string,
): Promise<void> {
  const normalizedUrl = baseUrl.replace(/\/+$/, "");
  const resolvedAccessPath = accessPath ?? inferPlatformAccessPath(
    normalizedUrl,
  ) ?? undefined;
  if (!resolvedAccessPath) {
    throw new PlatformGatewayError(
      "Platform 配对信息不完整，请重新配对这只 QwenPaw。",
    );
  }
  const current = gatewayRefreshes.get(normalizedUrl);
  if (current) return current;

  const refresh = primePlatformGateway(normalizedUrl, resolvedAccessPath)
    .finally(() => gatewayRefreshes.delete(normalizedUrl));
  gatewayRefreshes.set(normalizedUrl, refresh);
  return refresh;
}

export async function requestWithPlatformGateway(
  baseUrl: string,
  source: Connection["source"],
  request: () => Promise<Response>,
  forceBeforeRequest = false,
  accessPath?: string,
): Promise<Response> {
  if (source !== "platform") return request();
  if (forceBeforeRequest) {
    await ensurePlatformGateway(baseUrl, accessPath);
  }
  let response = await request();
  if (!isGatewayResponse(response)) return response;

  await response.body?.cancel().catch(() => undefined);
  await ensurePlatformGateway(baseUrl, accessPath);
  response = await request();
  if (isGatewayResponse(response)) {
    await response.body?.cancel().catch(() => undefined);
    throw new PlatformGatewayError(
      "Platform 实例访问态恢复失败，请返回后重新进入。",
    );
  }
  return response;
}

export async function resolvePlatformQwenPawAccess(
  value: string,
): Promise<{ baseUrl: string; accessPath: string }> {
  const path = platformAccessPath(value);
  if (!path) {
    throw new PlatformGatewayError(
      "Platform 没有返回有效的 QwenPaw 配对入口，请稍后重试。",
    );
  }
  const payload = await platformRequest<unknown>(path);
  const baseUrl = platformConsoleBaseUrl(payload);
  if (!baseUrl) {
    throw new PlatformGatewayError(
      "Platform 没有返回可用的 QwenPaw 地址，请稍后重试。",
    );
  }
  return { baseUrl, accessPath: path };
}

function isGatewayResponse(response: Response): boolean {
  return isPlatformGatewayAuthResponse(
    response.status,
    response.headers.get("Content-Type"),
  );
}

async function primePlatformGateway(
  baseUrl: string,
  accessPath: string,
): Promise<void> {
  const payload = await platformRequest<unknown>(accessPath);
  const refreshedBaseUrl = platformConsoleBaseUrl(payload);
  if (!refreshedBaseUrl || refreshedBaseUrl !== baseUrl) {
    throw new PlatformGatewayError(
      "Platform 暂时无法恢复 QwenPaw 访问，请稍后重试。",
    );
  }
}
