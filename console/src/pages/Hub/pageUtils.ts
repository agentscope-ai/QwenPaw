import type { HubRuntime } from "../../api/modules/hub";

export type Section =
  | "overview"
  | "runtimes"
  | "users"
  | "credentials"
  | "audit"
  | "settings";

export interface SettingsFormValues {
  publicBaseUrl?: string;
  registrationEnabled: boolean;
  runtimeProvisioner: "local" | "docker";
  dockerSource: "docker_hub" | "aliyun_acr" | "local" | "custom";
  dockerImage: string;
  dockerPullPolicy: "always" | "if_not_present" | "never";
  dockerCpuLimit?: number;
  dockerMemoryLimitMb?: number;
  dockerPidsLimit?: number;
  dockerShmSizeMb: number;
  maxRunningRuntimes?: number;
  ipBlacklist: string[];
  trustedProxyIps: string[];
  loginRateEnabled: boolean;
  loginMaxAttempts: number;
  loginWindowSeconds: number;
  loginBlockSeconds: number;
  registrationRateEnabled: boolean;
  registrationMaxAttempts: number;
  registrationWindowSeconds: number;
  registrationBlockSeconds: number;
}

export interface PageData<T> {
  items: T[];
  page: number;
  pageSize: number;
  total: number;
}

export const PAGE_SIZE = 20;

export const STATE_COLORS: Record<HubRuntime["state"], string> = {
  created: "default",
  starting: "processing",
  running: "success",
  stopped: "default",
  failed: "error",
};

export function emptyPage<T>(): PageData<T> {
  return { items: [], page: 1, pageSize: PAGE_SIZE, total: 0 };
}

export function dockerReferenceParts(reference: string) {
  const digestIndex = reference.indexOf("@");
  const withoutDigest =
    digestIndex >= 0 ? reference.slice(0, digestIndex) : reference;
  const lastSlash = withoutDigest.lastIndexOf("/");
  const tagIndex = withoutDigest.lastIndexOf(":");
  return {
    repository:
      tagIndex > lastSlash ? withoutDigest.slice(0, tagIndex) : withoutDigest,
    tag: tagIndex > lastSlash ? withoutDigest.slice(tagIndex + 1) : "latest",
  };
}

export function formatImageSize(size: number) {
  if (!size) return "—";
  const units = ["B", "KB", "MB", "GB"];
  let value = size;
  let index = 0;
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024;
    index += 1;
  }
  return `${value.toFixed(index > 1 ? 1 : 0)} ${units[index]}`;
}

export function formatDate(value: string, language?: string): string {
  return new Date(value).toLocaleString(language, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}
