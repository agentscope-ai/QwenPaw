import { platformRequest } from "../../api/platform";
import {
  parseCreatedDeploymentId,
  parsePlatformDeployment,
  parsePlatformDeploymentLogs,
  parsePlatformDeployments,
  type PlatformDeployment,
  type PlatformDeploymentSummary,
} from "./deploymentModel";

export async function listPlatformDeployments(): Promise<
  PlatformDeploymentSummary[]
> {
  const payload = await platformRequest<unknown>("/api/v1/app/list");
  return parsePlatformDeployments(payload);
}

export async function createPlatformQwenPaw(): Promise<string> {
  const payload = await platformRequest<unknown>("/api/v1/app/create", {
    method: "POST",
    body: JSON.stringify({ appType: "qwenpaw" }),
  });
  const appId = parseCreatedDeploymentId(payload);
  if (!appId) throw new Error("Platform 创建部署后没有返回 appId");
  return appId;
}

export async function getPlatformDeployment(
  appId: string,
): Promise<PlatformDeployment> {
  const payload = await platformRequest<unknown>(
    `/api/v1/app/get?appId=${encodeURIComponent(appId)}`,
  );
  return parsePlatformDeployment(payload, appId);
}

export async function getPlatformDeploymentLogs(
  appId: string,
): Promise<string[]> {
  const payload = await platformRequest<unknown>(
    `/api/v1/app/deploy-logs?appId=${encodeURIComponent(appId)}`,
  );
  return parsePlatformDeploymentLogs(payload);
}

export async function startPlatformDeployment(appId: string): Promise<void> {
  await platformRequest("/api/v1/app/start", {
    method: "POST",
    body: JSON.stringify({ appId }),
  });
}

export async function wakePlatformDeployment(appId: string): Promise<void> {
  await platformRequest("/api/v1/app/heartbeat", {
    method: "POST",
    body: JSON.stringify({ appId }),
  });
}

export async function resetPlatformQwenPawAuth(appId: string): Promise<void> {
  await platformRequest("/api/v1/app/reset-qwenpaw-auth", {
    method: "POST",
    body: JSON.stringify({ appId }),
  });
}

export async function restartPlatformDeployment(appId: string): Promise<void> {
  await platformRequest("/api/v1/app/restart", {
    method: "POST",
    body: JSON.stringify({ appId }),
  });
}
