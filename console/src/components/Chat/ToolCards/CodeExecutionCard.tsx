import React, { useState } from "react";
import { Accordion } from "@agentscope-ai/chat";
import type { ToolCardProps } from "../types";

interface CodeExecutionData {
  code?: string;
  language?: string;
  output?: string;
  error?: string;
  exitCode?: number;
}

const CodeExecutionCard: React.FC<ToolCardProps<CodeExecutionData>> = ({
  data,
  status,
  toolName,
}) => {
  const [showCode, setShowCode] = useState(false);
  const hasError =
    !!data.error || (data.exitCode !== undefined && data.exitCode !== 0);

  return (
    <div style={{ margin: "8px 0" }}>
      <Accordion
        title={
          <span>
            {status === "calling" ? "⏳" : hasError ? "✗" : "✓"}{" "}
            {toolName || "Code Execution"}
            {data.language && (
              <span style={{ opacity: 0.6, fontSize: 12, marginLeft: 8 }}>
                {data.language}
              </span>
            )}
          </span>
        }
        defaultOpen={status === "calling"}
      >
        <div style={{ fontSize: 12 }}>
          {data.code && (
            <div style={{ marginBottom: 8 }}>
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  marginBottom: 4,
                }}
              >
                <span style={{ fontWeight: 500 }}>Code</span>
                <button
                  onClick={() => setShowCode(!showCode)}
                  style={{
                    background: "none",
                    border: "none",
                    cursor: "pointer",
                    fontSize: 11,
                    color: "#1677ff",
                  }}
                >
                  {showCode ? "Hide" : "Show"}
                </button>
              </div>
              {showCode && (
                <pre
                  style={{
                    padding: 8,
                    background: "rgba(0,0,0,0.03)",
                    borderRadius: 4,
                    overflow: "auto",
                    maxHeight: 200,
                    margin: 0,
                    whiteSpace: "pre-wrap",
                  }}
                >
                  {data.code}
                </pre>
              )}
            </div>
          )}
          {data.output && (
            <div>
              <span style={{ fontWeight: 500 }}>Output</span>
              <pre
                style={{
                  padding: 8,
                  background: "rgba(0,0,0,0.03)",
                  borderRadius: 4,
                  overflow: "auto",
                  maxHeight: 200,
                  margin: "4px 0 0",
                  whiteSpace: "pre-wrap",
                }}
              >
                {data.output}
              </pre>
            </div>
          )}
          {data.error && (
            <div style={{ color: "#ff4d4f", marginTop: 4 }}>
              <span style={{ fontWeight: 500 }}>Error</span>
              <pre
                style={{
                  padding: 8,
                  background: "rgba(255,77,79,0.05)",
                  borderRadius: 4,
                  overflow: "auto",
                  maxHeight: 150,
                  margin: "4px 0 0",
                  whiteSpace: "pre-wrap",
                }}
              >
                {data.error}
              </pre>
            </div>
          )}
        </div>
      </Accordion>
    </div>
  );
};

export default CodeExecutionCard;
