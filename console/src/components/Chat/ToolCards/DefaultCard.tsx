import React from "react";
import { Accordion } from "@agentscope-ai/chat";
import type { ToolCardProps } from "../types";

const DefaultCard: React.FC<ToolCardProps> = ({ data, status, toolName }) => {
  const statusIcon =
    status === "calling" ? "\u23F3" : status === "done" ? "\u2713" : "\u2717";
  const title = `${statusIcon} ${toolName}`;

  const content =
    typeof data === "string" ? data : JSON.stringify(data, null, 2);

  return (
    <Accordion
      title={title}
      defaultOpen={status === "calling"}
      status={
        status === "calling"
          ? "generating"
          : status === "done"
          ? "finished"
          : "error"
      }
    >
      <pre
        style={{
          fontSize: 12,
          lineHeight: 1.5,
          margin: 0,
          whiteSpace: "pre-wrap",
          wordBreak: "break-all",
          maxHeight: 300,
          overflow: "auto",
        }}
      >
        {content}
      </pre>
    </Accordion>
  );
};

export default DefaultCard;
