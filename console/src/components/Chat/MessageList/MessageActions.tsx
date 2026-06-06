import React, { useCallback, useState } from "react";
import { useTranslation } from "react-i18next";
import { CopyOutlined, CheckOutlined } from "@ant-design/icons";
import styles from "./MessageList.module.less";

interface MessageActionsProps {
  /** Text content to copy */
  textToCopy: string;
}

const MessageActions: React.FC<MessageActionsProps> = ({ textToCopy }) => {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(async () => {
    if (!textToCopy) return;
    try {
      await navigator.clipboard.writeText(textToCopy);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Fallback
      const textarea = document.createElement("textarea");
      textarea.value = textToCopy;
      textarea.style.position = "fixed";
      textarea.style.opacity = "0";
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand("copy");
      document.body.removeChild(textarea);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  }, [textToCopy]);

  if (!textToCopy) return null;

  return (
    <div className={styles.messageActions}>
      <button
        className={`${styles.actionBtn} ${
          copied ? styles.actionBtnActive : ""
        }`}
        onClick={handleCopy}
        title={copied ? t("tool.copied") : t("tool.copy")}
      >
        {copied ? <CheckOutlined /> : <CopyOutlined />}
      </button>
    </div>
  );
};

export default MessageActions;
