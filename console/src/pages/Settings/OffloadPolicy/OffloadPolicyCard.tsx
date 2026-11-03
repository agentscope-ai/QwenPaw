import InlineHelp from "@/components/InlineHelp";
import { PolicySelector } from "@/components/interaction/PolicySelector";
import styles from "./index.module.less";
import { useEffect, useState, useRef } from "react";
import { useAutoSave } from "@/hooks/useAutoSave";
import { Card, Space, Spin } from "antd";
import { Clock, Layers } from "lucide-react";
import { useTranslation } from "react-i18next";
import { toolCallsApi } from "../../../api/modules/toolCalls";

export type OffloadPolicy = "keep_foreground" | "offload";

export function OffloadPolicyCard() {
  const { t } = useTranslation();
  const [policy, setPolicy] = useState<OffloadPolicy>("keep_foreground");
  const [loading, setLoading] = useState(true);
  const draft = useRef(policy);
  const { schedule } = useAutoSave(async () => {
    await toolCallsApi.setOffloadPolicy(draft.current);
  });

  useEffect(() => {
    toolCallsApi
      .getOffloadPolicy()
      .then((res) => {
        setPolicy((res.default_action as OffloadPolicy) || "keep_foreground");
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const handleChange = (value: OffloadPolicy) => {
    if (value === policy) return;
    draft.current = value;
    setPolicy(value);
    schedule();
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
          <InlineHelp>{t("agentConfig.offloadPolicy.alertMessage")}</InlineHelp>
        </Space>
      }
    >
      {loading ? (
        <div style={{ textAlign: "center", padding: 24 }}>
          <Spin />
        </div>
      ) : (
        <PolicySelector
          value={policy}
          onChange={handleChange}
          disabled={loading}
          label={t("agentConfig.offloadPolicy.title")}
          options={options.map((option) => ({
            ...option,
            icon:
              option.value === "offload" ? (
                <Layers size={18} />
              ) : (
                <Clock size={18} />
              ),
          }))}
        />
      )}
    </Card>
  );
}
