import "@/i18n";
import App from "@/App";
import React from "react";
import { DATAPAW_AGENT_ID, PLUGIN_ID } from "../lib/constants";
import { isDatapawAgentSelected } from "../lib/agent";
import type { HostBundle } from "../types";

const ROUTE_BASE = "/plugin/datapaw";
const DATA_CONNECTION_ROUTE_ID = "datapaw.data-connection";
const DATA_CONNECTION_ADD_ROUTE_ID = "datapaw.data-connection.add";
const DATAPAW_GROUP_ID = "datapaw.group";
const SEMANTIC_WEAVING_URL = "https://bailian.console.aliyun.com/";

function DataPawRoute() {
  return React.createElement(App);
}

function datapawAgentVisible(): boolean {
  const hostSelectedAgent = (
    window as {
      QwenPaw?: { host?: { getSelectedAgentId?: () => string } };
    }
  ).QwenPaw?.host?.getSelectedAgentId?.();
  if (hostSelectedAgent) return hostSelectedAgent === DATAPAW_AGENT_ID;
  return isDatapawAgentSelected();
}

export function registerDatapawNavigation(host: HostBundle): void {
  const QP = (
    window as {
      QwenPaw?: {
        route?: {
          add?: (
            pluginId: string,
            route:
              | { id: string; path: string; component: unknown }
              | Array<{ id: string; path: string; component: unknown }>,
          ) => unknown;
        };
        menu?: {
          add?: (
            pluginId: string,
            item:
              | Record<string, unknown>
              | Array<Record<string, unknown>>,
          ) => unknown;
        };
        registerRoutes?: (
          pluginId: string,
          routes: Array<{
            path: string;
            component: unknown;
            label: string;
            icon?: string;
            priority?: number;
          }>,
        ) => void;
      };
    }
  ).QwenPaw;

  if (QP?.route?.add && QP?.menu?.add) {
    QP.route.add(PLUGIN_ID, [
      {
        id: DATA_CONNECTION_ROUTE_ID,
        path: `${ROUTE_BASE}/datapaw/data-connection`,
        component: DataPawRoute,
      },
      {
        id: DATA_CONNECTION_ADD_ROUTE_ID,
        path: `${ROUTE_BASE}/datapaw/data-connection/add`,
        component: DataPawRoute,
      },
    ]);

    QP.menu.add(PLUGIN_ID, [
      {
        id: DATAPAW_GROUP_ID,
        location: "primary.agentScoped",
        label: "DataPaw",
        isGroup: true,
        before: "core.control-group",
        order: 15,
        visible: datapawAgentVisible,
      },
      {
        id: "datapaw.data-connection.menu",
        location: "primary.agentScoped",
        parentId: DATAPAW_GROUP_ID,
        label: "Data Connection",
        icon: host.React.createElement(
          "span",
          { style: { fontSize: 16, lineHeight: 1 } },
          "⛓",
        ),
        route: DATA_CONNECTION_ROUTE_ID,
        order: 10,
        visible: datapawAgentVisible,
      },
      {
        id: "datapaw.semantic-weaving.menu",
        location: "primary.agentScoped",
        parentId: DATAPAW_GROUP_ID,
        label: "Semantic Weaving",
        icon: host.React.createElement(
          "span",
          { style: { fontSize: 16, lineHeight: 1 } },
          "◇",
        ),
        href: SEMANTIC_WEAVING_URL,
        order: 20,
        visible: datapawAgentVisible,
      },
    ]);

    console.info("[datapaw:navigation] registered DataPaw menu and routes");
    return;
  }

  QP?.registerRoutes?.(PLUGIN_ID, [
    {
      path: `${ROUTE_BASE}/*`,
      component: DataPawRoute,
      label: "DataPaw",
      icon: "🐾",
      priority: 50,
    },
  ]);
  console.warn(
    "[datapaw:navigation] menu API unavailable; registered legacy flat route only",
  );
}
