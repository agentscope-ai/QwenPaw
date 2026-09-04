const TOOL_DISPLAY_MODE_STORAGE_KEY = "qwenpaw_tool_display_mode";
const LEGACY_TOOL_EXPANDED_STORAGE_KEY = "qwenpaw_tool_calls_default_expanded";
const ASSISTANT_DISPLAY_MODE_STORAGE_KEY =
  "qwenpaw_assistant_message_display_mode";
const SHOW_THINKING_STORAGE_KEY = "qwenpaw_show_thinking";
const CHAT_DISPLAY_PREFERENCE_CHANGE_EVENT =
  "qwenpaw:chat-display-preference-change";
const CHAT_DISPLAY_STORAGE_KEYS = new Set([
  TOOL_DISPLAY_MODE_STORAGE_KEY,
  ASSISTANT_DISPLAY_MODE_STORAGE_KEY,
  SHOW_THINKING_STORAGE_KEY,
]);

export type AssistantMessageDisplayPreference =
  | "expanded"
  | "process-collapsed"
  | "result-collapsed";

export type ToolDisplayPreference = "current" | "raw-input-output";

export function subscribeChatDisplayPreference(
  onStoreChange: () => void,
): () => void {
  if (typeof window === "undefined") return () => {};
  const handleStorage = (event: StorageEvent) => {
    if (event.key === null || CHAT_DISPLAY_STORAGE_KEYS.has(event.key)) {
      onStoreChange();
    }
  };
  window.addEventListener(CHAT_DISPLAY_PREFERENCE_CHANGE_EVENT, onStoreChange);
  window.addEventListener("storage", handleStorage);
  return () => {
    window.removeEventListener(
      CHAT_DISPLAY_PREFERENCE_CHANGE_EVENT,
      onStoreChange,
    );
    window.removeEventListener("storage", handleStorage);
  };
}

function notifyChatDisplayPreferenceChange(): void {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event(CHAT_DISPLAY_PREFERENCE_CHANGE_EVENT));
  }
}

export function getShowThinkingPreference(): boolean {
  try {
    return localStorage.getItem(SHOW_THINKING_STORAGE_KEY) !== "false";
  } catch {
    return true;
  }
}

export function setShowThinkingPreference(show: boolean): void {
  try {
    if (show) {
      localStorage.removeItem(SHOW_THINKING_STORAGE_KEY);
    } else {
      localStorage.setItem(SHOW_THINKING_STORAGE_KEY, "false");
    }
  } catch {
    // storage unavailable
  }
  notifyChatDisplayPreferenceChange();
}

export function getToolDisplayPreference(): ToolDisplayPreference {
  try {
    return localStorage.getItem(TOOL_DISPLAY_MODE_STORAGE_KEY) ===
      "raw-input-output"
      ? "raw-input-output"
      : "current";
  } catch {
    return "current";
  }
}

export function setToolDisplayPreference(mode: ToolDisplayPreference): void {
  try {
    localStorage.removeItem(LEGACY_TOOL_EXPANDED_STORAGE_KEY);
    if (mode === "raw-input-output") {
      localStorage.setItem(TOOL_DISPLAY_MODE_STORAGE_KEY, mode);
    } else {
      localStorage.removeItem(TOOL_DISPLAY_MODE_STORAGE_KEY);
    }
  } catch {
    // storage unavailable
  }
  notifyChatDisplayPreferenceChange();
}

export function getAssistantMessageDisplayPreference(): AssistantMessageDisplayPreference {
  try {
    const stored = localStorage.getItem(ASSISTANT_DISPLAY_MODE_STORAGE_KEY);
    if (stored === "expanded" || stored === "process-collapsed") {
      return stored;
    }
  } catch {
    // storage unavailable
  }
  return "result-collapsed";
}

export function getMessageDisplayPreferenceSnapshot(): string {
  return `${getShowThinkingPreference()}:${getAssistantMessageDisplayPreference()}`;
}

export function setAssistantMessageDisplayPreference(
  mode: AssistantMessageDisplayPreference,
): void {
  try {
    if (mode === "result-collapsed") {
      localStorage.removeItem(ASSISTANT_DISPLAY_MODE_STORAGE_KEY);
    } else {
      localStorage.setItem(ASSISTANT_DISPLAY_MODE_STORAGE_KEY, mode);
    }
  } catch {
    // storage unavailable
  }
  notifyChatDisplayPreferenceChange();
}
