import { useEffect, useState } from "react";
import { Card, Radio, Space, Typography, Alert, Spin, message } from "antd";
import { Clock } from "lucide-react";
import { useTranslation } from "react-i18next";
import { toolCallsApi } from "../../../api/modules/toolCalls";

const { Text, Paragraph } = Typography;

export type OffloadPolicy = "keep_foreground" | "offload";

export function OffloadPolicyCard() {
  const { t } = useTranslation();
  const [policy, setPolicy] = useState<OffloadPolicy>("keep_foreground");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    toolCallsApi
      .getOffloadPolicy()
      .then((res) => {
        setPolicy((res.default_action as OffloadPolicy) || "keep_foreground");
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const handleChange = async (value: OffloadPolicy) => {
    setSaving(true);
    try {
      await toolCallsApi.setOffloadPolicy(value);
      setPolicy(value);
    } catch {
      message.error(
        t("agentConfig.offloadPolicy.saveFailed", "Failed to save policy"),
      );
    } finally {
      setSaving(false);
    }
  };

  const options = [
    {
      value: "keep_foreground" as OffloadPolicy,
      label: t("agentConfig.offloadPolicy.keepForeground", "Keep Foreground"),
      description: t(
        "agentConfig.offloadPolicy.keepForegroundDesc",
        "After the countdown expires, the tool continues running in the foreground without auto-offloading. Suitable for scenarios requiring real-time output monitoring.",
      ),
      color: "#faad14",
    },
    {
      value: "offload" as OffloadPolicy,
      label: t(
        "agentConfig.offloadPolicy.offload",
        "Auto Offload to Background",
      ),
      description: t(
        "agentConfig.offloadPolicy.offloadDesc",
        "After the countdown expires, the tool is automatically moved to background execution, allowing the Agent to continue processing other tasks. Suitable for long-running tools.",
      ),
      color: "#1890ff",
    },
  ];

  return (
    <Card
      title={
        <Space>
          <Clock size={18} />
          {t("agentConfig.offloadPolicy.title", "Tool Background Execution")}
        </Space>
      }
    >
      <Alert
        type="info"
        message={t(
          "agentConfig.offloadPolicy.alertMessage",
          "This is a global setting (settings.json), not per-agent. It controls the default action when a tool reaches its offload deadline. Users can override it from the tool control panel while a tool is running.",
        )}
        style={{ marginBottom: 24 }}
        showIcon
      />

      {loading ? (
        <div style={{ textAlign: "center", padding: 24 }}>
          <Spin />
        </div>
      ) : (
        <Radio.Group
          value={policy}
          onChange={(e) => handleChange(e.target.value as OffloadPolicy)}
          disabled={saving}
          style={{ width: "100%" }}
        >
          <Space direction="vertical" size={16} style={{ width: "100%" }}>
            {options.map((option) => (
              <Card
                key={option.value}
                style={{
                  borderColor:
                    policy === option.value ? option.color : undefined,
                  borderWidth: policy === option.value ? 2 : 1,
                  cursor: "pointer",
                  transition: "all 0.3s",
                }}
                onClick={() => !saving && handleChange(option.value)}
                hoverable
              >
                <Radio value={option.value} style={{ width: "100%" }}>
                  <div style={{ marginLeft: 12 }}>
                    <Space align="start" size={12}>
                      <div style={{ color: option.color, marginTop: 2 }}>
                        <Clock size={18} />
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
      )}
    </Card>
  );
}
