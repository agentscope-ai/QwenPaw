import { useState, useEffect } from "react";
import { Modal, Input, Button } from "@agentscope-ai/design";
import { Typography } from "antd";
import { useTranslation } from "react-i18next";

interface GlobalAuthKeyModalProps {
  open: boolean;
  initialValue: string;
  saving: boolean;
  onClose: () => void;
  onSave: (value: string) => void;
}

export function GlobalAuthKeyModal({
  open,
  initialValue,
  saving,
  onClose,
  onSave,
}: GlobalAuthKeyModalProps) {
  const { t } = useTranslation();
  const [value, setValue] = useState(initialValue);

  useEffect(() => {
    if (open) {
      setValue(initialValue);
    }
  }, [open, initialValue]);

  const handleSave = () => {
    onSave(value);
  };

  return (
    <Modal
      title={t("agentSACP.globalAuthKeyTitle")}
      open={open}
      onCancel={onClose}
      destroyOnClose
      footer={
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
          <Button onClick={onClose}>{t("common.cancel")}</Button>
          <Button type="primary" loading={saving} onClick={handleSave}>
            {t("common.save")}
          </Button>
        </div>
      }
    >
      <div style={{ marginBottom: 16 }}>
        <Typography.Text type="secondary">
          {t("agentSACP.globalAuthKeyDesc")}
        </Typography.Text>
      </div>
      <Input.Password
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder={t("agentSACP.globalAuthKeyPlaceholder")}
        style={{ width: "100%" }}
      />
    </Modal>
  );
}
