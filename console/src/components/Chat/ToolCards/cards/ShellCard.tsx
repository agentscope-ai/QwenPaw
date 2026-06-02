/**
 * ShellCard — renders shell/terminal tool calls with command + output.
 * Self-contained: no dependency on ShellExecutionCard.
 */

import React from "react";
import { CodeOutlined } from "@ant-design/icons";
import type { ToolCallContent } from "../shared/types";
import { ToolCardShell } from "../shared";
import { DefaultBlock } from "../shared";
import { stringifyResult } from "../shared/utils";
import styles from "../shared/toolCards.module.less";

export interface ShellCardProps {
  content: ToolCallContent;
  isStreaming?: boolean;
}

const ShellCard: React.FC<ShellCardProps> = ({ content }) => {
  const command =
    (content.params?.command as string) ||
    (content.params?.cmd as string) ||
    "";
  const resultText = stringifyResult(content.result);

  return (
    <ToolCardShell
      icon={<CodeOutlined />}
      title={command || content.name}
      content={content}
      defaultOpen={!!resultText}
    >
      {command && (
        <DefaultBlock title="Command" content={command} />
      )}
      {resultText && (
        <div className={styles.toolCallResultMd}>
          <pre style={{ margin: 0, whiteSpace: "pre-wrap", wordBreak: "break-all" }}>
            {resultText}
          </pre>
        </div>
      )}
    </ToolCardShell>
  );
};

export default ShellCard;
