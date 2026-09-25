import React from "react";
import { useTranslation } from "react-i18next";
import { ServiceCard } from "@/components/interaction/ServiceCard";
import type { ACPAgentConfig } from "../../../../api/types";

interface ACPCardProps {
  agentKey: string;
  config: ACPAgentConfig;
  isBuiltin: boolean;
  onClick: () => void;
  onToggle: () => Promise<void>;
}

export const ACPCard = React.memo(function ACPCard({
  agentKey,
  config,
  isBuiltin,
  onClick,
  onToggle,
}: ACPCardProps) {
  const { t } = useTranslation();
  return (
    <ServiceCard
      name={agentKey}
      enabled={config.enabled}
      onConfigure={onClick}
      onToggle={onToggle}
      description={`${t("acp.command")}: ${
        config.command || t("acp.notSet")
      }\n${t("acp.args")}: ${config.args?.join(" ") || t("acp.notSet")}`}
      metadata={
        <>
          <span>{t(isBuiltin ? "acp.builtin" : "acp.custom")}</span>
          <span>{config.command || t("acp.notSet")}</span>
        </>
      }
    />
  );
});
