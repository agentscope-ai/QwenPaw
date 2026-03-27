import { Form, Card, Switch, InputNumber, Input } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import { SliderWithValue } from "./SliderWithValue";
import styles from "../index.module.less";

export function MemorySummaryCard() {
  const { t } = useTranslation();

  return (
    <Card
      className={styles.formCard}
      title={t("agentConfig.memorySummaryTitle")}
      style={{ marginTop: 16 }}
    >
      <Form.Item
        label={t("agentConfig.memorySummaryEnabled")}
        name={["memory_summary", "memory_summary_enabled"]}
        valuePropName="checked"
        tooltip={t("agentConfig.memorySummaryEnabledTooltip")}
      >
        <Switch />
      </Form.Item>

      <Form.Item
        label={t("agentConfig.memoryConsolidationCron")}
        name={["memory_summary", "memory_consolidation_cron"]}
        tooltip={t("agentConfig.memoryConsolidationCronTooltip")}
      >
        <Input
          placeholder={t("agentConfig.memoryConsolidationCronPlaceholder")}
        />
      </Form.Item>

      <Form.Item
        label={t("agentConfig.forceMemorySearch")}
        name={["memory_summary", "force_memory_search"]}
        valuePropName="checked"
        tooltip={t("agentConfig.forceMemorySearchTooltip")}
      >
        <Switch />
      </Form.Item>

      <Form.Item
        label={t("agentConfig.forceMaxResults")}
        name={["memory_summary", "force_max_results"]}
        rules={[
          { required: true, message: t("agentConfig.forceMaxResultsRequired") },
          {
            type: "number",
            min: 1,
            message: t("agentConfig.forceMaxResultsMin"),
          },
        ]}
        tooltip={t("agentConfig.forceMaxResultsTooltip")}
      >
        <InputNumber style={{ width: "100%" }} min={1} step={1} />
      </Form.Item>

      <Form.Item
        label={t("agentConfig.forceMinScore")}
        name={["memory_summary", "force_min_score"]}
        rules={[
          { required: true, message: t("agentConfig.forceMinScoreRequired") },
        ]}
        tooltip={t("agentConfig.forceMinScoreTooltip")}
      >
        <SliderWithValue
          min={0}
          max={1}
          step={0.05}
          marks={{ 0: "0", 0.5: "0.5", 1: "1" }}
        />
      </Form.Item>

      <Form.Item
        label={t("agentConfig.rebuildMemoryIndexOnStart")}
        name={["memory_summary", "rebuild_memory_index_on_start"]}
        valuePropName="checked"
        tooltip={t("agentConfig.rebuildMemoryIndexOnStartTooltip")}
      >
        <Switch />
      </Form.Item>
    </Card>
  );
}
