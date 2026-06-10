import React from "react";
import { useTranslation } from "react-i18next";
import { DesktopOutlined } from "@ant-design/icons";
import type { ToolCallContent } from "../shared/types";
import { ToolCardShell, MediaPreview } from "../shared";
import { getMediaInfo } from "../shared/utils";

export interface DesktopScreenshotCardProps {
  content: ToolCallContent;
  isStreaming?: boolean;
}

const DesktopScreenshotCard: React.FC<DesktopScreenshotCardProps> = ({
  content,
  isStreaming,
}) => {
  const { t } = useTranslation();
  const title = t("tool.desktopScreenshot");
  const media = getMediaInfo(content);

  return (
    <ToolCardShell
      content={content}
      isStreaming={isStreaming}
      icon={<DesktopOutlined />}
      title={title}
    >
      {media && <MediaPreview media={media} />}
    </ToolCardShell>
  );
};

export default DesktopScreenshotCard;
