/**
 * DataPaw frontend plugin for QwenPaw (CloudPaw-style).
 *
 * - registerToolRender: fetch_data
 * - response.append: append task graph between assistant response content and actions
 * - SSE intercept on /console/chat: create_plan → GET /api/tasks → plan-store
 */

import { PLUGIN_ID } from "./lib/constants";
import { injectTaskGraphStyles } from "./task-graph/styles";
import { createFetchDataRender } from "./renders/fetch-data";
import { createTaskGraphAppend } from "./renders/task-graph-append";
import { installFetchPatch } from "./patches/fetch-patch";
import { ensureDefaultAgent } from "./patches/ensure-agent";
import { patchWelcomeAndTheme } from "./patches/welcome-theme";
import {
  installChatBridge,
  scheduleSessionTaskPlanSync,
  resyncTaskCardFromPlanStore,
} from "./patches/task-card";
import {
  patchHostSessionApi,
  setSessionApiPatchedListener,
} from "./patches/session-api";
import { installConsoleLogoPatch } from "./patches/console-logo";
import { registerChatArtifactsButton } from "./patches/chat-artifacts-button";
import { registerChatSenderToolbar } from "./patches/chat-sender-toolbar";
import { registerDatapawNavigation } from "./patches/datapaw-navigation";
import { installDatapawFaviconPatch } from "./patches/favicon";
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
      registerCardRender?: (
        id: string,
        renders: Record<string, unknown>,
      ) => void;
      chat?: {
        response?: {
          append?: (
            pluginId: string,
            render: unknown,
          ) => unknown;
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

  if (QP?.chat?.response?.append) {
    QP.chat.response.append(PLUGIN_ID, createTaskGraphAppend(bundle));
  } else if (QP?.chat?.response?.render) {
    QP.chat.response.render(PLUGIN_ID, createTaskGraphAppend(bundle));
  } else {
    console.warn("[datapaw:task-graph] response append/render unavailable");
  }

  setSessionApiPatchedListener(() => {
    resyncTaskCardFromPlanStore();
  });

  if (!patchHostSessionApi()) {
    let attempts = 0;
    const timer = window.setInterval(() => {
      attempts += 1;
      if (patchHostSessionApi() || attempts >= 50) {
        window.clearInterval(timer);
        if (attempts < 50) resyncTaskCardFromPlanStore();
      }
    }, 200);
  } else {
    resyncTaskCardFromPlanStore();
  }
  installChatBridge();
  scheduleSessionTaskPlanSync();
  registerDatapawNavigation(bundle);
  registerChatArtifactsButton(bundle);
  registerChatSenderToolbar(bundle);
  installConsoleLogoPatch(bundle);
  installDatapawFaviconPatch();
  installFetchPatch();
  ensureDefaultAgent();
  patchWelcomeAndTheme();

  console.info(
    `[${PLUGIN_ID}] Plugin UI registered (response append + SSE hook)`,
  );
}

buildPlugin();
