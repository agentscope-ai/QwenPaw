/**
 * DataPaw frontend plugin entry — registers with the QwenPaw host console.
 *
 * 1. `registerRoutes` — mounts the DataPaw console UI under `/plugin/datapaw/*`
 *    inside the host layout (no duplicate top header).
 * 2. `setupDataPawHostChat` — patches host `/chat` when the DataPaw agent is
 *    selected (task graph, fetch_data tool render, SSE hooks).
 */

import "../i18n";
import App from "../App";
import { setupDataPawHostChat } from "../host-chat/setup";
import { PLUGIN_ID, PLUGIN_ROUTE_BASE } from "./constants";

export function bootstrapDatapawPlugin(): void {
  const QP = window.QwenPaw;
  if (!QP?.host) {
    console.warn(
      `[${PLUGIN_ID}] window.QwenPaw.host missing — plugin bundle skipped`,
    );
    return;
  }

  QP.registerRoutes?.(PLUGIN_ID, [
    {
      path: `${PLUGIN_ROUTE_BASE}/*`,
      component: App,
      label: "DataPaw",
      icon: "🐾",
      priority: 50,
    },
  ]);

  setupDataPawHostChat();
}
