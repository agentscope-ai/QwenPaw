/**
 * hostSdk/hooks.ts — React hooks exposed on `window.QwenPaw.host.*`.
 *
 * These are thin wrappers over existing host contexts. Plugin components
 * call them while rendering INSIDE the host React tree, so all underlying
 * providers (Theme, i18n, agent store, chat session context) are guaranteed
 * to be mounted.
 */
import { useTranslation } from "react-i18next";
import { useChatAnywhereSessionsState } from "@agentscope-ai/chat";
import { useTheme as useThemeCtx } from "../../contexts/ThemeContext";
import { useAgentStore } from "../../stores/agentStore";

export type HostThemeMode = "light" | "dark";

export interface HostAgentInfo {
  id: string;
}

export interface HostSessionInfo {
  id: string;
}

export function useHostTheme(): HostThemeMode {
  return useThemeCtx().isDark ? "dark" : "light";
}

export function useHostLocale(): string {
  return useTranslation().i18n.language;
}

export function useHostSelectedAgent(): HostAgentInfo {
  const id = useAgentStore((s) => s.selectedAgent) ?? "default";
  return { id };
}

export function useHostCurrentSession(): HostSessionInfo | null {
  const state = useChatAnywhereSessionsState();
  return state?.currentSessionId ? { id: state.currentSessionId } : null;
}

export function getSelectedAgentId(): string {
  return useAgentStore.getState().selectedAgent ?? "default";
}

export function getCurrentSessionId(): string | null {
  if (typeof window === "undefined") return null;
  return (
    (window as unknown as { currentSessionId?: string }).currentSessionId ??
    null
  );
}
