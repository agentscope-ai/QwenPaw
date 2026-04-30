import React, { useState, type ReactNode } from "react";
import { Card } from "@agentscope-ai/design";
import {
  ApiOutlined,
  CodeOutlined,
  ThunderboltOutlined,
  ToolOutlined,
} from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import type { ACPAgentConfig } from "../../../../api/types";
import styles from "../../../Control/Channels/index.module.less";

interface ACPCardIconSpec {
  icon?: ReactNode;
  imageUrl?: string;
}

const BUILTIN_ACP_ICON_MAP: Record<string, ACPCardIconSpec> = {
  opencode: {
    icon: <CodeOutlined />,
  },
  qwen_code: {
    icon: <ToolOutlined />,
  },
  claude_code: {
    icon: <ThunderboltOutlined />,
  },
  codex: {
    icon: <ApiOutlined />,
  },
};

const DEFAULT_ACP_ICON: ACPCardIconSpec = {
  icon: <ApiOutlined />,
};

interface ACPCardProps {
  agentKey: string;
  config: ACPAgentConfig;
  isBuiltin: boolean;
  onClick: () => void;
}

export const ACPCard = React.memo(function ACPCard({
  agentKey,
  config,
  isBuiltin,
  onClick,
}: ACPCardProps) {
  const { t } = useTranslation();
  const [isHover, setIsHover] = useState(false);
  const argsSummary = config.args?.join(" ") || t("acp.notSet");
  const iconSpec = BUILTIN_ACP_ICON_MAP[agentKey] ?? DEFAULT_ACP_ICON;
  const getCardClassNames = () => {
    if (isHover) return `${styles.channelCard} ${styles.hover}`;
    if (config.enabled) return `${styles.channelCard} ${styles.enabled}`;
    return `${styles.channelCard} ${styles.normal}`;
  };

  return (
    <Card
      hoverable
      onClick={onClick}
      onMouseEnter={() => setIsHover(true)}
      onMouseLeave={() => setIsHover(false)}
      className={getCardClassNames()}
      bodyStyle={{ padding: 24 }}
    >
      <div className={styles.cardTopSection}>
        <div className={styles.channelIcon}>
          {iconSpec.imageUrl ? (
            <img
              src={iconSpec.imageUrl}
              alt={agentKey}
              width={40}
              height={40}
            />
          ) : (
            iconSpec.icon
          )}
        </div>
        <div className={styles.statusIndicator}>
          <div
            className={`${styles.statusDot} ${
              config.enabled ? styles.enabled : styles.disabled
            }`}
          />
          <span
            className={`${styles.statusText} ${
              config.enabled ? styles.enabled : styles.disabled
            }`}
          >
            {config.enabled ? t("common.enabled") : t("common.disabled")}
          </span>
        </div>
      </div>

      <div className={styles.cardMiddleSection}>
        <div className={styles.cardTitle}>{agentKey}</div>
        {isBuiltin ? (
          <span className={styles.builtinTag}>{t("acp.builtin")}</span>
        ) : (
          <span className={styles.customTag}>{t("acp.custom")}</span>
        )}
      </div>

      <div className={styles.cardBottomSection}>
        <div className={styles.cardDescription}>
          {t("acp.command")}: {config.command || t("acp.notSet")}
        </div>
        <div className={styles.cardDescription}>
          {t("acp.args")}: {argsSummary}
        </div>
      </div>
    </Card>
  );
});
