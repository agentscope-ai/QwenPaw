import { useMemo } from "react";
import { Bubble } from "@agentscope-ai/chat";
import { SparkCopyLine } from "@agentscope-ai/icons";
import { Tooltip, message } from "antd";
import { useTranslation } from "react-i18next";
import { copyText } from "../../utils/clipboard";

// Types - defined locally since they're not exported from @agentscope-ai/chat
const AgentScopeRuntimeContentType = {
  TEXT: "text",
  IMAGE: "image",
  FILE: "file",
} as const;

interface ITextContent {
  type: "text";
  text: string;
}

interface IImageContent {
  type: "image";
  image_url: string;
}

interface IFileContent {
  type: "file";
  file_url: string;
  file_name?: string;
  file_size?: number;
}

type IContent = ITextContent | IImageContent | IFileContent;

interface IAgentScopeRuntimeRequest {
  input: {
    role: string;
    type: string;
    content: IContent[];
  }[];
}

interface RequestCardProps {
  data: IAgentScopeRuntimeRequest;
}

/**
 * Custom RequestCard with copy button for user messages
 */
export default function AgentScopeRuntimeRequestCard(props: RequestCardProps) {
  const { t } = useTranslation();

  const cards = useMemo(() => {
    return props.data.input[0].content.reduce<any[]>((p, c) => {
      if (c.type === AgentScopeRuntimeContentType.TEXT) {
        p.push({
          code: "Text",
          data: {
            content: (c as ITextContent).text,
          },
        });
      } else if (c.type === AgentScopeRuntimeContentType.IMAGE) {
        p.push({
          code: "Image",
          data: {
            url: (c as IImageContent).image_url,
          },
        });
      } else if (c.type === AgentScopeRuntimeContentType.FILE) {
        const fileCard = p.find((item: any) => item.code === "Files");
        if (!fileCard) {
          p.push({
            code: "Files",
            data: [
              {
                url: (c as IFileContent).file_url,
                name: (c as IFileContent).file_name,
                size: (c as IFileContent).file_size,
              },
            ],
          });
        } else {
          fileCard.data.push({
            url: (c as IFileContent).file_url,
            name: (c as IFileContent).file_name,
            size: (c as IFileContent).file_size,
          });
        }
      }
      return p;
    }, []);
  }, [props.data.input]);

  // Extract text content for copying
  const textContent = useMemo(() => {
    return props.data.input[0].content
      .filter((c: IContent) => c.type === AgentScopeRuntimeContentType.TEXT)
      .map((c: IContent) => (c as ITextContent).text)
      .join("\n");
  }, [props.data.input]);

  const hasTextContent = textContent.trim().length > 0;

  const handleCopy = async () => {
    if (!textContent) return;

    try {
      await copyText(textContent);
      message.success(t?.("common.copied") || "Copied to clipboard");
    } catch {
      message.error(t?.("common.copyFailed") || "Failed to copy to clipboard");
    }
  };

  if (!cards?.length) return null;

  // Only show copy button when there is text content
  if (!hasTextContent) {
    return <Bubble role="user" cards={cards} />;
  }

  const copyAction = {
    icon: (
      <Tooltip title={t?.("common.copy") || "Copy"}>
        <SparkCopyLine />
      </Tooltip>
    ),
    onClick: handleCopy,
  };

  return (
    <>
      <Bubble role="user" cards={cards} />
      <Bubble.Footer right={<Bubble.Footer.Actions data={[copyAction]} />} />
    </>
  );
}