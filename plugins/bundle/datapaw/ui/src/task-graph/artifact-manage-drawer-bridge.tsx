/**
 * Reuse the existing ArtifactManageDrawer from datapaw frontend (no reimplementation).
 */
import ArtifactManageDrawer from "@/pages/Chat/components/TaskGraphPanel/ArtifactManageDrawer";
import { PluginI18nProvider } from "@/host-chat/plugin-i18n";
import type { HostBundle } from "../types";

export interface ArtifactManageDrawerBridgeProps {
  open: boolean;
  onClose: () => void;
  sessionId: string;
  userId: string;
  graphId?: string | null;
}

export function createArtifactManageDrawerBridge(host: HostBundle) {
  const { React } = host;

  return function ArtifactManageDrawerBridge({
    open,
    onClose,
    sessionId,
    userId,
    graphId,
  }: ArtifactManageDrawerBridgeProps) {
    if (!sessionId) return null;

    return React.createElement(
      PluginI18nProvider,
      null,
      React.createElement(ArtifactManageDrawer, {
        open,
        onClose,
        sessionId,
        userId,
        graphId,
      }),
    );
  };
}
