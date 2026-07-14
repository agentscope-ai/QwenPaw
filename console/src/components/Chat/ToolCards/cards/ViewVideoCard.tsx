import React from "react";
import { useTranslation } from "react-i18next";
import { VideoCameraOutlined } from "@ant-design/icons";
import type { ToolCallContent } from "../shared/types";
import { ToolCardShell } from "../shared";
import { shortFileName } from "../shared/utils";

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

  return (
    <ToolCardShell
      content={content}
      isStreaming={isStreaming}
      icon={<VideoCameraOutlined />}
      title={title}
    />
  );
};

export default ViewVideoCard;
