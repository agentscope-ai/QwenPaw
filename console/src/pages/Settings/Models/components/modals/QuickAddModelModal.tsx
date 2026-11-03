import { useState } from "react";
import { Button, Form, Input, Modal, Select } from "@agentscope-ai/design";
import type { ProviderInfo } from "../../../../api/types/provider";
import api from "../../../../api";
import { useTranslation } from "react-i18next";
import { useAppMessage } from "../../../../../hooks/useAppMessage";

interface QuickAddModelModalProps {
  open: boolean;
  providers: ProviderInfo[];
  onClose: () => void;
  onSaved: () => void;
}

export function QuickAddModelModal({
  open,
  providers,
  onClose,
  onSaved,
}: QuickAddModelModalProps) {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [form] = Form.useForm();
  const [saving, setSaving] = useState(false);
  const [selectedProviderId, setSelectedProviderId] = useState<
    string | undefined
  >(undefined);

  const configuredProviders = providers.filter(
    (p) => p.api_key || p.require_api_key === false || p.supports_oauth,
  );

  const handleAdd = async () => {
    try {
      const values = await form.validateFields();
      const id = values.id.trim();
      const name = values.name?.trim() || id;

      if (!selectedProviderId) {
        message.error(t("models.quickAddNoProvider"));
        return;
      }

      const existing = [
        ...(configuredProviders.find((p) => p.id === selectedProviderId)
          ?.models ?? []),
        ...(configuredProviders.find((p) => p.id === selectedProviderId)
          ?.extra_models ?? []),
      ];
      if (existing.some((m) => m.id === id)) {
        message.warning(t("models.quickAddModelExists", { id }));
        return;
      }

      setSaving(true);
      await api.addModel(selectedProviderId, { id, name });
      message.success(t("models.quickAddSaved", { name }));
      form.resetFields();
      onSaved();
      onClose();
    } catch (error) {
      if (error && typeof error === "object" && "errorFields" in error) return;
      message.error(t("models.quickAddFailed"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      title={t("models.quickAddTitle")}
      open={open}
      onCancel={onClose}
      footer={null}
      width={480}
    >
      <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
        <Form.Item
          name="providerId"
          label={t("models.quickAddSelectProvider")}
          rules={[
            { required: true, message: t("models.quickAddSelectProvider") },
          ]}
        >
          <Select
            placeholder={
              configuredProviders.length > 0
                ? t("models.quickAddSelectProvider")
                : t("models.quickAddNoProvider")
            }
            options={configuredProviders.map((p) => ({
              value: p.id,
              label: p.name,
            }))}
            onChange={(v) => setSelectedProviderId(v)}
          />
        </Form.Item>
        <Form.Item
          name="id"
          label={t("models.quickAddModelId")}
          rules={[{ required: true, message: t("models.modelIdLabel") }]}
        >
          <Input placeholder={t("models.quickAddModelIdPlaceholder")} />
        </Form.Item>
        <Form.Item name="name" label={t("models.quickAddModelName")}>
          <Input placeholder={t("models.quickAddModelNamePlaceholder")} />
        </Form.Item>
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
          <Button onClick={onClose}>{t("models.cancel")}</Button>
          <Button
            type="primary"
            loading={saving}
            disabled={!selectedProviderId}
            onClick={handleAdd}
          >
            {t("models.quickAddAddModel")}
          </Button>
        </div>
      </Form>
    </Modal>
  );
}
