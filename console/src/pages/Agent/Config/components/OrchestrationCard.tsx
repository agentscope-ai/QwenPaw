import { Form, InputNumber, Card, Switch, Select } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import styles from "../index.module.less";

interface OrchestrationCardProps {
  agentsList: { value: string; label: string }[];
}

export function OrchestrationCard({ agentsList }: OrchestrationCardProps) {
  const { t } = useTranslation();

  return (
    <Card
      className={styles.formCard}
      title={t("agentConfig.orchestrationTitle")}
      style={{ marginTop: 16 }}
    >
      <Form.Item
        label={t("agentConfig.canSpawnAgents")}
        name="can_spawn_agents"
        valuePropName="checked"
        tooltip={t("agentConfig.canSpawnAgentsTooltip")}
      >
        <Switch />
      </Form.Item>

      <Form.Item
        noStyle
        shouldUpdate={(prevValues, currentValues) =>
          prevValues.can_spawn_agents !== currentValues.can_spawn_agents
        }
      >
        {({ getFieldValue }) =>
          getFieldValue("can_spawn_agents") ? (
            <>
              <Form.Item
                label={t("agentConfig.allowedAgents")}
                name="allowed_agents"
                tooltip={t("agentConfig.allowedAgentsTooltip")}
              >
                <Select
                  mode="multiple"
                  placeholder={t("agentConfig.allowedAgentsPlaceholder")}
                  options={agentsList}
                  allowClear
                  showSearch
                  filterOption={(input, option) =>
                    (option?.label ?? "")
                      .toString()
                      .toLowerCase()
                      .includes(input.toLowerCase())
                  }
                />
              </Form.Item>

              <Form.Item
                label={t("agentConfig.maxSpawnDepth")}
                name="max_spawn_depth"
                tooltip={t("agentConfig.maxSpawnDepthTooltip")}
                rules={[
                  {
                    type: "number",
                    min: 1,
                    max: 10,
                    message: t("agentConfig.maxSpawnDepthRange"),
                  },
                ]}
              >
                <InputNumber min={1} max={10} style={{ width: "100%" }} />
              </Form.Item>
            </>
          ) : null
        }
      </Form.Item>
    </Card>
  );
}
