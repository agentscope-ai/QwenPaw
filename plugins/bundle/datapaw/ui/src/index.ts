/**
 * DataPaw frontend plugin for QwenPaw (CloudPaw-style).
 *
 * - registerToolRender: fetch_data, create_plan
 * - sender.addPrefix: task graph panel above chat input
 * - SSE intercept on /console/chat: create_plan → GET /api/tasks → plan-store
 */

import { PLUGIN_ID } from "./lib/constants";
import { injectTaskGraphStyles } from "./task-graph/styles";
import { createFetchDataRender } from "./renders/fetch-data";
import { createCreatePlanRender } from "./renders/create-plan";
import { installFetchPatch } from "./patches/fetch-patch";
import { ensureDefaultAgent } from "./patches/ensure-agent";
import { patchWelcomeAndTheme } from "./patches/welcome-theme";
import {
  installChatBridge,
  scheduleCachedTaskCardRestore,
} from "./patches/task-card";
import { registerTaskCardSenderPrefix } from "./patches/task-card-sender-prefix";
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
    };
  }).QwenPaw;

  QP?.registerToolRender?.(PLUGIN_ID, {
    fetch_data: createFetchDataRender(bundle),
    create_plan: createCreatePlanRender(bundle),
  });

  installChatBridge();
  scheduleCachedTaskCardRestore();
  installFetchPatch();
  registerTaskCardSenderPrefix(bundle);
  ensureDefaultAgent();
  patchWelcomeAndTheme();

  console.info(
    `[${PLUGIN_ID}] Plugin UI registered (tool renders + sender prefix task card + SSE hook)`,
  );
}

buildPlugin();
