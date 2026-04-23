import { useState, useEffect } from "react";
import { Card, Radio, Alert, Space, Typography } from "antd";
import { Shield, CheckCircle, AlertTriangle, Ban } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useAppMessage } from "../../../../hooks/useAppMessage";
import { agentsApi } from "../../../../api/modules/agents";
import { useAgentStore } from "../../../../stores/agentStore";
import styles from "../index.module.less";

const { Text, Paragraph } = Typography;

type ToolExecutionLevel = "STRICT" | "SMART" | "AUTO" | "OFF";

interface LevelOption {
  value: ToolExecutionLevel;
  label: string;
  icon: React.ReactNode;
  description: string;
  color: string;
}

export function ToolExecutionLevelCard() {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const { selectedAgent } = useAgentStore();
  const [level, setLevel] = useState<ToolExecutionLevel>("AUTO");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    loadLevel();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedAgent]);

  const loadLevel = async () => {
    setLoading(true);
    try {
      const config = await agentsApi.getAgent(selectedAgent);
      const currentLevel = (
        config?.approval_level || "AUTO"
      ).toUpperCase() as ToolExecutionLevel;
      setLevel(currentLevel);
    } catch (error) {
      console.error("Failed to load tool execution level:", error);
      message.error(t("agentConfig.loadFailed"));
    } finally {
      setLoading(false);
    }
  };

  const handleChange = async (newLevel: ToolExecutionLevel) => {
    setSaving(true);
    try {
      // Get current config first
      const config = await agentsApi.getAgent(selectedAgent);
      // Update with new approval_level
      await agentsApi.updateAgent(selectedAgent, {
        ...config,
        approval_level: newLevel,
      });
      setLevel(newLevel);
      message.success(t("agentConfig.saveLevelSuccess"));
    } catch (error) {
      console.error("Failed to save tool execution level:", error);
      message.error(t("agentConfig.saveLevelFailed"));
    } finally {
      setSaving(false);
    }
  };

  const levelOptions: LevelOption[] = [
    {
      value: "STRICT",
      label: t("agentConfig.toolExecutionLevel.strict"),
      icon: <Ban size={18} />,
      description: t("agentConfig.toolExecutionLevel.strictDesc"),
      color: "#ff4d4f",
    },
    {
      value: "SMART",
      label: t("agentConfig.toolExecutionLevel.smart"),
      icon: <AlertTriangle size={18} />,
      description: t("agentConfig.toolExecutionLevel.smartDesc"),
      color: "#faad14",
    },
    {
      value: "AUTO",
      label: t("agentConfig.toolExecutionLevel.auto"),
      icon: <Shield size={18} />,
      description: t("agentConfig.toolExecutionLevel.autoDesc"),
      color: "#1890ff",
    },
    {
      value: "OFF",
      label: t("agentConfig.toolExecutionLevel.off"),
      icon: <CheckCircle size={18} />,
      description: t("agentConfig.toolExecutionLevel.offDesc"),
      color: "#52c41a",
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
      />

      <Radio.Group
        value={level}
        onChange={(e) => handleChange(e.target.value as ToolExecutionLevel)}
        disabled={loading || saving}
        style={{ width: "100%" }}
      >
        <Space direction="vertical" size={16} style={{ width: "100%" }}>
          {levelOptions.map((option) => (
            <Card
              key={option.value}
              className={styles.levelOptionCard}
              style={{
                borderColor: level === option.value ? option.color : undefined,
                borderWidth: level === option.value ? 2 : 1,
                cursor: "pointer",
                transition: "all 0.3s",
              }}
              onClick={() => !loading && !saving && handleChange(option.value)}
              hoverable
            >
              <Radio value={option.value} style={{ width: "100%" }}>
                <div style={{ marginLeft: 12 }}>
                  <Space align="start" size={12}>
                    <div style={{ color: option.color, marginTop: 2 }}>
                      {option.icon}
                    </div>
                    <div style={{ flex: 1 }}>
                      <Text strong style={{ fontSize: 15 }}>
                        {option.label}
                      </Text>
                      <Paragraph
                        type="secondary"
                        style={{ margin: "4px 0 0 0", fontSize: 13 }}
                      >
                        {option.description}
                      </Paragraph>
                    </div>
                  </Space>
                </div>
              </Radio>
            </Card>
          ))}
        </Space>
      </Radio.Group>
    </Card>
  );
}
