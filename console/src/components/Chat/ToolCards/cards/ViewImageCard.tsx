import React from "react";
import { useTranslation } from "react-i18next";
import { PictureOutlined } from "@ant-design/icons";
import type { ToolCallContent } from "../shared/types";
import { ToolCardShell, MediaPreview } from "../shared";
import { shortFileName, getMediaInfo } from "../shared/utils";

export interface ViewImageCardProps {
  content: ToolCallContent;
  isStreaming?: boolean;
}

const ViewImageCard: React.FC<ViewImageCardProps> = ({
  content,
  isStreaming,
}) => {
  const { t } = useTranslation();
  const params = content.params || {};
  const imgPath = (params.image_path || "") as string;
  const file = shortFileName(imgPath);
  const title = file
    ? t("tool.viewImage", { file })
    : t("tool.viewImageDefault");

  return (
    <ToolCardShell
      content={content}
      isStreaming={isStreaming}
      icon={<PictureOutlined />}
      title={title}
      renderBody={() => {
        const media = getMediaInfo(content);
        return media ? <MediaPreview media={media} /> : null;
      }}
    />
  );
};

export default ViewImageCard;
