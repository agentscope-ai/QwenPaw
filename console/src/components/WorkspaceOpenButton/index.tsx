import { invoke } from "@tauri-apps/api/core";
import { Button, Tooltip } from "antd";
import { FolderOpen } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useAppMessage } from "../../hooks/useAppMessage";
import { useAgentStore } from "../../stores/agentStore";
import { isDesktopTauriRuntime } from "../../utils/openExternalLink";

interface WorkspaceOpenButtonProps {
  className?: string;
}

export default function WorkspaceOpenButton(props: WorkspaceOpenButtonProps) {
  const { className } = props;
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const { agents, selectedAgent } = useAgentStore();
  const [opening, setOpening] = useState(false);
  const workspacePath = agents.find((agent) => agent.id === selectedAgent)
    ?.workspace_dir;

  if (!isDesktopTauriRuntime()) {
    return null;
  }

  const handleOpenWorkspace = async () => {
    if (!workspacePath || opening) return;

    setOpening(true);
    try {
      await invoke("open_workspace_directory", { path: workspacePath });
    } catch (error) {
      console.warn("[workspace] failed to open workspace directory", error);
      message.error(t("common.operationFailed"));
    } finally {
      setOpening(false);
    }
  };

  const label = t("nav.workspace");
  return (
    <Tooltip title={label} placement="top">
      <Button
        type="text"
        aria-label={label}
        className={className}
        icon={<FolderOpen size={18} />}
        loading={opening}
        disabled={!workspacePath}
        onClick={() => void handleOpenWorkspace()}
      />
    </Tooltip>
  );
}
