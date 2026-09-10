import type { HubRuntimeState } from "../../api/types";

const stateLabels: Record<HubRuntimeState, string> = {
  created: "等待启动",
  starting: "正在启动",
  running: "运行中",
  stopped: "已停止",
  failed: "异常",
};

export function hubRuntimeStateLabel(state: HubRuntimeState | null): string {
  return state ? stateLabels[state] : "尚未创建";
}

export function hubRuntimeStateTone(
  state: HubRuntimeState | null,
): "positive" | "accent" | "muted" | "danger" {
  if (state === "running") return "positive";
  if (state === "starting" || state === "created") return "accent";
  if (state === "failed") return "danger";
  return "muted";
}

export function hubRoleLabel(role: "admin" | "user"): string {
  return role === "admin" ? "管理员" : "成员";
}
