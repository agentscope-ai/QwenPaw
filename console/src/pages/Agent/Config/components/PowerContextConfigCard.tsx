import {
  Card,
  Collapse,
  Form,
  Input,
  InputNumber,
  Switch,
} from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";

export function PowerContextConfigCard() {
  const { t } = useTranslation();
  return (
    <Card
      title={t("agentConfig.powercontextConfig.title", "PowerContext Memory")}
    >
      <Form.Item
        name={["powercontext_memory_config", "base_url"]}
        label={t("agentConfig.powercontextConfig.baseUrl", "Server URL")}
        rules={[{ required: true }, { type: "url" }]}
      >
        <Input placeholder="http://127.0.0.1:8000" />
      </Form.Item>
      <Form.Item
        name={["powercontext_memory_config", "token"]}
        label={t("agentConfig.powercontextConfig.token", "Access token")}
      >
        <Input.Password />
      </Form.Item>
      <Form.Item
        name={["powercontext_memory_config", "scope_id"]}
        label={t("agentConfig.powercontextConfig.scopeId", "Memory scope")}
        rules={[
          { max: 256 },
          {
            validator: (_, value) =>
              !value || value.trim().length > 0
                ? Promise.resolve()
                : Promise.reject(
                    new Error(
                      t(
                        "agentConfig.powercontextConfig.scopeIdInvalid",
                        "Memory scope must not contain only whitespace.",
                      ),
                    ),
                  ),
          },
        ]}
      >
        <Input
          placeholder={t(
            "agentConfig.powercontextConfig.scopeIdPlaceholder",
            "Leave empty to use this installation's unique agent scope",
          )}
          maxLength={256}
        />
      </Form.Item>
      <Form.Item
        name={["powercontext_memory_config", "timeout"]}
        label={t("agentConfig.powercontextConfig.timeout", "Request timeout")}
        initialValue={10}
        rules={[{ required: true }, { type: "number", min: 1, max: 60 }]}
      >
        <InputNumber
          min={1}
          max={60}
          addonAfter="s"
          style={{ width: "100%" }}
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
                    "powercontext_memory_config",
                    "auto_memory_search_config",
                    "enabled",
                  ]}
                  valuePropName="checked"
                  initialValue={true}
                  tooltip={t("agentConfig.autoMemorySearchTooltip")}
                >
                  <Switch />
                </Form.Item>
                <Form.Item
                  label={t(
                    "agentConfig.powercontextConfig.maxContextBytes",
                    "Maximum injected context (bytes)",
                  )}
                  name={[
                    "powercontext_memory_config",
                    "auto_memory_search_config",
                    "max_context_bytes",
                  ]}
                  initialValue={12000}
                  rules={[
                    { required: true },
                    { type: "number", min: 1024, max: 32768 },
                  ]}
                  tooltip={t(
                    "agentConfig.powercontextConfig.maxContextBytesTooltip",
                    "Bounds the total PowerContext search result content added to one model turn.",
                  )}
                >
                  <InputNumber
                    style={{ width: "100%" }}
                    min={1024}
                    max={32768}
                    step={1024}
                  />
                </Form.Item>
                <Form.Item
                  label={t("agentConfig.autoMaxResults")}
                  name={[
                    "powercontext_memory_config",
                    "auto_memory_search_config",
                    "max_results",
                  ]}
                  initialValue={3}
                  rules={[
                    { required: true },
                    { type: "number", min: 1, max: 50 },
                  ]}
                  tooltip={t("agentConfig.autoMaxResultsTooltip")}
                >
                  <InputNumber
                    style={{ width: "100%" }}
                    min={1}
                    max={50}
                    step={1}
                  />
                </Form.Item>
              </>
            ),
          },
        ]}
      />
    </Card>
  );
}
