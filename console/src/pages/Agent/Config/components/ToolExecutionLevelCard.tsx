import { Card, Space } from "antd";
import { useEffect, useState } from "react";
import { providerApi } from "@/api/modules/provider";
import { Link } from "react-router-dom";
import { Shield, ShieldCheck, ShieldQuestion, ShieldOff } from "lucide-react";
import InlineHelp from "@/components/InlineHelp";
import { PolicySelector } from "@/components/interaction/PolicySelector";
import { useTranslation } from "react-i18next";
import styles from "../index.module.less";

export type ToolExecutionLevel = "STRICT" | "SMART" | "JEV" | "AUTO" | "OFF";

interface LevelOption {
  value: ToolExecutionLevel;
  label: string;
  icon: React.ReactNode;
  description: string;
}

interface ToolExecutionLevelCardProps {
  value: ToolExecutionLevel;
  onChange: (level: ToolExecutionLevel) => void;
  disabled?: boolean;
}

export function ToolExecutionLevelCard({
  value: level,
  onChange,
  disabled = false,
}: ToolExecutionLevelCardProps) {
  const { t } = useTranslation();
  const [configured, setConfigured] = useState(false);

  useEffect(() => {
    void providerApi
      .listProviders()
      .then((providers) => {
        const decisionModelProvider = providers.find(
          (provider) => provider.id === "typesafe",
        );
        setConfigured(
          Boolean(
            decisionModelProvider?.enabled && decisionModelProvider.api_key,
          ),
        );
      })
      .catch(() => setConfigured(false));
  }, []);

  const levelOptions: LevelOption[] = [
    {
      value: "STRICT",
      label: t("agentConfig.toolExecutionLevel.strict"),
      icon: <ShieldCheck size={18} />,
      description: t("agentConfig.toolExecutionLevel.strictDesc"),
    },
    {
      value: "SMART",
      label: t("agentConfig.toolExecutionLevel.smart"),
      icon: <ShieldQuestion size={18} />,
      description: t("agentConfig.toolExecutionLevel.smartDesc"),
    },
    {
      value: "JEV",
      label: t("agentConfig.toolExecutionLevel.jev"),
      icon: <ShieldQuestion size={18} />,
      description: t("agentConfig.toolExecutionLevel.jevDesc"),
    },
    {
      value: "AUTO",
      label: t("agentConfig.toolExecutionLevel.auto"),
      icon: <Shield size={18} />,
      description: t("agentConfig.toolExecutionLevel.autoDesc"),
    },
    {
      value: "OFF",
      label: t("agentConfig.toolExecutionLevel.off"),
      icon: <ShieldOff size={18} />,
      description: t("agentConfig.toolExecutionLevel.offDesc"),
    },
  ];

  const selected = levelOptions.find((option) => option.value === level);

  return (
    <Card
      className={styles.formCard}
      title={
        <Space>
          <Shield size={18} />
          {t("agentConfig.toolExecutionLevel.title")}
          <InlineHelp>
            <Space direction="vertical" size={8}>
              <span>{t("agentConfig.toolExecutionLevel.alertMessage")}</span>
              <span>
                <strong>{selected?.label}：</strong>
                {selected?.description}
              </span>
            </Space>
          </InlineHelp>
        </Space>
      }
    >
      <PolicySelector
        value={level}
        onChange={onChange}
        disabled={disabled}
        label={t("agentConfig.toolExecutionLevel.title")}
        options={levelOptions}
        showDescription={false}
      />
      {level === "JEV" && (
        <Space direction="vertical" style={{ width: "100%", marginTop: 16 }}>
          <span>
            {t("agentConfig.toolExecutionLevel.decisionModelPrivacy")}
          </span>
          <span>
            {configured
              ? t("agentConfig.toolExecutionLevel.decisionModelConnected")
              : t("agentConfig.toolExecutionLevel.decisionModelNotConnected")}
          </span>
          <Link to="/settings/models">
            {t("agentConfig.toolExecutionLevel.decisionModelConfigure")}
          </Link>
        </Space>
      )}
    </Card>
  );
}
