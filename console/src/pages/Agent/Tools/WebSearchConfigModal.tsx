import { SharedModal as Modal } from "@/components/interaction/SharedModal";
import { useAutoSave } from "@/hooks/useAutoSave";
import { useCallback, useEffect, useRef, useState } from "react";
import { X, ChevronDown, CircleAlert } from "lucide-react";
import { Alert, Button, Spin, Typography } from "antd";
import { Form, Input, Select } from "@agentscope-ai/design";
import api from "../../../api";
import { useTranslation } from "react-i18next";
import type { ToolInfo } from "../../../api/modules/tools";

/**
 * web_search-specific config modal.
 *
 * Deliberately not driven by ``tool.config_fields`` like the generic
 * ``ToolConfigModal``: web_search only ever has two fixed fields
 * (provider select + api_key password). The api_key field is optional for
 * every provider: tavily stays keyless when empty, anysearch may register
 * anonymously. Keeping this as a standalone component means the shared
 * ``ToolConfigModal`` — used by all plugin tools — is never touched by
 * web_search-specific behavior.
 *
 * Credential isolation: submission is allowed only when the form's
 * ``provider`` matches a successfully loaded provider slot
 * (``loadState.status === "ready"``). A failed fetch leaves an error /
 * retry UI and never writes an empty string that the backend would treat
 * as "delete key".
 */

type ConfigLoadState =
  | { status: "loading"; provider: string | null }
  | { status: "ready"; provider: string }
  // provider === null means the initial (saved-config) fetch failed;
  // retry must re-run that request, not load a hardcoded provider slot.
  | { status: "error"; provider: string | null };

