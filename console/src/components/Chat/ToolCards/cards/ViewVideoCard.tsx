import React from "react";
import { useTranslation } from "react-i18next";
import { Video } from "lucide-react";
import type { ToolCallContent } from "../shared/types";
import { ToolCardShell, MediaPreview } from "../shared";
import { shortFileName, getMediaInfo } from "../shared/utils";

export interface ViewVideoCardProps {
  content: ToolCallContent;
  isStreaming?: boolean;
}

const ViewVideoCard: React.FC<ViewVideoCardProps> = ({
  content,
  isStreaming,
}) => {
  const { t } = useTranslation();
  const params = content.params || {};
  const videoPath = (params.video_path || "") as string;
  const file = shortFileName(videoPath);
  const title = file
    ? t("tool.viewVideo", { file })
    : t("tool.viewVideoDefault");

  const media = getMediaInfo(content);

  return (
    <ToolCardShell
      content={content}
      isStreaming={isStreaming}
      icon={<Video size={15} />}
      title={title}
      defaultExpanded={Boolean(media)}
    >
      {media && <MediaPreview media={media} />}
    </ToolCardShell>
  );
};

export default ViewVideoCard;
