import {
  Card,
  Form,
  Select,
  Input,
  InputNumber,
  Switch,
} from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";

export function ADBPGConfigCard() {
  const { t } = useTranslation();

  const apiMode = Form.useWatch(["adbpg_memory_config", "api_mode"]) ?? "rest";

  return (
    <Card title={t("agentConfig.adbpgConfig.title")}>
      {/* API Mode */}
      <Form.Item
        name={["adbpg_memory_config", "api_mode"]}
        label={t("agentConfig.adbpgConfig.apiMode")}
        initialValue="rest"
      >
        <Select>
          <Select.Option value="sql">SQL (Direct)</Select.Option>
          <Select.Option value="rest">REST API</Select.Option>
        </Select>
      </Form.Item>

      {apiMode === "sql" ? (
        <>
          {/* Database Connection */}
          <Form.Item
            name={["adbpg_memory_config", "host"]}
            label={t("agentConfig.adbpgConfig.host")}
          >
            <Input placeholder="gp-xxx.gpdb.rds.aliyuncs.com" />
          </Form.Item>
          <Form.Item
            name={["adbpg_memory_config", "port"]}
            label={t("agentConfig.adbpgConfig.port")}
          >
            <InputNumber min={1} max={65535} style={{ width: "100%" }} />
          </Form.Item>
          <Form.Item
            name={["adbpg_memory_config", "user"]}
            label={t("agentConfig.adbpgConfig.user")}
          >
            <Input />
          </Form.Item>
          <Form.Item
            name={["adbpg_memory_config", "password"]}
            label={t("agentConfig.adbpgConfig.password")}
          >
            <Input.Password />
          </Form.Item>
          <Form.Item
            name={["adbpg_memory_config", "dbname"]}
            label={t("agentConfig.adbpgConfig.dbname")}
          >
            <Input />
          </Form.Item>

          {/* LLM Config */}
          <Form.Item
            name={["adbpg_memory_config", "llm_model"]}
            label={t("agentConfig.adbpgConfig.llmModel")}
          >
            <Input placeholder="qwen-plus" />
          </Form.Item>
          <Form.Item
            name={["adbpg_memory_config", "llm_api_key"]}
            label={t("agentConfig.adbpgConfig.llmApiKey")}
          >
            <Input.Password />
          </Form.Item>
          <Form.Item
            name={["adbpg_memory_config", "llm_base_url"]}
            label={t("agentConfig.adbpgConfig.llmBaseUrl")}
          >
            <Input placeholder="https://dashscope.aliyuncs.com/compatible-mode/v1" />
          </Form.Item>

          {/* Embedding Config */}
          <Form.Item
            name={["adbpg_memory_config", "embedding_model"]}
            label={t("agentConfig.adbpgConfig.embeddingModel")}
          >
            <Input placeholder="text-embedding-v3" />
          </Form.Item>
          <Form.Item
            name={["adbpg_memory_config", "embedding_api_key"]}
            label={t("agentConfig.adbpgConfig.embeddingApiKey")}
          >
            <Input.Password />
          </Form.Item>
          <Form.Item
            name={["adbpg_memory_config", "embedding_base_url"]}
            label={t("agentConfig.adbpgConfig.embeddingBaseUrl")}
          >
            <Input placeholder="https://dashscope.aliyuncs.com/compatible-mode/v1" />
          </Form.Item>
          <Form.Item
            name={["adbpg_memory_config", "embedding_dims"]}
            label={t("agentConfig.adbpgConfig.embeddingDims")}
          >
            <InputNumber min={1} max={4096} style={{ width: "100%" }} />
          </Form.Item>
        </>
      ) : (
        <>
          {/* REST Mode */}
          <Form.Item
            name={["adbpg_memory_config", "rest_base_url"]}
            label={t("agentConfig.adbpgConfig.restBaseUrl")}
          >
            <Input placeholder="https://your-adbpg-api.example.com" />
          </Form.Item>
          <Form.Item
            name={["adbpg_memory_config", "rest_api_key"]}
            label={t("agentConfig.adbpgConfig.restApiKey")}
          >
            <Input.Password />
          </Form.Item>
        </>
      )}

      {/* Behavior */}
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
    </Card>
  );
}
