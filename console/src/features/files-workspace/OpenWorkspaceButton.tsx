import { invoke } from "@tauri-apps/api/core";
import { Button } from "@agentscope-ai/design";
import { FolderOpen } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { useAppMessage } from "../../hooks/useAppMessage";
import { isDesktopTauriRuntime } from "../../utils/openExternalLink";

interface OpenWorkspaceButtonProps {
  agentId: string | null;
}

export function OpenWorkspaceButton({ agentId }: OpenWorkspaceButtonProps) {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [opening, setOpening] = useState(false);

  if (!isDesktopTauriRuntime()) {
    return null;
  }

  const handleOpen = async () => {
    if (!agentId || opening) return;

    setOpening(true);
    try {
      await invoke("open_workspace_directory", { agentId });
    } catch (error) {
      console.warn("[workspace] failed to open workspace directory", error);
      message.error(t("workspace.openFailed"));
    } finally {
      setOpening(false);
    }
  };

  return (
    <Button
      size="small"
      icon={<FolderOpen size={16} />}
      loading={opening || undefined}
      disabled={!agentId}
      onClick={() => void handleOpen()}
    >
      {t("workspace.openInFileManager")}
    </Button>
  );
}
