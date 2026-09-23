import { PreferenceChoice } from "@/components/interaction/PreferenceChoice";
import styles from "./index.module.less";
import { useEffect, useState } from "react";
import { Card, Space, Tooltip, Button, Spin, message } from "antd";
import { Clock, Layers, CircleHelp } from "lucide-react";
import { useTranslation } from "react-i18next";
import { toolCallsApi } from "../../../api/modules/toolCalls";

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
    },
  ];

  return (
    <Card
      className={styles.card}
      title={
        <Space>
          <Clock size={18} />
          {t("agentConfig.offloadPolicy.title", "Tool Background Execution")}
          <Tooltip title={t("agentConfig.offloadPolicy.alertMessage")}>
            <Button
              type="text"
              size="small"
              aria-label={t("common.help", "Help")}
              icon={<CircleHelp size={16} />}
            />
          </Tooltip>
        </Space>
      }
    >
      {loading ? (
        <div style={{ textAlign: "center", padding: 24 }}>
          <Spin />
        </div>
      ) : (
        <div className={styles.choices}>
          {options.map((option) => (
            <PreferenceChoice
              key={option.value}
              label={
                <span>
                  {option.label}{" "}
                  <Tooltip title={option.description}>
                    <span tabIndex={0} aria-label={option.description}>
                      <CircleHelp size={14} />
                    </span>
                  </Tooltip>
                </span>
              }
              icon={
                option.value === "offload" ? (
                  <Layers size={20} />
                ) : (
                  <Clock size={20} />
                )
              }
              selected={policy === option.value}
              disabled={saving}
              onSelect={() => {
                if (option.value !== policy) void handleChange(option.value);
              }}
            />
          ))}
        </div>
      )}
    </Card>
  );
}
