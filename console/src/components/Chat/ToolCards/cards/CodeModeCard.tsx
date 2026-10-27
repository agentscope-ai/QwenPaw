import { Code2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { BuiltinCardProps } from "./index";
import { DefaultBlock, MediaPreview, ToolCardShell } from "../shared";
import { shortFileName, stringifyResult, toDisplayUrl } from "../shared/utils";

interface OutputBlock {
  type: "text" | "image" | "audio" | "video";
  text?: string;
  filename?: string;
  source?: {
    type: "url" | "base64";
    media_type: string;
    url?: string;
    data?: string;
  };
}

function outputBlocks(result: unknown): OutputBlock[] {
  let parsed = result;
  if (typeof result === "string") {
    try {
      parsed = JSON.parse(result);
    } catch {
      parsed = result;
    }
  }
  if (
    Array.isArray(parsed) &&
    parsed.length > 0 &&
    parsed.every(
      (block) =>
        block &&
        typeof block === "object" &&
        ["text", "image", "audio", "video"].includes(block.type),
    )
  ) {
    return parsed;
  }
  const text = stringifyResult(result);
  return text ? [{ type: "text", text }] : [];
}

export default function CodeModeCard({
  content,
  isStreaming,
}: BuiltinCardProps) {
  const { t } = useTranslation();
  const code =
    typeof content.params.code === "string" ? content.params.code : "";
  const blocks = outputBlocks(content.result);

  return (
    <ToolCardShell
      content={content}
      isStreaming={isStreaming}
      icon={<Code2 size={16} strokeWidth={1.75} />}
      title={t("codingMode.runCode")}
      defaultExpanded={
        content.status === "error" || blocks.some((b) => b.type !== "text")
      }
    >
      {code && (
        <DefaultBlock
          title={t("codingMode.script")}
          content={code}
          language="python"
        />
      )}
      {blocks.map((block, index) => {
        if (block.type === "text") {
          return (
            <DefaultBlock
              key={index}
              title={t("codingMode.output")}
              content={block.text || ""}
            />
          );
        }
        const source = block.source;
        if (!source) return null;
        const type = block.type;
        const url =
          source.type === "base64"
            ? `data:${source.media_type};base64,${source.data}`
            : toDisplayUrl(source.url || "");
        return (
          <MediaPreview
            key={index}
            media={{
              url,
              type,
              name: block.filename || shortFileName(source.url || "") || type,
            }}
          />
        );
      })}
    </ToolCardShell>
  );
}
