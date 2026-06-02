import React from "react";
import { useTranslation } from "react-i18next";
import { ThunderboltOutlined } from "@ant-design/icons";
import { Markdown } from "@agentscope-ai/chat";
import type { ToolCallContent } from "../shared/types";
import { ToolCardShell } from "../shared";
import { stringifyResult } from "../shared/utils";
import styles from "../shared/toolCards.module.less";

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
      {resultText && (
        <div className={styles.toolCallResultMd}>
          <Markdown content={resultText} />
        </div>
      )}
    </ToolCardShell>
  );
};

export default MaterializeSkillCard;
