import { useEffect, useRef, useState } from "react";
import { Alert } from "antd";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { request } from "@/api/request";
import { useAppMessage } from "@/hooks/useAppMessage";
import { subscribeToPluginChanges } from "@/utils/pluginChangeEvents";

const OFFICIAL_PLUGINS = "/market?tab=plugins&view=official";

/** Read-only recovery UI. Only the official page can initiate an online install. */
export function MCPFeatureStatus({
  agentId,
  active = true,
  refreshKey,
}: {
  agentId: string;
  active?: boolean;
  refreshKey?: unknown;
}) {
  const { t } = useTranslation();
  const { modal } = useAppMessage();
  const navigate = useNavigate();
  const [revision, setRevision] = useState(0);
  const [blocked, setBlocked] = useState(false);
  const lastFailure = useRef("");
  const title = t("mcpFeature.required");
  const description = t("mcpFeature.unavailable");
  const okText = t("mcpFeature.openOfficial");
  const cancelText = t("mcpFeature.later");

  useEffect(
    () => subscribeToPluginChanges(() => setRevision((n) => n + 1)),
    [],
  );
  useEffect(() => {
    if (!active) {
      setBlocked(false);
      return;
    }
    const controller = new AbortController();
    let dialog: { destroy: () => void } | undefined;
    setBlocked(false);
    request<{ available: boolean; status: string; diagnostics: string[] }>(
      "/mcp-plugin",
      {
        headers: { "X-Agent-Id": agentId },
        signal: controller.signal,
      },
    )
      .then((state) => {
        if (controller.signal.aborted) return;
        setBlocked(!state.available);
        if (state.available) {
          lastFailure.current = "";
          return;
        }
        const key = JSON.stringify([agentId, state.status, state.diagnostics]);
        if (lastFailure.current === key) return;
        lastFailure.current = key;
        dialog = modal.confirm({
          title,
          content: description,
          okText,
          cancelText,
          onOk: () => navigate(OFFICIAL_PLUGINS),
        });
      })
      .catch(() => {
        // A failed status request is not evidence that a plugin needs reinstalling.
      });
    return () => {
      controller.abort();
      dialog?.destroy();
    };
  }, [
    active,
    agentId,
    revision,
    refreshKey,
    modal,
    navigate,
    title,
    description,
    okText,
    cancelText,
  ]);

  return blocked ? (
    <Alert showIcon type="warning" message={description} />
  ) : null;
}
