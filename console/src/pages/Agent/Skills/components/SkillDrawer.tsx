import { useState, useEffect, useCallback } from "react";
import { Drawer, Form, Input, Button, message } from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import type { FormInstance } from "antd";
import type { SkillSpec } from "../../../../api/types";
import { MarkdownCopy } from "../../../../components/MarkdownCopy/MarkdownCopy";

/**
 * Parse frontmatter from content string.
 * Returns an object with parsed key-value pairs, or null if no valid frontmatter found.
 */
function parseFrontmatter(content: string): Record<string, string> | null {
  const trimmed = content.trim();
  if (!trimmed.startsWith("---")) return null;

  const endIndex = trimmed.indexOf("---", 3);
  if (endIndex === -1) return null;

  const frontmatterBlock = trimmed.slice(3, endIndex).trim();
  if (!frontmatterBlock) return null;

  const result: Record<string, string> = {};
  for (const line of frontmatterBlock.split("\n")) {
    const colonIndex = line.indexOf(":");
    if (colonIndex > 0) {
      const key = line.slice(0, colonIndex).trim();
      const value = line.slice(colonIndex + 1).trim();
      result[key] = value;
    }
  }
  return result;
}

interface SkillDrawerProps {
  open: boolean;
  editingSkill: SkillSpec | null;
  form: FormInstance<SkillSpec>;
  onClose: () => void;
  onSubmit: (values: SkillSpec) => void;
  onContentChange?: (content: string) => void;
}

export function SkillDrawer({
  open,
  editingSkill,
  form,
  onClose,
  onSubmit,
  onContentChange,
}: SkillDrawerProps) {
  const { t } = useTranslation();
  const [showMarkdown, setShowMarkdown] = useState(true);
  const [contentValue, setContentValue] = useState("");

  const validateFrontmatter = useCallback(
    (_: unknown, value: string) => {
      const content = contentValue || value;
      if (!content || !content.trim()) {
        return Promise.reject(new Error(t("skills.pleaseInputContent")));
      }
      const fm = parseFrontmatter(content);
      if (!fm) {
        return Promise.reject(new Error(t("skills.frontmatterRequired")));
      }
      if (!fm.name) {
        return Promise.reject(new Error(t("skills.frontmatterNameRequired")));
      }
      if (!fm.description) {
        return Promise.reject(
          new Error(t("skills.frontmatterDescriptionRequired")),
        );
      }
      return Promise.resolve();
    },
    [contentValue, t],
  );

  useEffect(() => {
    if (editingSkill) {
      setContentValue(editingSkill.content);
      form.setFieldsValue({
        name: editingSkill.name,
        content: editingSkill.content,
      });
    } else {
      setContentValue("");
      form.resetFields();
    }
  }, [editingSkill, form]);

  const handleSubmit = (values: { name: string; content: string }) => {
    if (editingSkill) {
      message.warning(t("skills.editNotSupported"));
      onClose();
    } else {
      onSubmit({
        ...values,
        content: contentValue || values.content,
        source: "",
        path: "",
      });
    }
  };

  const handleContentChange = (content: string) => {
    setContentValue(content);
    form.setFieldsValue({ content });
    // Re-validate the content field to give real-time feedback
    form.validateFields(["content"]).catch(() => {});
    if (onContentChange) {
      onContentChange(content);
    }
  };

  return (
    <Drawer
      width={520}
      placement="right"
      title={editingSkill ? t("skills.viewSkill") : t("skills.createSkill")}
      open={open}
      onClose={onClose}
      destroyOnClose
    >
      <Form form={form} layout="vertical" onFinish={handleSubmit}>
        {!editingSkill && (
          <>
            <Form.Item
              name="name"
              label="Name"
              rules={[{ required: true, message: t("skills.pleaseInputName") }]}
            >
              <Input placeholder={t("skills.skillNamePlaceholder")} />
            </Form.Item>

            <Form.Item
              name="content"
              label="Content"
              rules={[{ required: true, validator: validateFrontmatter }]}
            >
              <MarkdownCopy
                content={contentValue}
                showMarkdown={showMarkdown}
                onShowMarkdownChange={setShowMarkdown}
                editable={true}
                onContentChange={handleContentChange}
                textareaProps={{
                  placeholder: t("skills.contentPlaceholder"),
                  rows: 12,
                }}
              />
            </Form.Item>

            <Form.Item>
              <div
                style={{
                  display: "flex",
                  justifyContent: "flex-end",
                  gap: 8,
                  marginTop: 16,
                }}
              >
                <Button onClick={onClose}>{t("common.cancel")}</Button>
                <Button type="primary" htmlType="submit">
                  {t("skills.create")}
                </Button>
              </div>
            </Form.Item>
          </>
        )}

        {editingSkill && (
          <>
            <Form.Item name="name" label="name">
              <Input disabled />
            </Form.Item>

            <Form.Item name="content" label="Content">
              <MarkdownCopy
                content={editingSkill.content}
                showMarkdown={showMarkdown}
                onShowMarkdownChange={setShowMarkdown}
                textareaProps={{
                  disabled: true,
                  rows: 12,
                }}
              />
            </Form.Item>

            <Form.Item name="source" label="Source">
              <Input disabled />
            </Form.Item>

            <Form.Item name="path" label="Path">
              <Input disabled />
            </Form.Item>

            <div
              style={{
                padding: 12,
                backgroundColor: "#fffbe6",
                border: "1px solid #ffe58f",
                borderRadius: 4,
                marginTop: 16,
              }}
            >
              <p style={{ margin: 0, fontSize: 12, color: "#8c8c8c" }}>
                {t("skills.editNote")}
              </p>
            </div>
          </>
        )}
      </Form>
    </Drawer>
  );
}
