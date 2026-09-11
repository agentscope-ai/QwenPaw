import React from "react";
import { useTranslation } from "react-i18next";
import { Send } from "lucide-react";
import type { ToolCallContent } from "../shared/types";
import { ToolCardShell, MediaPreview } from "../shared";
import { shortFileName, getMediaInfo } from "../shared/utils";
import {
  filePathFromPreviewUrl,
  parseInternalFileLink,
} from "../../../../features/files-workspace/internalFileLinks";

export interface SendFileCardProps {
  content: ToolCallContent;
  isStreaming?: boolean;
}

const SendFileCard: React.FC<SendFileCardProps> = ({
  content,
  isStreaming,
}) => {
  const { t } = useTranslation();
  const params = content.params || {};
  const filePath = (params.file_path ||
    params.image_path ||
    params.video_path ||
    params.audio_path ||
    params.path ||
    "") as string;
  const file = shortFileName(filePath);
  const title = file ? t("tool.sendFile", { file }) : t("tool.sendFileDefault");

  if (content.status === "error") {
    return (
      <ToolCardShell
        content={content}
        isStreaming={isStreaming}
        icon={<Send size={15} />}
        title={title}
      />
    );
  }

  const media = getMediaInfo(content);
  const workspaceTarget = parseInternalFileLink(filePath);
  const target = media
    ? {
        source: "attachment" as const,
        path:
          filePathFromPreviewUrl(media.url) || filePath || media.name || file,
        artifactUrl: media.url,
      }
    : workspaceTarget;

  return (
    <ToolCardShell
      content={content}
      isStreaming={isStreaming}
      icon={<Send size={15} />}
      title={title}
      defaultExpanded={Boolean(media)}
    >
      {media && (
        <MediaPreview
          media={media}
          onFileOpen={
            target
              ? (trigger) => {
                  window.dispatchEvent(
                    new CustomEvent("qwenpaw:open-file-preview", {
                      detail: { target, trigger },
                    }),
                  );
                }
              : undefined
          }
        />
      )}
    </ToolCardShell>
  );
};

export default SendFileCard;
