import { useRef } from "react";
import { useLocation } from "react-router-dom";
import { useAgentStore } from "@/stores/agentStore";
import type { SettingsSearchTarget } from "@/plugins/settingsSearch";
import { useSettingsSearchTarget } from "./useSettingsSearchTarget";

/** Locate plugin settings fields at their original registered URLs. */
export function SettingsSearchNavigation() {
  const location = useLocation();
  const selectedAgent = useAgentStore((state) => state.selectedAgent);
  const request = (
    location.state as {
      settingsSearchTarget?: SettingsSearchTarget;
    } | null
  )?.settingsSearchTarget;
  const body = useRef<HTMLElement>(document.body);
  const active =
    request &&
    request.agentId === selectedAgent &&
    request.page.startsWith("extension-")
      ? request
      : null;
  useSettingsSearchTarget(body, active, active?.page);
  return null;
}
