/**
 * DataPaw frontend plugin for QwenPaw (CloudPaw-style).
 *
 * - registerToolRender: fetch_data
 * - response.render: wrap assistant response and append task graph under the latest response
 * - SSE intercept on /console/chat: create_plan → GET /api/tasks → plan-store
 */

import { PLUGIN_ID } from "./lib/constants";
import { injectTaskGraphStyles } from "./task-graph/styles";
import { createFetchDataRender } from "./renders/fetch-data";
import { createTaskGraphAppend } from "./renders/task-graph-append";
import { installFetchPatch } from "./patches/fetch-patch";
import { ensureDefaultAgent } from "./patches/ensure-agent";
import { patchWelcomeAndTheme } from "./patches/welcome-theme";
import { installChatBridge } from "./patches/task-card";
import type { HostBundle } from "./types";

function buildPlugin() {
  const host = (window as { QwenPaw?: { host?: HostBundle } }).QwenPaw?.host;
  if (!host?.React || !host?.antd) {
    console.warn(
      `[${PLUGIN_ID}] window.QwenPaw.host missing (React/antd) — plugin UI skipped`,
    );
    return;
  }

  injectTaskGraphStyles();

  const bundle: HostBundle = {
    React: host.React,
    antd: host.antd,
    getApiUrl: host.getApiUrl,
    getApiToken: host.getApiToken,
  };

  const QP = (window as {
    QwenPaw?: {
      registerToolRender?: (
        id: string,
        renders: Record<string, unknown>,
      ) => void;
      chat?: {
        response?: {
          render?: (
            pluginId: string,
            render: unknown,
          ) => unknown;
        };
      };
    };
  }).QwenPaw;

  QP?.registerToolRender?.(PLUGIN_ID, {
    fetch_data: createFetchDataRender(bundle),
  });

  if (QP?.chat?.response?.render) {
    QP.chat.response.render(PLUGIN_ID, createTaskGraphAppend(bundle));
    console.info("[datapaw:task-graph] response.render registered");
  } else {
    console.warn("[datapaw:task-graph] response.render unavailable");
  }

  installChatBridge();
  installFetchPatch();
  ensureDefaultAgent();
  patchWelcomeAndTheme();

  console.info(
    `[${PLUGIN_ID}] Plugin UI registered (tool renders + response.render + SSE hook)`,
  );
}

buildPlugin();
