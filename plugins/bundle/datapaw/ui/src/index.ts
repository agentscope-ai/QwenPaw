/**
 * DataPaw frontend plugin for QwenPaw (CloudPaw-style).
 *
 * - registerToolRender: fetch_data
 * - chat cards.task_graph: persistent task plan row in the message stream
 * - SSE intercept on /console/chat: create_plan → GET /api/tasks → plan-store
 */

import { PLUGIN_ID } from "./lib/constants";
import { injectTaskGraphStyles } from "./task-graph/styles";
import { createFetchDataRender } from "./renders/fetch-data";
import { createTaskGraphCard } from "./task-graph/card";
import { installFetchPatch } from "./patches/fetch-patch";
import { ensureDefaultAgent } from "./patches/ensure-agent";
import { patchWelcomeAndTheme } from "./patches/welcome-theme";
import {
  installChatBridge,
  scheduleSessionTaskPlanSync,
} from "./patches/task-card";
import { patchHostSessionApi } from "./patches/session-api";
import { installConsoleLogoPatch } from "./patches/console-logo";
import { registerChatArtifactsButton } from "./patches/chat-artifacts-button";
import { registerDatapawNavigation } from "./patches/datapaw-navigation";
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
    };
  }).QwenPaw;

  QP?.registerToolRender?.(PLUGIN_ID, {
    fetch_data: createFetchDataRender(bundle),
  });

  const TaskGraphCard = createTaskGraphCard(bundle);
  QP?.registerCardRender?.(PLUGIN_ID, {
    task_graph: TaskGraphCard,
  });

  if (!patchHostSessionApi()) {
    let attempts = 0;
    const timer = window.setInterval(() => {
      attempts += 1;
      if (patchHostSessionApi() || attempts >= 50) {
        window.clearInterval(timer);
      }
    }, 200);
  }
  installChatBridge();
  scheduleSessionTaskPlanSync();
  registerDatapawNavigation(bundle);
  registerChatArtifactsButton(bundle);
  installConsoleLogoPatch(bundle);
  installFetchPatch();
  ensureDefaultAgent();
  patchWelcomeAndTheme();

  console.info(
    `[${PLUGIN_ID}] Plugin UI registered (task_graph card + SSE hook)`,
  );
}

buildPlugin();
