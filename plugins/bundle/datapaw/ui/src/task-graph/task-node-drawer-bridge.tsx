/**
 * Reuse the existing TaskNodeDrawer from datapaw frontend (no reimplementation).
 */
import TaskNodeDrawer from "@/pages/Chat/components/TaskGraphPanel/TaskNodeDrawer";
import { PluginI18nProvider } from "@/host-chat/plugin-i18n";
import type {
  FileItem,
  StreamEvent,
  TaskNode,
} from "@/pages/Chat/components/TaskGraphPanel/types";
import type { HostBundle } from "../types";
import { toPlainJson } from "../lib/plain";

export interface TaskNodeDrawerBridgeProps {
  node: TaskNode | null;
  allFiles?: (FileItem & { _nodeName?: string })[];
  isStreaming?: boolean;
  streamEvents?: StreamEvent[];
  sessionId: string;
  userId: string;
  onClose: () => void;
  showFollowTab?: boolean;
}

export function createTaskNodeDrawerBridge(host: HostBundle) {
  const { React } = host;

  return function TaskNodeDrawerBridge({
    node,
    allFiles = [],
    isStreaming = false,
    streamEvents = [],
    sessionId,
    userId,
    onClose,
    showFollowTab,
  }: TaskNodeDrawerBridgeProps) {
    if (!node) return null;

    const plainNode = toPlainJson(node);
    const plainFiles = toPlainJson(allFiles);
    const plainEvents = toPlainJson(streamEvents);

    return React.createElement(
      PluginI18nProvider,
      null,
      React.createElement(TaskNodeDrawer, {
        node: plainNode,
        allFiles: plainFiles,
        isStreaming,
        streamEvents: plainEvents,
        sessionId,
        userId,
        onClose,
        showFollowTab,
      }),
    );
  };
}
