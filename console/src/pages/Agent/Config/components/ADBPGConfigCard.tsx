import {
  Card,
  Collapse,
  Form,
  Input,
  InputNumber,
  Switch,
} from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import { useEffect } from "react";
import type { ADBPGMemoryConfig } from "@/api/types/agent";

export function createDefaultADBPGMemoryConfig(): ADBPGMemoryConfig {
  return {
    rest_base_url: "",
    rest_api_key: "",
    memory_isolation: true,
    search_timeout: 10,
    auto_memory_search_config: {
      enabled: true,
      max_results: 3,
    },
  };
}

export function ADBPGConfigCard() {
  const { t } = useTranslation();
  const form = Form.useFormInstance();

  useEffect(() => {
    if (form.getFieldValue("adbpg_memory_config") == null) {
      form.setFieldValue(
        "adbpg_memory_config",
        createDefaultADBPGMemoryConfig(),
      );
    }
  }, [form]);

  return (
    <Card title={t("agentConfig.adbpgConfig.title")}>
      <Form.Item
        name={["adbpg_memory_config", "rest_base_url"]}
        label={t("agentConfig.adbpgConfig.restBaseUrl")}
        initialValue=""
      >
        <Input placeholder="https://your-adbpg-api.example.com" />
      </Form.Item>
      <Form.Item
        name={["adbpg_memory_config", "rest_api_key"]}
        label={t("agentConfig.adbpgConfig.restApiKey")}
        initialValue=""
      >
        <Input.Password />
      </Form.Item>
      <Form.Item
        name={["adbpg_memory_config", "memory_isolation"]}
        label={t("agentConfig.adbpgConfig.memoryIsolation")}
        valuePropName="checked"
        initialValue={true}
      >
        <Switch />
      </Form.Item>
      <Form.Item
        name={["adbpg_memory_config", "search_timeout"]}
        label={t("agentConfig.adbpgConfig.searchTimeout")}
        initialValue={10}
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
                    "adbpg_memory_config",
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
                  label={t("agentConfig.autoMaxResults")}
                  name={[
                    "adbpg_memory_config",
                    "auto_memory_search_config",
                    "max_results",
                  ]}
                  rules={[
                    {
                      required: true,
                      message: t("agentConfig.autoMaxResultsRequired"),
                    },
                    {
                      type: "number",
                      min: 1,
                      message: t("agentConfig.autoMaxResultsMin"),
                    },
                  ]}
                  initialValue={3}
                  tooltip={t("agentConfig.autoMaxResultsTooltip")}
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
