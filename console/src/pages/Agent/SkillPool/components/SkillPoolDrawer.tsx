import { useCallback, useState } from "react";
import { Button, Drawer, Form, Input } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import type { PoolSkillSpec } from "../../../../api/types";
import {
  getPoolBuiltinStatusLabel,
  getPoolBuiltinStatusTone,
} from "../../Skills/components";
import { MarkdownCopy } from "../../../../components/MarkdownCopy/MarkdownCopy";
import type { PoolMode } from "../hooks/useSkillPool";
import styles from "../index.module.less";

interface SkillPoolDrawerProps {
  mode: PoolMode | null;
  activeSkill: PoolSkillSpec | null;
  onClose: () => void;
  onSave: (
    formValues: { name: string; content: string },
    drawerContent: string,
    configText: string,
    setFormFieldsValue: (v: { name: string }) => void,
  ) => Promise<boolean>;
  validateFrontmatter: (drawerContent: string, value: string) => Promise<void>;
}

export function SkillPoolDrawer({
  mode,
  activeSkill,
  onClose,
  onSave,
  validateFrontmatter,
}: SkillPoolDrawerProps) {
  const { t } = useTranslation();
  const [form] = Form.useForm();
  const [drawerContent, setDrawerContent] = useState("");
  const [showMarkdown, setShowMarkdown] = useState(true);
  const [configText, setConfigText] = useState("{}");

  // Initialize form when mode changes
  const initializeForm = useCallback(
    (skill: PoolSkillSpec | null, currentMode: PoolMode | null) => {
      if (currentMode === "edit" && skill) {
        setDrawerContent(skill.content);
        setConfigText(JSON.stringify(skill.config || {}, null, 2));
        form.setFieldsValue({
          name: skill.name,
          content: skill.content,
        });
      } else if (currentMode === "create") {
        setDrawerContent("");
        setConfigText("{}");
        form.resetFields();
        form.setFieldsValue({ name: "", content: "" });
      }
    },
    [form],
  );

  // Reset state when drawer opens
  const handleAfterOpenChange = (open: boolean) => {
    if (open) {
      initializeForm(activeSkill, mode);
    }
  };

  const handleDrawerContentChange = (content: string) => {
    setDrawerContent(content);
    form.setFieldsValue({ content });
  };

  const handleSave = async () => {
    const values = await form.validateFields().catch(() => null);
    if (!values) return;
    await onSave(values, drawerContent, configText, (v) =>
      form.setFieldsValue(v),
    );
  };

  const handleValidate = useCallback(
    (_: unknown, value: string) => validateFrontmatter(drawerContent, value),
    [drawerContent, validateFrontmatter],
  );

  return (
    <Drawer
      width={520}
      placement="right"
      title={
        mode === "edit"
          ? t("skillPool.editTitle", { name: activeSkill?.name || "" })
          : t("skillPool.createTitle")
      }
      open={mode === "create" || mode === "edit"}
      onClose={onClose}
      afterOpenChange={handleAfterOpenChange}
      destroyOnClose
      footer={
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
          <Button onClick={onClose}>{t("common.cancel")}</Button>
          <Button type="primary" onClick={handleSave}>
            {mode === "edit" ? t("common.save") : t("common.create")}
          </Button>
        </div>
      }
    >
      {mode === "edit" && activeSkill && (
        <div className={styles.metaStack} style={{ marginBottom: 16 }}>
          <div className={styles.infoSection}>
            <div className={styles.infoLabel}>{t("skillPool.status")}</div>
            <div
              className={`${styles.infoBlock} ${
                styles[getPoolBuiltinStatusTone(activeSkill.sync_status)]
              }`}
            >
              {getPoolBuiltinStatusLabel(activeSkill.sync_status, t)}
            </div>
          </div>
        </div>
      )}
      <Form form={form} layout="vertical" onFinish={handleSave}>
        <Form.Item
          name="name"
          label={t("skillPool.skillName")}
          rules={[{ required: true, message: t("skills.pleaseInputName") }]}
        >
          <Input placeholder={t("skillPool.skillNamePlaceholder")} />
        </Form.Item>

        <Form.Item
          name="content"
          label={t("common.content")}
          rules={[{ required: true, validator: handleValidate }]}
        >
          <MarkdownCopy
            content={drawerContent}
            showMarkdown={showMarkdown}
            onShowMarkdownChange={setShowMarkdown}
            editable={true}
            onContentChange={handleDrawerContentChange}
            textareaProps={{
              placeholder: t("skillPool.contentPlaceholder"),
              rows: 12,
            }}
          />
        </Form.Item>

        <Form.Item label={t("skills.config")}>
          <Input.TextArea
            rows={4}
            value={configText}
            onChange={(e) => setConfigText(e.target.value)}
            placeholder={t("skills.configPlaceholder")}
          />
        </Form.Item>
      </Form>
    </Drawer>
  );
}
