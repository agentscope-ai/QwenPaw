import { Card, Radio, Alert, Space } from "antd";
import { Shield, ShieldCheck, ShieldQuestion, ShieldOff } from "lucide-react";
import { useTranslation } from "react-i18next";
import styles from "../index.module.less";

export type ToolExecutionLevel = "STRICT" | "SMART" | "AUTO" | "OFF";

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

  return (
    <Card
      className={styles.formCard}
      title={
        <Space>
          <Shield size={18} />
          {t("agentConfig.toolExecutionLevel.title")}
        </Space>
      }
    >
      <Alert
        type="info"
        message={t("agentConfig.toolExecutionLevel.alertMessage")}
        style={{ marginBottom: 24 }}
        showIcon
        icon={<Shield size={16} />}
      />

      <Radio.Group
        value={level}
        onChange={(e) => onChange(e.target.value as ToolExecutionLevel)}
        disabled={disabled}
        style={{ width: "100%" }}
      >
        <div className={styles.levelOptions}>
          {levelOptions.map((option) => (
            <Radio
              key={option.value}
              value={option.value}
              className={styles.levelOption}
            >
              <span className={styles.levelOptionIcon}>{option.icon}</span>
              <span className={styles.levelOptionCopy}>
                <strong>{option.label}</strong>
                <span>{option.description}</span>
              </span>
            </Radio>
          ))}
        </div>
      </Radio.Group>
    </Card>
  );
}
