import i18n from "@/i18n";
import React from "react";
import { DataPawRoute } from "../datapaw-route";
import { DATAPAW_AGENT_ID, PLUGIN_ID } from "../lib/constants";
import { isDatapawAgentSelected } from "../lib/agent";
import type { HostBundle } from "../types";

const ROUTE_BASE = "/plugin/datapaw";
const DATA_CONNECTION_ROUTE_ID = "datapaw.data-connection";
const DATA_CONNECTION_ADD_ROUTE_ID = "datapaw.data-connection.add";
const KG_DOCS_ROUTE_ID = "datapaw.kg-docs";
const DATAPAW_GROUP_ID = "datapaw.group";
const SEMANTIC_WEAVING_MENU_ID = "datapaw.semantic-weaving.menu";
const SEMANTIC_WEAVING_URL =
  "https://pre-datascope-config-backend.alibaba-inc.com/";
const DATA_CONNECTION_PATH = `${ROUTE_BASE}/datapaw/data-connection`;
const DATA_CONNECTION_ADD_PATH = `${ROUTE_BASE}/datapaw/data-connection/add`;
const KG_DOCS_PATH = `${ROUTE_BASE}/datapaw/kg-docs`;
const LANGUAGE_KEY = "language";

interface Disposable {
  dispose(): void;
}

type PluginMenuItem = Record<string, unknown> & { id: string };

function readConsoleLanguage(): string {
  try {
    return localStorage.getItem(LANGUAGE_KEY) || "en";
  } catch {
    return "en";
  }
}

function translateNav(key: string, fallback: string): string {
  return String(
    i18n.t(key, {
      lng: readConsoleLanguage(),
      defaultValue: fallback,
    }),
  );
}

function subscribeConsoleLanguage(fn: () => void): () => void {
  let last = readConsoleLanguage();
  const emitIfChanged = () => {
    const next = readConsoleLanguage();
    if (next === last) return;
    last = next;
    fn();
  };
  const onStorage = (event: StorageEvent) => {
    if (event.key === LANGUAGE_KEY) emitIfChanged();
  };

  window.addEventListener("storage", onStorage);
  const timer = window.setInterval(emitIfChanged, 500);

  return () => {
    window.removeEventListener("storage", onStorage);
    window.clearInterval(timer);
  };
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

function createMenuItems(host: HostBundle): PluginMenuItem[] {
  return [
    {
      id: DATAPAW_GROUP_ID,
      location: "primary.agentScoped",
      label: () => translateNav("nav.datapaw", "DataPaw"),
      isGroup: true,
      before: "core.control-group",
      order: 15,
      visible: datapawAgentVisible,
    },
    {
      id: DATA_CONNECTION_ROUTE_ID,
      location: "primary.agentScoped",
      parentId: DATAPAW_GROUP_ID,
      label: () => translateNav("nav.dataConnection", "Data Connection"),
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
      id: SEMANTIC_WEAVING_MENU_ID,
      location: "primary.agentScoped",
      parentId: DATAPAW_GROUP_ID,
      label: () => translateNav("nav.semanticWeaving", "Semantic Weaving"),
      icon: host.React.createElement(
        "span",
        { style: { fontSize: 16, lineHeight: 1 } },
        "◇",
      ),
      href: SEMANTIC_WEAVING_URL,
      order: 20,
      visible: datapawAgentVisible,
    },
    {
      id: KG_DOCS_ROUTE_ID,
      location: "primary.agentScoped",
      parentId: DATAPAW_GROUP_ID,
      label: () => translateNav("nav.kgDocs", "KG Document Management"),
      icon: host.React.createElement(
        "span",
        { style: { fontSize: 14, fontWeight: 700, lineHeight: 1 } },
        "KG",
      ),
      route: KG_DOCS_ROUTE_ID,
      order: 30,
      visible: datapawAgentVisible,
    },
  ];
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
            item: Record<string, unknown> | Array<Record<string, unknown>>,
          ) => Disposable | unknown;
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
        path: DATA_CONNECTION_PATH,
        component: DataPawRoute,
      },
      {
        id: DATA_CONNECTION_ADD_ROUTE_ID,
        path: DATA_CONNECTION_ADD_PATH,
        component: DataPawRoute,
      },
      {
        id: KG_DOCS_ROUTE_ID,
        path: KG_DOCS_PATH,
        component: DataPawRoute,
      },
    ]);

    let menuRegistration: Disposable | undefined;
    const registerMenu = () => {
      menuRegistration?.dispose();
      const disposable = QP.menu?.add?.(PLUGIN_ID, createMenuItems(host));
      menuRegistration =
        disposable && typeof (disposable as Disposable).dispose === "function"
          ? (disposable as Disposable)
          : undefined;
    };

    registerMenu();
    subscribeConsoleLanguage(registerMenu);
    return;
  }

  QP?.registerRoutes?.(PLUGIN_ID, [
    {
      path: `${ROUTE_BASE}/*`,
      component: DataPawRoute,
      label: translateNav("nav.datapaw", "DataPaw"),
      icon: "🐾",
      priority: 50,
    },
  ]);
  console.warn(
    "[datapaw:navigation] menu API unavailable; registered legacy flat route only",
  );
}
