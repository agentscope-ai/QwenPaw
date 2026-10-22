import { invoke } from "@tauri-apps/api/core";

export type CloseAction = "minimize-to-tray" | "quit" | "stop-service";

export function setRememberedCloseAction(
  action: CloseAction | null,
): Promise<void> {
  return invoke("set_close_action", { action });
}

export function getRememberedCloseAction(): Promise<CloseAction | null> {
  return invoke("get_close_action");
}

export function clearRememberedCloseAction(): Promise<void> {
  return setRememberedCloseAction(null);
}
