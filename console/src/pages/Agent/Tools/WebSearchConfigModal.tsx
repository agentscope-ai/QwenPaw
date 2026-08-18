import { useEffect, useState } from "react";
import { Spin, Typography } from "antd";
import { Modal, Form, Input, Select } from "@agentscope-ai/design";
import api from "../../../api";
import { useTranslation } from "react-i18next";
import type { ToolInfo } from "../../../api/modules/tools";

/**
 * web_search-specific config modal.
 *
 * Deliberately not driven by ``tool.config_fields`` like the generic
 * ``ToolConfigModal``: web_search only ever has two fixed fields
 * (provider select + api_key password), and the api_key field must hide
 * itself when provider is "tavily" (keyless backend). Keeping this as a
 * standalone component means the shared ``ToolConfigModal`` — used by all
 * plugin tools — is never touched by web_search-specific behavior.
 */
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
  const [saving, setSaving] = useState(false);
  const [loadingConfig, setLoadingConfig] = useState(false);
  const { t } = useTranslation();
  const providerValue = Form.useWatch("provider", form);

  useEffect(() => {
    if (!visible || !tool) return;
    form.resetFields();
    setLoadingConfig(true);
    let cancelled = false;
    api
      .getToolConfig(tool.name)
      .then((config) => {
        if (!cancelled) form.setFieldsValue(config || {});
      })
      .catch(() => {
        // Leave form empty on error
      })
      .finally(() => {
        if (!cancelled) setLoadingConfig(false);
      });
    return () => {
      cancelled = true;
    };
  }, [visible, tool.name, form]);

  // When the user switches provider inside the modal, fetch that provider's
  // credential slot so an existing key is shown instead of a blank field
  // (which would otherwise be treated as "clear the key" on save).
  useEffect(() => {
    if (!visible || !tool) return;
    if (!providerValue || providerValue === "tavily") {
      // Keyless provider: drop any leftover key from the form store so it
      // cannot be submitted into the wrong provider's credential slot.
      form.setFieldValue("api_key", undefined);
      return;
    }
    let cancelled = false;
    setLoadingConfig(true);
    api
      .getToolConfig(tool.name, { provider: providerValue })
      .then((config) => {
        if (cancelled) return;
        form.setFieldsValue({ api_key: config?.api_key ?? "" });
      })
      .catch(() => {
        // Keep current field value on error
      })
      .finally(() => {
        if (!cancelled) setLoadingConfig(false);
      });
    return () => {
      cancelled = true;
    };
  }, [visible, tool.name, providerValue, form]);

  const handleSave = async () => {
    try {
      const values = await form.validateFields();
      if (values.provider === "tavily") {
        delete values.api_key;
      }
      setSaving(true);
      await onSave(values);
      onClose();
    } catch (error) {
      console.error("Failed to save config:", error);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      title={`${t("tools.configure")} - ${tool.name}`}
      open={visible}
      onCancel={onClose}
      onOk={handleSave}
      confirmLoading={saving || loadingConfig}
      okButtonProps={{ disabled: loadingConfig }}
      okText={t("common.save")}
      cancelText={t("common.cancel")}
    >
      <Spin spinning={loadingConfig}>
        <Form form={form} layout="vertical">
          <Form.Item
            name="provider"
            label={t("tools.webSearchProviderLabel")}
            initialValue="tavily"
          >
            <Select>
              <Select.Option value="tavily">tavily</Select.Option>
              <Select.Option value="anysearch">anysearch</Select.Option>
            </Select>
          </Form.Item>
          {providerValue !== "tavily" && (
            <>
              <Form.Item name="api_key" label={t("tools.webSearchApiKeyLabel")}>
                <Input.Password autoComplete="off" />
              </Form.Item>
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
            </>
          )}
        </Form>
      </Spin>
    </Modal>
  );
}
