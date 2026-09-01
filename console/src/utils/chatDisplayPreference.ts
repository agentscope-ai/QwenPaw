const TOOL_DISPLAY_MODE_STORAGE_KEY = "qwenpaw_tool_display_mode";
const LEGACY_TOOL_EXPANDED_STORAGE_KEY = "qwenpaw_tool_calls_default_expanded";
const ASSISTANT_DISPLAY_MODE_STORAGE_KEY =
  "qwenpaw_assistant_message_display_mode";

export type AssistantMessageDisplayPreference =
  | "expanded"
  | "process-collapsed"
  | "result-collapsed";

export type ToolDisplayPreference = "current" | "raw-input-output";

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
}
