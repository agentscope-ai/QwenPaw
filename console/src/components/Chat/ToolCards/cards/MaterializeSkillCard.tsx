import React from "react";
import { useTranslation } from "react-i18next";
import { ThunderboltOutlined } from "@ant-design/icons";
import type { ToolCallContent } from "../shared/types";
import { ToolCardShell, DefaultBlock } from "../shared";
import { stringifyResult } from "../shared/utils";

export interface MaterializeSkillCardProps {
  content: ToolCallContent;
  isStreaming?: boolean;
}

const MaterializeSkillCard: React.FC<MaterializeSkillCardProps> = ({
  content,
  isStreaming,
}) => {
  const { t } = useTranslation();
  const params = content.params || {};
  const skill = (params.name || "") as string;
  const title = skill
    ? t("tool.materializeSkill", { skill })
    : t("tool.materializeSkillDefault");

  const resultText = stringifyResult(content.result);

  return (
    <ToolCardShell
      content={content}
      isStreaming={isStreaming}
      icon={<ThunderboltOutlined />}
      title={title}
    >
      {resultText && <DefaultBlock title="Output" content={resultText} />}
    </ToolCardShell>
  );
};

export default MaterializeSkillCard;
