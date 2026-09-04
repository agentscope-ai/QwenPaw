const CHAT_WIDE_MODE_STORAGE_KEY = "qwenpaw_chat_wide_mode";
export const CHAT_WIDE_MODE_CHANGE_EVENT = "qwenpaw:chat-wide-mode-change";

export function getChatWideModePreference(): boolean {
  try {
    return localStorage.getItem(CHAT_WIDE_MODE_STORAGE_KEY) === "true";
  } catch {
    return false;
  }
}

export function setChatWideModePreference(enabled: boolean): void {
  try {
    if (enabled) {
      localStorage.setItem(CHAT_WIDE_MODE_STORAGE_KEY, "true");
    } else {
      localStorage.removeItem(CHAT_WIDE_MODE_STORAGE_KEY);
    }
  } catch {
    // storage unavailable
  }

  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event(CHAT_WIDE_MODE_CHANGE_EVENT));
  }
}