export function WebSearchConfigModal({
  tool,
  visible,
  onClose,
  onSave,
}: {
  tool: ToolInfo;
  visible: boolean;
  onClose: () => void;
  onSave: (values: Record<string, unknown>) => Promise<void>;
}) {
  const [form] = Form.useForm();
  const { t } = useTranslation();
  const providerValue = Form.useWatch("provider", form);
  const [loadState, setLoadState] = useState<ConfigLoadState>({
    status: "loading",
    provider: null,
  });
  // Bump to ignore stale responses when the modal closes or a newer fetch starts.
  const fetchGen = useRef(0);

  const loadInitialConfig = useCallback(() => {
    const gen = ++fetchGen.current;
    setLoadState({ status: "loading", provider: null });
    api
      .getToolConfig(tool.name)
      .then((config) => {
        if (gen !== fetchGen.current) return;
        const provider =
          (typeof config?.provider === "string" && config.provider) || "tavily";
        form.setFieldsValue({ ...(config || {}), provider });
        setLoadState({ status: "ready", provider });
      })
      .catch(() => {
        if (gen !== fetchGen.current) return;
        // Do not force provider to "tavily" here — that would make Retry
        // load the tavily slot and let auto-save overwrite a saved
        // anysearch (or other) selection. Leave the form provider alone
        // until a successful load recovers the saved config.
        form.setFieldValue("api_key", undefined);
        setLoadState({ status: "error", provider: null });
      });
  }, [tool.name, form]);

  const loadForProvider = useCallback(
    (provider: string) => {
      const gen = ++fetchGen.current;
      setLoadState({ status: "loading", provider });
      api
        .getToolConfig(tool.name, { provider })
        .then((config) => {
          if (gen !== fetchGen.current) return;
          form.setFieldsValue({ api_key: config?.api_key ?? "" });
          setLoadState({ status: "ready", provider });
        })
        .catch(() => {
          if (gen !== fetchGen.current) return;
          // Do not set api_key to "" — backend treats empty as delete.
          form.setFieldValue("api_key", undefined);
          setLoadState({ status: "error", provider });
        });
    },
    [tool.name, form],
  );

  // Open: load the saved provider + its credential slot.
  useEffect(() => {
    if (!visible) {
      fetchGen.current += 1;
      return;
    }
    form.resetFields();
    loadInitialConfig();
    return () => {
      fetchGen.current += 1;
    };
  }, [visible, tool.name, form, loadInitialConfig]);

  // Provider switch: fetch that provider's slot once selection diverges
  // from the last successful/in-flight/error target.
  useEffect(() => {
    if (!visible) return;
    if (!providerValue) return;
    // Initial loading/retry owns provider selection until config is loaded.
    if (loadState.provider === null) return;
    // Already loading / ready / error for this provider — no auto-refetch
    // (error waits for explicit retry).
    if (loadState.provider === providerValue) return;
    loadForProvider(providerValue);
  }, [visible, providerValue, loadState, loadForProvider]);

  const canSubmit =
    loadState.status === "ready" && loadState.provider === providerValue;

  const { schedule, discard, requestClose } = useAutoSave(async () => {
    if (!canSubmit) return false;
    const values = form.getFieldsValue(true);
    try {
      await form.validateFields();
    } catch {
      return false;
    }
    await onSave(values);
  });

  useEffect(() => {
    if (canSubmit && form.isFieldsTouched()) schedule();
  }, [canSubmit, form, schedule]);

  const isAnysearch = providerValue === "anysearch";
  const isTavily = providerValue === "tavily" || !providerValue;
  const isLoading = loadState.status === "loading";
  const isError = loadState.status === "error";

  return (
    <Modal
      closeIcon={<X size={18} aria-hidden />}
      title={`${t("tools.configure")} · ${t(
        `tools.catalog.${tool.name}.name`,
        tool.name,
      )}`}
      open={visible}
      onCancel={() => {
        // Unsafe to save while loading/error or when the loaded slot
        // does not match the selected provider — discard and close.
        if (!canSubmit) {
          discard();
          onClose();
          return;
        }
        void requestClose(onClose);
      }}
      footer={null}
    >
      <Spin spinning={isLoading}>
        <Form form={form} layout="vertical" onValuesChange={schedule}>
          <Form.Item
            name="provider"
            label={t("tools.webSearchProviderLabel")}
            initialValue="tavily"
          >
            <Select
              suffixIcon={<ChevronDown size={16} aria-hidden />}
              disabled={isLoading}
            >
              <Select.Option value="tavily">tavily</Select.Option>
              <Select.Option value="anysearch">anysearch</Select.Option>
              <Select.Option value="firecrawl">firecrawl</Select.Option>
            </Select>
          </Form.Item>
          <Form.Item name="api_key" label={t("tools.webSearchApiKeyLabel")}>
            <Input.Password
              autoComplete="off"
              disabled={isLoading || isError}
            />
          </Form.Item>
          {isError && (
            <Alert
              type="error"
              showIcon
              icon={<CircleAlert size={16} aria-hidden />}
              style={{ marginBottom: 12 }}
              message={t("tools.webSearchConfigLoadError")}
              action={
                <Button
                  size="small"
                  type="link"
                  onClick={() => {
                    if (loadState.status !== "error") return;
                    // Initial failure: recover saved provider via the
                    // original config request. Provider-switch failure:
                    // reload that provider's credential slot.
                    if (loadState.provider === null) {
                      loadInitialConfig();
                    } else {
                      loadForProvider(loadState.provider);
                    }
                  }}
                >
                  {t("common.retry")}
                </Button>
              }
            />
          )}
          {isAnysearch && !isError && (
            <Typography.Text
              type="secondary"
              style={{ fontSize: 12, lineHeight: "20px", display: "block" }}
            >
              {t("tools.webSearchQuotaHintBefore")}
              <Typography.Link
                href="https://anysearch.com"
                target="_blank"
                rel="noreferrer"
              >
                anysearch.com
              </Typography.Link>
              {t("tools.webSearchQuotaHintAfter")}
            </Typography.Text>
          )}
          {isTavily && !isError && (
            <Typography.Text
              type="secondary"
              style={{ fontSize: 12, lineHeight: "20px", display: "block" }}
            >
              {t("tools.webSearchTavilyKeyHintBefore")}
              <Typography.Link
                href="https://tavily.com"
                target="_blank"
                rel="noreferrer"
              >
                tavily.com
              </Typography.Link>
              {t("tools.webSearchTavilyKeyHintAfter")}
            </Typography.Text>
          )}
        </Form>
      </Spin>
    </Modal>
  );
}
