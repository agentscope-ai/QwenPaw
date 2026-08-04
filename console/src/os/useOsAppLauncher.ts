import { useCallback } from "react";
import { App } from "antd";
import { useTranslation } from "react-i18next";
import { codingModeApi } from "../api/modules/codingMode";
import { useAgentStore } from "../stores/agentStore";
import { useCodingModeStore } from "../stores/codingModeStore";
import { useOsRoute } from "./osRouteStore";
import { useOsWindows } from "./osWindowStore";

const MODE_TARGETS = {
  "core.chat": {
    enabled: false,
    path: "/chat",
    oppositeRouteId: "core.coding",
  },
  "core.coding": {
    enabled: true,
    path: "/coding",
    oppositeRouteId: "core.chat",
  },
} as const;

let modeLaunchPromise: Promise<boolean> | null = null;

/** Open a desktop app, applying Chat/Coding backend mode before navigation. */
export function useOsAppLauncher(): (routeId: string) => Promise<boolean> {
  const { message } = App.useApp();
  const { t } = useTranslation();

  return useCallback(
    async (routeId: string) => {
      const target = MODE_TARGETS[routeId as keyof typeof MODE_TARGETS];
      if (!target) {
        useOsWindows.getState().open(routeId);
        return true;
      }

      if (modeLaunchPromise) return modeLaunchPromise;

      const launchPromise = (async () => {
        const agentId = useAgentStore.getState().selectedAgent;
        const codingState = useCodingModeStore.getState();
        const currentMode = codingState.codingModeByAgent[agentId];

        try {
          if (currentMode !== target.enabled) {
            await codingModeApi.toggle(target.enabled);
            codingState.setCodingMode(agentId, target.enabled);
          }
          useOsRoute
            .getState()
            .navigateTo(routeId, target.path, target.oppositeRouteId);
          return true;
        } catch (error) {
          message.error(
            error instanceof Error
              ? error.message
              : t("os.codingModeLaunchFailed", "Failed to switch mode"),
          );
          return false;
        }
      })();
      modeLaunchPromise = launchPromise;

      try {
        return await launchPromise;
      } finally {
        if (modeLaunchPromise === launchPromise) {
          modeLaunchPromise = null;
        }
      }
    },
    [message, t],
  );
}
