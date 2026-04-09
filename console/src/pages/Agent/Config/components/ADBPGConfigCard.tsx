import { useState, useEffect } from "react";
import {
  Card,
  Form,
  Select,
  Input,
  InputNumber,
  Button,
  Switch,
} from "@agentscope-ai/design";
import { Alert } from "antd";
import { useTranslation } from "react-i18next";
import { agentApi } from "../../../../api/modules/agent";
import styles from "../index.module.less";

export function ADBPGConfigCard() {
  const { t } = useTranslation();
  const form = Form.useFormInstance();
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{
    type: "success" | "error" | "warning";
    message: string;
  } | null>(null);
  // Reactively watch the selected backend to conditionally render ADBPG fields
  const backend = Form.useWatch("memory_manager_backend") ?? "remelight";
  const apiMode = Form.useWatch(["adbpg", "api_mode"]) ?? "sql";
  const userIsolation = Form.useWatch(["adbpg", "user_isolation"]) ?? false;
  const [customPromptOn, setCustomPromptOn] = useState(false);

  // Sync switch state only when form data is loaded/reloaded from server
  // (detected by backend value changing, which happens on fetchConfig)
  useEffect(() => {
    const val = form.getFieldValue(["adbpg", "custom_fact_extraction_prompt"]);
    setCustomPromptOn(typeof val === "string" && val.trim().length > 0);
  }, [backend, form]);

  const handleTestConnection = async () => {
    setTestResult(null);
    const adbpg = form.getFieldValue("adbpg") || {};
    const host = adbpg.host || "";
    const port = adbpg.port || 5432;
    const user = adbpg.user || "";
    const password = adbpg.password || "";
    const dbname = adbpg.dbname || "";
    if (!host || !user || !password || !dbname) {
      setTestResult({
        type: "warning",
        message: t("agentConfig.adbpgConfig.testConnectionFillRequired"),
      });
      return;
    }
    setTesting(true);
    try {
      const res = await agentApi.testAdbpgConnection({
        host,
        port,
        user,
        password,
        dbname,
      });
      if (res.success) {
        setTestResult({ type: "success", message: res.message });
      } else {
        setTestResult({ type: "error", message: res.message });
      }
    } catch (err) {
      console.error("Test connection error:", err);
      setTestResult({
        type: "error",
        message: t("agentConfig.adbpgConfig.testConnectionError"),
      });
    } finally {
      setTesting(false);
    }
  };

  if (backend !== "adbpg") {
    return null;
  }

  return (
    <Card
      className={styles.formCard}
      title={t("agentConfig.adbpgConfig.title")}
      style={{ marginTop: 16 }}
    >
      {/* API mode selector */}
      <Form.Item
        label={t("agentConfig.adbpgConfig.apiModeLabel")}
        name={["adbpg", "api_mode"]}
        tooltip={t("agentConfig.adbpgConfig.apiModeTooltip")}
        initialValue="sql"
      >
        <Select>
          <Select.Option value="sql">SQL</Select.Option>
          <Select.Option value="rest">REST</Select.Option>
        </Select>
      </Form.Item>

      {apiMode === "rest" && (
        <Card
          type="inner"
          title={t("agentConfig.adbpgConfig.restConnectionTitle")}
          style={{ marginBottom: 16 }}
        >
          <Form.Item
            label={t("agentConfig.adbpgConfig.restApiKey")}
            name={["adbpg", "rest_api_key"]}
            rules={[
              {
                required: true,
                message: t("agentConfig.adbpgConfig.restApiKeyRequired"),
              },
            ]}
          >
            <Input.Password
              placeholder={t("agentConfig.adbpgConfig.restApiKeyPlaceholder")}
            />
          </Form.Item>
          <Form.Item
            label={t("agentConfig.adbpgConfig.restBaseUrl")}
            name={["adbpg", "rest_base_url"]}
            tooltip={t("agentConfig.adbpgConfig.restBaseUrlTooltip")}
          >
            <Input placeholder="http://your-adbpg-memory-host:6001" />
          </Form.Item>
        </Card>
      )}

      {/* --- SQL-specific fields (shown only when api_mode !== "rest") --- */}
      {apiMode !== "rest" && (
        <>
          {/* Database connection parameters */}
          <Card
            type="inner"
            title={t("agentConfig.adbpgConfig.dbConnectionTitle")}
            style={{ marginBottom: 16 }}
          >
            <Form.Item
              label={t("agentConfig.adbpgConfig.host")}
              name={["adbpg", "host"]}
              rules={[
                {
                  required: true,
                  message: t("agentConfig.adbpgConfig.hostRequired"),
                },
              ]}
            >
              <Input placeholder="e.g. gp-xxx.gpdb.rds.aliyuncs.com" />
            </Form.Item>
            <Form.Item
              label={t("agentConfig.adbpgConfig.port")}
              name={["adbpg", "port"]}
              rules={[{ required: true }]}
              initialValue={5432}
            >
              <InputNumber
                style={{ width: "100%" }}
                min={1}
                max={65535}
                placeholder="5432"
              />
            </Form.Item>
            <Form.Item
              label={t("agentConfig.adbpgConfig.user")}
              name={["adbpg", "user"]}
              rules={[
                {
                  required: true,
                  message: t("agentConfig.adbpgConfig.userRequired"),
                },
              ]}
            >
              <Input
                placeholder={t("agentConfig.adbpgConfig.userPlaceholder")}
              />
            </Form.Item>
            <Form.Item
              label={t("agentConfig.adbpgConfig.password")}
              name={["adbpg", "password"]}
              rules={[
                {
                  required: true,
                  message: t("agentConfig.adbpgConfig.passwordRequired"),
                },
              ]}
            >
              <Input.Password
                placeholder={t("agentConfig.adbpgConfig.passwordPlaceholder")}
              />
            </Form.Item>
            <Form.Item
              label={t("agentConfig.adbpgConfig.dbname")}
              name={["adbpg", "dbname"]}
              rules={[
                {
                  required: true,
                  message: t("agentConfig.adbpgConfig.dbnameRequired"),
                },
              ]}
            >
              <Input
                placeholder={t("agentConfig.adbpgConfig.dbnamePlaceholder")}
              />
            </Form.Item>
            <Form.Item>
              <Button
                type="default"
                loading={testing}
                onClick={handleTestConnection}
              >
                {t("agentConfig.adbpgConfig.testConnection")}
              </Button>
              {testResult && (
                <Alert
                  style={{ marginTop: 8 }}
                  type={testResult.type}
                  message={testResult.message}
                  showIcon
                  closable
                  onClose={() => setTestResult(null)}
                />
              )}
            </Form.Item>
          </Card>

          {/* LLM configuration for adbpg_llm_memory.config() */}
          <Card
            type="inner"
            title={t("agentConfig.adbpgConfig.llmConfigTitle")}
            style={{ marginBottom: 16 }}
          >
            <Form.Item
              label={t("agentConfig.adbpgConfig.llmModel")}
              name={["adbpg", "llm_model"]}
              rules={[
                {
                  required: true,
                  message: t("agentConfig.adbpgConfig.llmModelRequired"),
                },
              ]}
            >
              <Input placeholder="e.g. qwen-plus" />
            </Form.Item>
            <Form.Item
              label={t("agentConfig.adbpgConfig.llmApiKey")}
              name={["adbpg", "llm_api_key"]}
              rules={[
                {
                  required: true,
                  message: t("agentConfig.adbpgConfig.llmApiKeyRequired"),
                },
              ]}
            >
              <Input.Password
                placeholder={t("agentConfig.adbpgConfig.llmApiKeyPlaceholder")}
              />
            </Form.Item>
            <Form.Item
              label={t("agentConfig.adbpgConfig.llmBaseUrl")}
              name={["adbpg", "llm_base_url"]}
              rules={[
                {
                  required: true,
                  message: t("agentConfig.adbpgConfig.llmBaseUrlRequired"),
                },
              ]}
            >
              <Input placeholder="e.g. https://dashscope.aliyuncs.com/compatible-mode/v1" />
            </Form.Item>
          </Card>

          {/* Embedding model configuration for vector search */}
          <Card
            type="inner"
            title={t("agentConfig.adbpgConfig.embeddingConfigTitle")}
            style={{ marginBottom: 16 }}
          >
            <Form.Item
              label={t("agentConfig.adbpgConfig.embeddingModel")}
              name={["adbpg", "embedding_model"]}
              tooltip={t("agentConfig.adbpgConfig.embeddingModelTooltip")}
              initialValue="text-embedding-v4"
            >
              <Input placeholder="text-embedding-v4" />
            </Form.Item>
            <Form.Item
              label={t("agentConfig.adbpgConfig.embeddingApiKey")}
              name={["adbpg", "embedding_api_key"]}
              rules={[
                {
                  required: true,
                  message: t("agentConfig.adbpgConfig.embeddingApiKeyRequired"),
                },
              ]}
            >
              <Input.Password
                placeholder={t(
                  "agentConfig.adbpgConfig.embeddingApiKeyPlaceholder",
                )}
              />
            </Form.Item>
            <Form.Item
              label={t("agentConfig.adbpgConfig.embeddingBaseUrl")}
              name={["adbpg", "embedding_base_url"]}
              rules={[
                {
                  required: true,
                  message: t(
                    "agentConfig.adbpgConfig.embeddingBaseUrlRequired",
                  ),
                },
              ]}
            >
              <Input placeholder="e.g. https://dashscope.aliyuncs.com/compatible-mode/v1" />
            </Form.Item>
            <Form.Item
              label={t("agentConfig.adbpgConfig.embeddingDims")}
              name={["adbpg", "embedding_dims"]}
              tooltip={t("agentConfig.adbpgConfig.embeddingDimsTooltip")}
              initialValue={1024}
            >
              <InputNumber
                style={{ width: "100%" }}
                min={1}
                placeholder="1024"
              />
            </Form.Item>
          </Card>
        </>
      )}

      {/* Optional tuning: search timeout, pool config */}
      <Card
        type="inner"
        title={t("agentConfig.adbpgConfig.optionalConfigTitle")}
      >
        <Form.Item
          label={t("agentConfig.adbpgConfig.searchTimeout")}
          name={["adbpg", "search_timeout"]}
          tooltip={t("agentConfig.adbpgConfig.searchTimeoutTooltip")}
        >
          <InputNumber
            style={{ width: "100%" }}
            min={0.1}
            step={0.5}
            placeholder="10.0"
          />
        </Form.Item>
        {apiMode !== "rest" && (
          <>
            <Form.Item
              label={t("agentConfig.adbpgConfig.poolMinconn")}
              name={["adbpg", "pool_minconn"]}
              tooltip={t("agentConfig.adbpgConfig.poolMinconnTooltip")}
            >
              <InputNumber
                style={{ width: "100%" }}
                min={1}
                max={100}
                placeholder="2"
              />
            </Form.Item>
            <Form.Item
              label={t("agentConfig.adbpgConfig.poolMaxconn")}
              name={["adbpg", "pool_maxconn"]}
              tooltip={t("agentConfig.adbpgConfig.poolMaxconnTooltip")}
            >
              <InputNumber
                style={{ width: "100%" }}
                min={1}
                max={200}
                placeholder="10"
              />
            </Form.Item>
          </>
        )}
        <Form.Item
          label={t("agentConfig.adbpgConfig.toolCompactMode")}
          name={["adbpg", "tool_compact_mode"]}
          tooltip={t("agentConfig.adbpgConfig.toolCompactModeTooltip")}
        >
          <Select>
            <Select.Option value="summarize">summarize</Select.Option>
            <Select.Option value="truncate">truncate</Select.Option>
          </Select>
        </Form.Item>
        <Form.Item
          label={t("agentConfig.adbpgConfig.toolCompactMaxLen")}
          name={["adbpg", "tool_compact_max_len"]}
          tooltip={t("agentConfig.adbpgConfig.toolCompactMaxLenTooltip")}
        >
          <InputNumber
            style={{ width: "100%" }}
            min={100}
            step={100}
            placeholder="500"
          />
        </Form.Item>
        <Form.Item
          label={t("agentConfig.adbpgConfig.memoryIsolation")}
          name={["adbpg", "memory_isolation"]}
          valuePropName="checked"
          tooltip={t("agentConfig.adbpgConfig.memoryIsolationTooltip")}
        >
          <Switch />
        </Form.Item>
        <Form.Item
          label={t("agentConfig.adbpgConfig.userIsolation")}
          name={["adbpg", "user_isolation"]}
          valuePropName="checked"
          tooltip={t("agentConfig.adbpgConfig.userIsolationTooltip")}
        >
          <Switch />
        </Form.Item>
        {userIsolation && (
          <Form.Item
            label={t("agentConfig.adbpgConfig.userIsolationId")}
            name={["adbpg", "user_isolation_id"]}
            tooltip={t("agentConfig.adbpgConfig.userIsolationIdTooltip")}
            rules={[
              {
                required: true,
                message: t("agentConfig.adbpgConfig.userIsolationIdRequired"),
              },
            ]}
          >
            <Input
              placeholder={t(
                "agentConfig.adbpgConfig.userIsolationIdPlaceholder",
              )}
            />
          </Form.Item>
        )}
        <Form.Item
          label={t("agentConfig.adbpgConfig.runIsolation")}
          name={["adbpg", "run_isolation"]}
          valuePropName="checked"
          tooltip={t("agentConfig.adbpgConfig.runIsolationTooltip")}
        >
          <Switch />
        </Form.Item>
        <Form.Item
          label={t("agentConfig.adbpgConfig.stripLocalMemory")}
          name={["adbpg", "strip_local_memory_instructions"]}
          initialValue={true}
          valuePropName="checked"
          tooltip={t("agentConfig.adbpgConfig.stripLocalMemoryTooltip")}
        >
          <Switch />
        </Form.Item>
      </Card>

      {/* Custom fact extraction prompt (SQL mode only) */}
      {apiMode !== "rest" && (
        <Card
          type="inner"
          title={t("agentConfig.adbpgConfig.customPromptTitle")}
          style={{ marginTop: 16 }}
        >
          <Form.Item
            label={t("agentConfig.adbpgConfig.customPromptEnabled")}
            tooltip={t("agentConfig.adbpgConfig.customPromptTooltip")}
          >
            <Switch
              checked={customPromptOn}
              onChange={(checked) => {
                setCustomPromptOn(checked);
                if (!checked) {
                  form.setFieldValue(
                    ["adbpg", "custom_fact_extraction_prompt"],
                    "",
                  );
                }
              }}
            />
          </Form.Item>
          {customPromptOn && (
            <Form.Item
              label={t("agentConfig.adbpgConfig.customPromptLabel")}
              name={["adbpg", "custom_fact_extraction_prompt"]}
              tooltip={t("agentConfig.adbpgConfig.customPromptInputTooltip")}
              rules={[
                {
                  required: true,
                  message: t("agentConfig.adbpgConfig.customPromptRequired"),
                },
              ]}
            >
              <Input.TextArea
                rows={6}
                placeholder={t(
                  "agentConfig.adbpgConfig.customPromptPlaceholder",
                )}
              />
            </Form.Item>
          )}
        </Card>
      )}
    </Card>
  );
}
