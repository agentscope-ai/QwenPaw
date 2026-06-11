import { FolderOpenOutlined } from "@ant-design/icons";
import { isDatapawAgentSelected } from "../lib/agent";
import { getCurrentPlan, subscribeCurrentPlan } from "../lib/plan-store";
import { resolveBackendSessionId } from "../lib/session-id";
import { createArtifactManageDrawerBridge } from "../task-graph/artifact-manage-drawer-bridge";
import type { HostBundle } from "../types";

export function registerChatArtifactsButton(host: HostBundle): void {
  const QP = (
    window as {
      QwenPaw?: {
        chat?: {
          rightHeader?: {
            add?: (
              pluginId: string,
              node: unknown,
              opts?: { id?: string; order?: number },
            ) => unknown;
          };
        };
      };
    }
  ).QwenPaw;

  if (!QP?.chat?.rightHeader?.add) {
    console.warn("[datapaw:artifacts] chat.rightHeader.add unavailable");
    return;
  }

  const { React, antd } = host;
  const { Button, Tooltip } = antd;
  const { useMemo, useState, useSyncExternalStore } = React;
  const ArtifactManageDrawer = createArtifactManageDrawerBridge(host);

  function DataPawArtifactsButton() {
    const [open, setOpen] = useState(false);
    const plan = useSyncExternalStore(
      subscribeCurrentPlan,
      getCurrentPlan,
      () => null,
    );
    const sessionId = resolveBackendSessionId() || "";
    const userId =
      (window as Window & { currentUserId?: string }).currentUserId ||
      "default";
    const active = isDatapawAgentSelected();

    const button = useMemo(
      () =>
        React.createElement(
          Tooltip,
          { title: "Artifacts", mouseEnterDelay: 0.5 },
          React.createElement(Button, {
            type: "text",
            icon: React.createElement(FolderOpenOutlined),
            onClick: () => setOpen(true),
          }),
        ),
      [Tooltip, Button],
    );

    if (!active) return null;

    return React.createElement(
      React.Fragment,
      null,
      button,
      React.createElement(ArtifactManageDrawer, {
        open,
        onClose: () => setOpen(false),
        sessionId,
        userId,
        graphId: plan?.id,
      }),
    );
  }

  QP.chat.rightHeader.add(
    "datapaw",
    React.createElement(DataPawArtifactsButton),
    { id: "datapaw-artifacts", order: 45 },
  );
  console.info("[datapaw:artifacts] right header button registered");
}
