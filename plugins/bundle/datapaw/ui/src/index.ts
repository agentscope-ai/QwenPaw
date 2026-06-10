/**
 * DataPaw frontend plugin for QwenPaw (CloudPaw-style).
 *
 * - registerToolRender: fetch_data, create_plan
 * - registerCardRender: task_graph (injected into chat message stream)
 * - SSE intercept on /console/chat: detect create_plan → confirm → GET /api/tasks
 */

import { PLUGIN_ID } from "./lib/constants";
import { injectTaskGraphStyles } from "./task-graph/styles";
import { createFetchDataRender } from "./renders/fetch-data";
import { createCreatePlanRender } from "./renders/create-plan";
import { createTaskGraphCard } from "./task-graph/card";
import { installFetchPatch } from "./patches/fetch-patch";
import { ensureDefaultAgent } from "./patches/ensure-agent";
import { patchWelcomeAndTheme } from "./patches/welcome-theme";
import { patchHostSessionApi } from "./patches/session-api";
import {
  installChatBridge,
  scheduleTaskCardRestore,
} from "./patches/task-card";
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
    create_plan: createCreatePlanRender(bundle),
  });

  const taskGraphCard = createTaskGraphCard(bundle);
  if (QP?.chat?.card) {
    QP.chat.card(PLUGIN_ID, "task_graph", taskGraphCard);
  } else {
    QP?.registerCardRender?.(PLUGIN_ID, {
      task_graph: taskGraphCard,
    });
  }

  installChatBridge();
  const startPersistence = () => {
    scheduleTaskCardRestore();
  };
  if (!patchHostSessionApi()) {
    let attempts = 0;
    const timer = window.setInterval(() => {
      attempts += 1;
      if (patchHostSessionApi()) {
        window.clearInterval(timer);
        startPersistence();
      } else if (attempts >= 100) {
        window.clearInterval(timer);
        startPersistence();
      }
    }, 50);
  } else {
    startPersistence();
  }
  installFetchPatch();
  ensureDefaultAgent();
  patchWelcomeAndTheme();

  console.info(
    `[${PLUGIN_ID}] Plugin UI registered (tool renders + task_graph card + SSE hook)`,
  );
}

buildPlugin();
