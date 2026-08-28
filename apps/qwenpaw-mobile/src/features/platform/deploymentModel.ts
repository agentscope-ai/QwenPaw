import { isPlatformRateLimitError } from "../../api/platformError";

export interface PlatformDeploymentSummary {
  appId: string;
}

export interface PlatformDeployment {
  appId: string;
  status: string;
  accessUrl: string;
  versionType?: string;
}

export interface DeploymentStatusPresentation {
  label: string;
  detail: string;
  active: boolean;
  failed: boolean;
}

interface JsonObject {
  [key: string]: unknown;
}

export function parsePlatformDeployments(
  payload: unknown,
): PlatformDeploymentSummary[] {
  const value = unwrapPayload(payload);
  const object = objectValue(value);
  const entries = Array.isArray(value)
    ? value
    : object?.apps ?? object?.list ?? [];
  if (!Array.isArray(entries)) return [];
  return entries.flatMap((entry) => {
    const item = objectValue(entry);
    const appId = String(item?.appId ?? item?.id ?? "").trim();
    return appId ? [{ appId }] : [];
  });
}

export function parsePlatformDeployment(
  payload: unknown,
  fallbackAppId: string,
): PlatformDeployment {
  const value = objectValue(unwrapPayload(payload)) ?? {};
  return {
    appId: String(value.appId ?? value.id ?? fallbackAppId),
    status: String(value.status ?? "pending").toLowerCase(),
    accessUrl: String(value.accessUrl ?? value.access_url ?? "")
      .replace(/\/$/, ""),
    versionType: stringValue(value.versionType ?? value.version_type),
  };
}

export function parseCreatedDeploymentId(payload: unknown): string {
  const value = objectValue(unwrapPayload(payload)) ?? {};
  return String(value.appId ?? value.id ?? "").trim();
}

export function parsePlatformDeploymentLogs(payload: unknown): string[] {
  const value = unwrapPayload(payload);
  const object = objectValue(value);
  const entries = Array.isArray(value) ? value : object?.logs;
  if (!Array.isArray(entries)) return [];
  return entries.flatMap((entry) => {
    if (typeof entry === "string" && entry.trim()) return [entry.trim()];
    const item = objectValue(entry);
    const message = stringValue(item?.message ?? item?.log ?? item?.content);
    if (!message) return [];
    const level = stringValue(item?.level ?? item?.source);
    return [level ? `[${level.toUpperCase()}] ${message}` : message];
  });
}

export function deploymentStatusPresentation(
  status: string,
): DeploymentStatusPresentation {
  switch (status.toLowerCase()) {
    case "idle":
      return statusValue(
        "尚未部署",
        "登录已经完成，可以直接创建你的云端 QwenPaw。",
        false,
      );
    case "creating":
      return statusValue("正在创建", "正在为你准备云端 QwenPaw。", true);
    case "pending":
    case "deploying":
      return statusValue("正在部署", "正在装载服务与持久化配置。", true);
    case "rate_limited":
      return statusValue(
        "部署进行中",
        "Platform 正在处理请求，App 会自动重试，无需操作。",
        true,
      );
    case "starting":
      return statusValue("正在启动", "QwenPaw 服务即将就绪。", true);
    case "waking_up":
    case "sleeping":
      return statusValue("正在唤醒", "正在恢复你的云端 QwenPaw。", true);
    case "stopped":
      return statusValue("正在恢复", "已提交 QwenPaw 启动请求。", true);
    case "running":
      return statusValue("QwenPaw 已就绪", "正在完成安全配对。", false);
    case "failed":
      return statusValue("部署失败", "可以保留登录态并重新部署。", false, true);
    case "deleted":
      return statusValue("部署已移除", "可以重新创建你的 QwenPaw。", false, true);
    default:
      return statusValue("正在准备", "正在读取 Platform 部署状态。", true);
  }
}

export function isGitHubBindingError(error: unknown): boolean {
  const message = errorText(error).toLowerCase();
  return message.includes("asp.auth.github_bind_required") ||
    (message.includes("github") && message.includes("bind"));
}

export function platformDeploymentErrorMessage(error: unknown): string {
  const message = errorText(error);
  const normalized = message.toLowerCase();
  if (isPlatformRateLimitError(error)) {
    return "Platform 请求较多，登录态已保留；App 会暂停请求并自动重试。";
  }
  if (isGitHubBindingError(error)) {
    return "部署前需要先为 Platform 账号绑定 GitHub。绑定后返回这里重试即可。";
  }
  if (normalized.includes("qualification")) {
    return "当前 Platform 账号暂不具备 QwenPaw 部署资格，请先在 Platform 完成资格申请。";
  }
  if (normalized.includes("violation")) {
    return "当前 Platform 账号的部署权限受限，请前往 Platform 查看或提交申诉。";
  }
  if (normalized.includes("application_pending") ||
      normalized.includes("appeal_pending")) {
    return "Platform 正在审核你的申请，审核完成后可直接在这里继续部署。";
  }
  return message || "Platform 部署请求失败，请稍后重试。";
}

function statusValue(
  label: string,
  detail: string,
  active: boolean,
  failed = false,
): DeploymentStatusPresentation {
  return { label, detail, active, failed };
}

function unwrapPayload(payload: unknown): unknown {
  let value = payload;
  for (let depth = 0; depth < 2; depth += 1) {
    const object = objectValue(value);
    if (!object || !("data" in object)) break;
    value = object.data;
  }
  return value;
}

function objectValue(value: unknown): JsonObject | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as JsonObject
    : null;
}

function stringValue(value: unknown): string | undefined {
  if (typeof value !== "string") return undefined;
  const normalized = value.trim();
  return normalized || undefined;
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error ?? "");
}
