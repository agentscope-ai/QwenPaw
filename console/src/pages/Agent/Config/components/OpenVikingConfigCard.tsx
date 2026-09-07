import {
  Card,
  Collapse,
  Form,
  Input,
  InputNumber,
  Select,
  Switch,
} from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";

export function OpenVikingConfigCard() {
  const { t } = useTranslation();

  return (
    <Card title={t("agentConfig.openvikingConfig.title")}>
      <Form.Item
        name={["openviking_memory_config", "base_url"]}
        label={t("agentConfig.openvikingConfig.baseUrl")}
        rules={[{ required: true }]}
      >
        <Input placeholder="http://openviking:1933" />
      </Form.Item>
      <Form.Item
        name={["openviking_memory_config", "api_key"]}
        label={t("agentConfig.openvikingConfig.apiKey")}
        rules={[{ required: true }]}
      >
        <Input.Password autoComplete="new-password" />
      </Form.Item>
      <Form.Item
        name={["openviking_memory_config", "request_timeout"]}
        label={t("agentConfig.openvikingConfig.requestTimeout")}
        initialValue={10}
      >
        <InputNumber min={1} max={300} addonAfter="s" style={{ width: "100%" }} />
      </Form.Item>
      <Form.Item
        name={["openviking_memory_config", "retrieval_token_budget"]}
        label={t("agentConfig.openvikingConfig.tokenBudget")}
        initialValue={2048}
      >
        <InputNumber min={64} max={32000} style={{ width: "100%" }} />
      </Form.Item>
      <Form.Item
        name={["openviking_memory_config", "commit_policy"]}
        label={t("agentConfig.openvikingConfig.commitPolicy")}
        initialValue="auto"
      >
        <Select
          options={[
            {
              value: "auto",
              label: t("agentConfig.openvikingConfig.commitAuto"),
            },
            {
              value: "every_turn",
              label: t("agentConfig.openvikingConfig.commitEveryTurn"),
            },
          ]}
        />
      </Form.Item>
      <Collapse
        items={[
          {
            key: "autoMemorySearch",
            label: t("agentConfig.autoMemorySearchCollapseLabel"),
            forceRender: true,
            children: (
              <>
                <Form.Item
                  label={t("agentConfig.autoMemorySearch")}
                  name={[
                    "openviking_memory_config",
                    "auto_memory_search_config",
                    "enabled",
                  ]}
                  valuePropName="checked"
                  initialValue={true}
                >
                  <Switch />
                </Form.Item>
                <Form.Item
                  label={t("agentConfig.autoMaxResults")}
                  name={[
                    "openviking_memory_config",
                    "auto_memory_search_config",
                    "max_results",
                  ]}
                  initialValue={3}
                >
                  <InputNumber style={{ width: "100%" }} min={1} step={1} />
                </Form.Item>
              </>
            ),
          },
        ]}
      />
    </Card>
  );
}
