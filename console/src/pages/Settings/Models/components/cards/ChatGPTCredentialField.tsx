import { Tooltip } from "antd";
import { CircleHelp } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { ProviderInfo } from "@/api/types";
import type { ChatGPTSession } from "./ChatGPTAccountPanel";
import styles from "../../index.module.less";
import accountStyles from "./ChatGPTAccountPanel.module.less";

export function ChatGPTCredentialField({
  provider,
  onConfigure,
}: {
  provider: ProviderInfo;
  onConfigure: () => void;
}) {
  const { t } = useTranslation();
  const session = provider.meta?.chatgpt_session as ChatGPTSession | undefined;
  const account = session?.accounts.find((item) => item.id === session.active);
  const label = session?.sharing
    ? account?.email || t("models.chatgpt.connected")
    : t(
        session?.connected
          ? "models.chatgpt.permissionMissing"
          : "models.chatgpt.disconnected",
      );

  return (
    <div className={styles.groupCardField}>
      <span className={styles.groupCardFieldLabel}>
        <Tooltip
          title={t("models.chatgpt.localHelp")}
          trigger={["hover", "focus", "click"]}
        >
          <span tabIndex={0} className={accountStyles.summaryLabel}>
            {t("models.chatgpt.account")}
            <CircleHelp size={14} strokeWidth={1.7} aria-hidden />
          </span>
        </Tooltip>
      </span>
      <div className={styles.groupCardMono}>
        <span className={accountStyles.summaryValue} title={label}>
          {label}
        </span>
        <button
          type="button"
          className={styles.groupCardChangeBtn}
          onClick={onConfigure}
        >
          {t(session?.sharing ? "models.settings" : "models.connect")}
        </button>
      </div>
    </div>
  );
}
