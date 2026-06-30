import { useState } from "react";
import {
  Card,
  Form,
  InputNumber,
  Select,
  Switch,
  Input,
  Button,
} from "@agentscope-ai/design";
import { Plus, Trash2, ChevronDown, ChevronRight } from "lucide-react";
import { useTranslation } from "react-i18next";
import styles from "../index.module.less";

const ACTION_OPTIONS = [
  { value: "modify_prompt", label: "Inject Warning" },
  { value: "stop", label: "Stop & Ask Human" },
];

export function AgentLoopCard() {
  const { t } = useTranslation();
  const form = Form.useFormInstance();
  const [advanced, setAdvanced] = useState(false);

  const enabled = Form.useWatch(["loop", "doom_loop", "enabled"], form);
  const stages =
    Form.useWatch(["loop", "doom_loop", "stages"], form) || [];

  return (
    <Card
      className={styles.formCard}
      title={t("agentConfig.agentLoopTitle", "Agent Loop")}
    >
      <Form.Item
        name={["loop", "doom_loop", "enabled"]}
        label={t("agentConfig.doomLoopEnabled", "Doom Loop Detection")}
        valuePropName="checked"
        tooltip={t(
          "agentConfig.doomLoopEnabledTooltip",
          "Detect repetitive agent behavior and intervene",
        )}
      >
        <Switch />
      </Form.Item>

      {enabled && (
        <>
          {/* Simple mode: show summary of stages */}
          {!advanced && (
            <div style={{ marginBottom: 16 }}>
              {stages.map(
                (
                  stage: { after: number; action: string; prompt: string },
                  idx: number,
                ) => (
                  <div
                    key={idx}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 8,
                      marginBottom: 8,
                    }}
                  >
                    <span style={{ color: "var(--text-secondary)", whiteSpace: "nowrap" }}>
                      {t("agentConfig.doomLoopAfter", "After")}{" "}
                      <strong>{stage.after}</strong>{" "}
                      {t("agentConfig.doomLoopRepetitions", "repetitions")} →
                    </span>
                    <span>
                      {stage.action === "stop"
                        ? t("agentConfig.doomLoopStopAction", "Stop & Ask Human")
                        : t(
                            "agentConfig.doomLoopWarnAction",
                            "Inject Warning",
                          )}
                    </span>
                  </div>
                ),
              )}
            </div>
          )}

          <Button
            type="link"
            size="small"
            onClick={() => setAdvanced(!advanced)}
            style={{ padding: 0, marginBottom: 16 }}
          >
            <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
              {advanced ? (
                <ChevronDown size={14} />
              ) : (
                <ChevronRight size={14} />
              )}
              {advanced
                ? t("agentConfig.doomLoopSimpleMode", "Simple")
                : t("agentConfig.doomLoopAdvancedMode", "Advanced")}
            </span>
          </Button>

          {/* Advanced mode: full config */}
          {advanced && (
            <>
              <div className={styles.reactAgentRow}>
                <Form.Item
                  name={["loop", "doom_loop", "window_size"]}
                  label={t("agentConfig.doomLoopWindowSize", "Window Size")}
                  tooltip={t(
                    "agentConfig.doomLoopWindowSizeTooltip",
                    "Sliding window size for repetition detection",
                  )}
                  className={styles.reactAgentField}
                >
                  <InputNumber min={2} max={20} style={{ width: "100%" }} />
                </Form.Item>

                <Form.Item
                  name={["loop", "doom_loop", "similarity_threshold"]}
                  label={t(
                    "agentConfig.doomLoopSimilarity",
                    "Similarity Threshold",
                  )}
                  tooltip={t(
                    "agentConfig.doomLoopSimilarityTooltip",
                    "Similarity threshold to consider calls as repetitive (0-1)",
                  )}
                  className={styles.reactAgentField}
                >
                  <InputNumber
                    min={0}
                    max={1}
                    step={0.05}
                    style={{ width: "100%" }}
                  />
                </Form.Item>
              </div>

              <hr style={{ border: "none", borderTop: "1px solid var(--border-color)", margin: "12px 0" }} />
              <strong style={{ display: "block", marginBottom: 12 }}>
                {t("agentConfig.doomLoopStages", "Escalation Stages")}
              </strong>

              <Form.List name={["loop", "doom_loop", "stages"]}>
                {(fields, { add, remove }) => (
                  <>
                    {fields.map(({ key, name, ...rest }) => (
                      <div
                        key={key}
                        style={{
                          display: "flex",
                          gap: 8,
                          marginBottom: 12,
                          alignItems: "flex-start",
                        }}
                      >
                        <Form.Item
                          {...rest}
                          name={[name, "after"]}
                          label={
                            name === 0
                              ? t("agentConfig.doomLoopAfter", "After")
                              : undefined
                          }
                          rules={[{ required: true }]}
                          style={{ flex: 1 }}
                        >
                          <InputNumber
                            min={1}
                            placeholder="N"
                            style={{ width: "100%" }}
                          />
                        </Form.Item>

                        <Form.Item
                          {...rest}
                          name={[name, "action"]}
                          label={
                            name === 0
                              ? t("agentConfig.doomLoopAction", "Action")
                              : undefined
                          }
                          rules={[{ required: true }]}
                          style={{ flex: 1.5 }}
                        >
                          <Select options={ACTION_OPTIONS} />
                        </Form.Item>

                        <Form.Item
                          {...rest}
                          name={[name, "prompt"]}
                          label={
                            name === 0
                              ? t("agentConfig.doomLoopPrompt", "Prompt")
                              : undefined
                          }
                          style={{ flex: 3 }}
                        >
                          <Input.TextArea
                            rows={1}
                            autoSize={{ minRows: 1, maxRows: 3 }}
                            placeholder={t(
                              "agentConfig.doomLoopPromptPlaceholder",
                              "Warning or stop reason...",
                            )}
                          />
                        </Form.Item>

                        <Button
                          type="text"
                          danger
                          icon={<Trash2 size={14} />}
                          onClick={() => remove(name)}
                          style={{ marginTop: name === 0 ? 30 : 0 }}
                        />
                      </div>
                    ))}
                    <Button
                      type="dashed"
                      onClick={() =>
                        add({ after: (stages.length + 1) * 3, action: "modify_prompt", prompt: "" })
                      }
                      icon={<Plus size={14} />}
                      style={{ width: "100%" }}
                    >
                      {t("agentConfig.doomLoopAddStage", "Add Stage")}
                    </Button>
                  </>
                )}
              </Form.List>
            </>
          )}
        </>
      )}
    </Card>
  );
}
