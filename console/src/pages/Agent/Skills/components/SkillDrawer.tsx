import { useState, useEffect, useCallback, useRef } from "react";
import { Drawer, Form, Input, Button, Select } from "@agentscope-ai/design";
import { useAppMessage } from "../../../../hooks/useAppMessage";
import { useTranslation } from "react-i18next";
import { ThunderboltOutlined, StopOutlined } from "@ant-design/icons";
import type { FormInstance } from "antd";
import type { SkillSpec } from "../../../../api/types";
import { MarkdownCopy } from "../../../../components/MarkdownCopy/MarkdownCopy";
import { api } from "../../../../api";

/**
 * Parse frontmatter from content string.
 * Returns an object with parsed key-value pairs, or null if no valid frontmatter found.
 */
export function parseFrontmatter(
  content: string,
): Record<string, string> | null {
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

const CHANNEL_OPTIONS = [
  { label: "all", value: "all" },
  { label: "console", value: "console" },
  { label: "discord", value: "discord" },
  { label: "telegram", value: "telegram" },
  { label: "dingtalk", value: "dingtalk" },
  { label: "feishu", value: "feishu" },
  { label: "imessage", value: "imessage" },
  { label: "qq", value: "qq" },
  { label: "mattermost", value: "mattermost" },
  { label: "wecom", value: "wecom" },
  { label: "mqtt", value: "mqtt" },
];

export interface SkillDrawerFormValues {
  name: string;
  description?: string;
  content: string;
  enabled?: boolean;
  channels?: string[];
  source?: string;
  config?: Record<string, unknown>;
}

interface SkillDrawerProps {
  open: boolean;
  editingSkill: SkillSpec | null;
  form: FormInstance<SkillDrawerFormValues>;
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
  const { t, i18n } = useTranslation();
  const [showMarkdown, setShowMarkdown] = useState(true);
  const [contentValue, setContentValue] = useState("");
  const [optimizing, setOptimizing] = useState(false);
  const abortControllerRef = useRef<AbortController | null>(null);
  const [configText, setConfigText] = useState("{}");
  const [configError, setConfigError] = useState("");
  const { message } = useAppMessage();

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
      const channels = editingSkill.channels || ["all"];
      const fallbackConfigText = JSON.stringify(
        editingSkill.config || {},
        null,
        2,
      );
      setContentValue(editingSkill.content);
      setConfigText(fallbackConfigText);
      form.setFieldsValue({
        name: editingSkill.name,
        content: editingSkill.content,
        channels,
        source: editingSkill.source,
      });
      setConfigError("");
      let active = true;
      api
        .getSkillConfig(editingSkill.name)
        .then((res) => {
          if (!active) return;
          setConfigText(JSON.stringify(res.config || {}, null, 2));
        })
        .catch(() => {
          if (!active) return;
          setConfigText(fallbackConfigText);
        });
      return () => {
        active = false;
      };
    } else {
      setContentValue("");
      setConfigText("{}");
      setConfigError("");
      form.resetFields();
    }
  }, [editingSkill, form, t]);

  const handleSubmit = async (values: SkillDrawerFormValues) => {
    let parsedConfig: Record<string, unknown> | undefined;
    const trimmed = configText.trim();
    if (!trimmed) {
      parsedConfig = {};
    } else {
      try {
        parsedConfig = JSON.parse(trimmed);
        setConfigError("");
      } catch {
        setConfigError(t("skills.configInvalidJson"));
        return;
      }
    }
    onSubmit({
      ...editingSkill,
      ...values,
      content: contentValue || values.content,
      source: editingSkill?.source || "",
      config: parsedConfig,
    });
  };

  const handleContentChange = (content: string) => {
    setContentValue(content);
    form.setFieldsValue({ content });
    form.validateFields(["content"]).catch(() => {});
    if (onContentChange) {
      onContentChange(content);
    }
  };

  const handleOptimize = async () => {
    if (!contentValue.trim()) {
      message.warning(t("skills.noContentToOptimize"));
      return;
    }

    setOptimizing(true);
    abortControllerRef.current = new AbortController();
    const originalContent = contentValue;
    setContentValue(""); // Clear content for streaming output

    try {
      await api.streamOptimizeSkill(
        originalContent,
        (textChunk) => {
          setContentValue((prev) => {
            const newContent = prev + textChunk;
            form.setFieldsValue({ content: newContent });
            return newContent;
          });
        },
        abortControllerRef.current.signal,
        i18n.language, // Pass current language to API
      );
      message.success(t("skills.optimizeSuccess"));
    } catch (error: unknown) {
      const aborted =
        error instanceof DOMException && error.name === "AbortError";
      if (!aborted) {
        message.error(
          error instanceof Error ? error.message : t("skills.optimizeFailed"),
        );
      }
    } finally {
      setOptimizing(false);
      abortControllerRef.current = null;
    }
  };

  const handleStopOptimize = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      setOptimizing(false);
      abortControllerRef.current = null;
    }
  };

  const drawerFooter = !editingSkill ? (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        width: "100%",
      }}
    >
      <div>
        {!optimizing ? (
          <Button
            type="default"
            icon={<ThunderboltOutlined />}
            onClick={handleOptimize}
            disabled={!contentValue.trim()}
          >
            {t("skills.optimizeWithAI")}
          </Button>
        ) : (
          <Button
            type="default"
            danger
            icon={<StopOutlined />}
            onClick={handleStopOptimize}
          >
            {t("skills.stopOptimize")}
          </Button>
        )}
      </div>
      <div style={{ display: "flex", gap: 8 }}>
        <Button onClick={onClose}>{t("common.cancel")}</Button>
        <Button type="primary" onClick={() => form.submit()}>
          {t("skills.create")}
        </Button>
      </div>
    </div>
  ) : (
    <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
      <Button onClick={onClose}>{t("common.cancel")}</Button>
      <Button type="primary" onClick={() => form.submit()}>
        {t("common.save")}
      </Button>
    </div>
  );

  return (
    <Drawer
      width={520}
      placement="right"
      title={editingSkill ? t("skills.viewSkill") : t("skills.createSkill")}
      open={open}
      onClose={onClose}
      destroyOnClose
      footer={drawerFooter}
    >
      <Form form={form} layout="vertical" onFinish={handleSubmit}>
        {!editingSkill ? (
          <Form.Item
            name="name"
            label="Name"
            rules={[{ required: true, message: t("skills.pleaseInputName") }]}
          >
            <Input placeholder={t("skills.skillNamePlaceholder")} />
          </Form.Item>
        ) : (
          <Form.Item name="name" label="Name">
            <Input />
          </Form.Item>
        )}

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
              ...(!editingSkill && {
                placeholder: t("skills.contentPlaceholder"),
              }),
              rows: 12,
            }}
          />
        </Form.Item>

        <Form.Item name="channels" label={t("skills.channels")}>
          <Select mode="multiple" options={CHANNEL_OPTIONS} />
        </Form.Item>

        <Form.Item
          label={t("skills.config")}
          validateStatus={configError ? "error" : undefined}
          help={configError || undefined}
        >
          <Input.TextArea
            rows={4}
            value={configText}
            onChange={(e) => {
              setConfigText(e.target.value);
              setConfigError("");
            }}
            placeholder={t("skills.configPlaceholder")}
          />
        </Form.Item>

        {editingSkill && (
          <>
            <Form.Item name="source" label={t("skills.type")}>
              <Input disabled />
            </Form.Item>
          </>
        )}
      </Form>
    </Drawer>
  );
}
