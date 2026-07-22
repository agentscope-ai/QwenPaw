export const CLOSE_ACTION_STORAGE_KEY = "qwenpaw.closeWindowAction";

export type CloseAction = "minimize-to-tray" | "quit";

export function getRememberedCloseAction(): CloseAction | null {
  const action = getStorage()?.getItem(CLOSE_ACTION_STORAGE_KEY);
  return action === "minimize-to-tray" || action === "quit" ? action : null;
}

export function setRememberedCloseAction(action: CloseAction) {
  getStorage()?.setItem(CLOSE_ACTION_STORAGE_KEY, action);
}

export function clearRememberedCloseAction() {
  getStorage()?.removeItem(CLOSE_ACTION_STORAGE_KEY);
}

function getStorage(): Storage | null {
  return typeof window === "undefined" ? null : window.localStorage;
}
