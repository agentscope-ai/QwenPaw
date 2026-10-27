const TOOL_DISPLAY_MODE_STORAGE_KEY = "qwenpaw_tool_display_mode";
const LEGACY_TOOL_EXPANDED_STORAGE_KEY = "qwenpaw_tool_calls_default_expanded";
const ASSISTANT_DISPLAY_MODE_STORAGE_KEY =
  "qwenpaw_assistant_message_display_mode";
const SHOW_THINKING_STORAGE_KEY = "qwenpaw_show_thinking";
const CHAT_DISPLAY_PREFERENCE_CHANGE_EVENT =
  "qwenpaw:chat-display-preference-change";

export type AssistantMessageDisplayPreference =
  | "expanded"
  | "process-collapsed"
  | "result-collapsed";

export type ToolDisplayPreference = "current" | "raw-input-output";

type AssistantDisplayServerDefault = AssistantMessageDisplayPreference | null;

/**
 * Server-provided fallback for the assistant message display mode.
 * An explicit per-browser choice in localStorage always wins; this value
 * only applies when the browser has never stored a choice.
 */
let assistantDisplayServerDefault: AssistantDisplayServerDefault = null;

export function subscribeChatDisplayPreference(
  onStoreChange: () => void,
): () => void {
  if (typeof window === "undefined") return () => {};
  window.addEventListener(CHAT_DISPLAY_PREFERENCE_CHANGE_EVENT, onStoreChange);
  return () => {
    window.removeEventListener(
      CHAT_DISPLAY_PREFERENCE_CHANGE_EVENT,
      onStoreChange,
    );
  };
}

function notifyChatDisplayPreferenceChange(): void {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event(CHAT_DISPLAY_PREFERENCE_CHANGE_EVENT));
  }
}

function isAssistantMessageDisplayPreference(
  value: unknown,
): value is AssistantMessageDisplayPreference {
  return (
    value === "expanded" ||
    value === "process-collapsed" ||
    value === "result-collapsed"
  );
}

/**
 * Apply the server-provided default for the assistant message display
 * mode. Pass null to clear it (e.g. on fetch failure). An explicit
 * per-browser choice in localStorage always wins over this default.
 */
export function setAssistantMessageDisplayServerDefault(
  mode: AssistantMessageDisplayPreference | null | undefined,
): void {
  assistantDisplayServerDefault = isAssistantMessageDisplayPreference(mode)
    ? mode
    : null;
  notifyChatDisplayPreferenceChange();
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
    if (isAssistantMessageDisplayPreference(stored)) {
      return stored;
    }
  } catch {
    // storage unavailable
  }
  if (
    assistantDisplayServerDefault === "expanded" ||
    assistantDisplayServerDefault === "process-collapsed"
  ) {
    return assistantDisplayServerDefault;
  }
  return "result-collapsed";
}

export function setAssistantMessageDisplayPreference(
  mode: AssistantMessageDisplayPreference,
): void {
  try {
    // Store every mode explicitly (including the built-in default) so a
    // per-browser choice stays expressible when a server default exists.
    localStorage.setItem(ASSISTANT_DISPLAY_MODE_STORAGE_KEY, mode);
  } catch {
    // storage unavailable
  }
  notifyChatDisplayPreferenceChange();
}
