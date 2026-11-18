import type { ReactNode } from "react";
import { AutoComplete, Form, Input } from "antd";
import { useTranslation } from "react-i18next";

export function ModelIdentityFields({
  options,
  loading = false,
  idField = "id",
  idSuffix,
  nameLabel,
  onSelect,
}: {
  options: { value: string; label?: ReactNode }[];
  loading?: boolean;
  idField?: string;
  idSuffix?: ReactNode;
  nameLabel?: string;
  onSelect?: (value: string) => void;
}) {
  const { t } = useTranslation();
  return (
    <>
      <Form.Item
        name={idField}
        label={t("models.modelIdLabel")}
        rules={[{ required: true, message: t("models.modelIdLabel") }]}
        style={{ marginBottom: 12 }}
      >
        <AutoComplete
          placeholder={t("models.modelIdPlaceholder")}
          options={options}
          onSelect={onSelect}
          filterOption={(inputValue: string, option?: { value?: string }) =>
            option?.value?.toLowerCase().includes(inputValue.toLowerCase()) ??
            false
          }
          notFoundContent={
            loading
              ? t("common.loading")
              : t("models.modelDiscoveryUnavailableHint")
          }
        >
          <Input suffix={idSuffix} />
        </AutoComplete>
      </Form.Item>
      <Form.Item
        name="name"
        label={nameLabel ?? t("models.modelNameLabel")}
        style={{ marginBottom: 12 }}
      >
        <Input placeholder={t("models.modelNamePlaceholder")} />
      </Form.Item>
    </>
  );
}
