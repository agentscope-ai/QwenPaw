import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Input, Modal, message } from "antd";
import { saveAsTemplate } from "@/api/creator";

interface SaveAsTemplateDialogProps {
  open: boolean;
  onClose: () => void;
  projectId: string;
}

export default function SaveAsTemplateDialog({
  open,
  onClose,
  projectId,
}: SaveAsTemplateDialogProps) {
  const { t } = useTranslation();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [iconEmoji, setIconEmoji] = useState("\u2728");
  const [saving, setSaving] = useState(false);

  async function handleSave() {
    if (!name.trim()) return;
    setSaving(true);
    try {
      await saveAsTemplate({
        projectId,
        name: name.trim(),
        description: description.trim(),
        iconEmoji: iconEmoji || "\u2728",
      });
      message.success(t("home.saveAsTemplateSuccess"));
      setName("");
      setDescription("");
      setIconEmoji("\u2728");
      onClose();
    } catch {
      message.error(t("home.saveAsTemplateFailed"));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      title={t("home.saveAsTemplateTitle")}
      open={open}
      onOk={handleSave}
      onCancel={onClose}
      confirmLoading={saving}
      okButtonProps={{ disabled: !name.trim() }}
      destroyOnClose
    >
      <div className="flex flex-col gap-3 py-2">
        <div>
          <label className="mb-1 block text-xs font-medium">
            {t("home.saveAsTemplateName")}
          </label>
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={t("home.saveAsTemplateNamePlaceholder")}
            maxLength={50}
          />
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium">
            {t("home.saveAsTemplateDesc")}
          </label>
          <Input.TextArea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder={t("home.saveAsTemplateDescPlaceholder")}
            rows={2}
            maxLength={200}
          />
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium">
            {t("home.saveAsTemplateIcon")}
          </label>
          <Input
            value={iconEmoji}
            onChange={(e) => setIconEmoji(e.target.value)}
            maxLength={4}
            className="w-20"
          />
        </div>
      </div>
    </Modal>
  );
}
