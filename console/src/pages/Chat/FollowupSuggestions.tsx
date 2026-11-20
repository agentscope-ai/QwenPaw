import { useContext } from "react";
import { createPortal } from "react-dom";
import { Button } from "antd";
import { CornerDownRight } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useAppMessage } from "../../hooks/useAppMessage";
import {
  FollowupContext,
  FollowupPlacementContext,
  type FollowupSource,
} from "./followupContext";
import styles from "./HostBubbles.module.less";

interface FollowupSuggestion {
  label: string;
  prompt: string;
}

function parseFollowupSuggestions(source: string): FollowupSuggestion[] | null {
  if (source.length > 8192 || new TextEncoder().encode(source).length > 8192)
    return null;
  try {
    const value: unknown = JSON.parse(source);
    if (!Array.isArray(value) || value.length > 3) return null;
    const result: FollowupSuggestion[] = [];
    for (const item of value) {
      if (
        !item ||
        typeof item !== "object" ||
        Array.isArray(item) ||
        Object.keys(item).length !== 2 ||
        typeof item.label !== "string" ||
        typeof item.prompt !== "string"
      )
        return null;
      const label = item.label.trim();
      const prompt = item.prompt.trim();
      if (
        !label ||
        !prompt ||
        /[\r\n]/.test(label) ||
        [...item.label].length > 40 ||
        [...item.prompt].length > 100
      )
        return null;
      result.push({ label, prompt });
    }
    return result;
  } catch {
    return null;
  }
}

export function FollowupSuggestions({
  source,
  text,
}: {
  source: FollowupSource;
  text: string;
}) {
  const ctx = useContext(FollowupContext);
  const placement = useContext(FollowupPlacementContext);
  const { t } = useTranslation();
  const { message } = useAppMessage();
  if (
    !ctx ||
    ctx.blocked ||
    ctx.invalidatedResponseId === source.responseId ||
    ctx.agentId !== source.agentId ||
    ctx.chatId !== source.chatId
  )
    return null;
  const suggestions = parseFollowupSuggestions(text);
  if (!suggestions?.length) return null;
  const content = (
    <div className={styles.followupSuggestions}>
      {suggestions.map((item, index) => (
        <Button
          key={index}
          className={styles.followupSuggestion}
          type="text"
          htmlType="button"
          title={t("chat.followupAdd")}
          onClick={() => {
            if (!ctx.addFollowup(source, item.prompt))
              message.warning(t("chat.followupFailed"));
          }}
        >
          <CornerDownRight className={styles.followupIcon} aria-hidden="true" />
          <span>{item.label}</span>
        </Button>
      ))}
    </div>
  );
  return placement === undefined
    ? content
    : placement && createPortal(content, placement);
}
