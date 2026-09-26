import { useAutoSave } from "@/hooks/useAutoSave";
import { SettingsDrawer as Drawer } from "@/components/interaction/SettingsDrawer";
import {
  Collapse,
  Form,
  Input,
  Switch,
  Button,
  Select,
  InputNumber,
} from "@agentscope-ai/design";
import { ChevronRight, Link as LinkOutlined } from "lucide-react";
import type { FormInstance } from "antd";
import { useTranslation } from "react-i18next";
import {
  ACP_DEFAULT_STDIO_BUFFER_LIMIT_BYTES,
  type ACPAgentConfig,
  type ACPToolParseMode,
} from "../../../../api/types";
import { getWebsiteLang } from "../../../../layouts/constants";
import styles from "./ACPDrawer.module.less";
import { openExternalLink } from "../../../../utils/openExternalLink";

interface ACPDrawerProps {
  surfaceId?: string;
  open: boolean;
  activeKey: string | null;
  isCreateMode?: boolean;
  form: FormInstance<Record<string, unknown>>;
  saving: boolean;
  initialValues?: ACPAgentConfig;
  canEditKey?: boolean;
  canDelete?: boolean;
  onClose: () => void;
  onSubmit: (
    values: Record<string, unknown>,
  ) => boolean | void | Promise<boolean | void>;
  onDelete?: () => void;
}

const TOOL_PARSE_MODE_OPTIONS: { value: ACPToolParseMode; label: string }[] = [
  { value: "call_title", label: "call_title" },
  { value: "update_detail", label: "update_detail" },
  { value: "call_detail", label: "call_detail" },
];

const ACP_DOC_SECTION_HASH = {
  zh: "如何配置外部-runner",
  en: "How-to-configure-external-runners",
} as const;

function getACPDocsUrl(lang: string): string {
  const websiteLang = getWebsiteLang(lang);
  const hash =
    websiteLang === "zh" ? ACP_DOC_SECTION_HASH.zh : ACP_DOC_SECTION_HASH.en;
  return `https://qwenpaw.agentscope.io/docs/acp-integration?lang=${websiteLang}#${hash}`;
}

function findInvalidEnvLine(value: unknown): string | null {
  const lines = String(value || "")
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean);

  for (const line of lines) {
    const index = line.indexOf("=");
    if (index <= 0 || !line.slice(0, index).trim()) {
      return line;
    }
  }
  return null;
}

export function ACPDrawer({
  open,
  surfaceId,
  activeKey,
  isCreateMode = false,
  form,
  saving,
  initialValues,
  canEditKey = false,
  canDelete = false,
  onClose,
  onSubmit,
  onDelete,
}: ACPDrawerProps) {
  const { t, i18n } = useTranslation();
  const { schedule, flush } = useAutoSave(async () => {
    if (isCreateMode) return;
    const values = form.getFieldsValue(true);
    try {
      await form.validateFields();
    } catch {
      return false;
    }
    return await onSubmit(values);
  });

  return (
    <Drawer
      surfaceId={surfaceId}
      title={
        isCreateMode
          ? t("acp.createTitle")
          : activeKey
          ? `${t("acp.editTitle")}: ${activeKey}`
          : t("acp.editTitle")
      }
      open={open}
      onClose={() => {
        void flush().then((saved) => {
          if (saved) onClose();
        });
      }}
      width={640}
      footer={
        canDelete || isCreateMode ? (
          <div style={{ display: "flex", justifyContent: "space-between" }}>
            <div>
              {canDelete ? (
                <Button danger onClick={onDelete}>
                  {t("common.delete")}
                </Button>
              ) : null}
            </div>
            {isCreateMode && (
              <div
                style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}
              >
                <Button onClick={onClose}>{t("common.cancel")}</Button>
                <Button
                  type="primary"
                  loading={saving}
                  onClick={() => form.submit()}
                >
                  {t("common.create")}
                </Button>
              </div>
            )}
          </div>
        ) : undefined
      }
      destroyOnHidden
    >
      <Form
        form={form}
        layout="vertical"
        className={styles.form}
        initialValues={initialValues}
        onValuesChange={isCreateMode ? undefined : schedule}
        onFinish={onSubmit}
      >
        <Form.Item
          name="agentKey"
          hidden={!canEditKey}
          label={t("acp.agentKey")}
          rules={[
            { required: true, message: t("acp.agentKeyRequired") },
            {
              pattern: /^[A-Za-z0-9_-]+$/,
              message: t("acp.agentKeyInvalid"),
            },
          ]}
        >
          <Input placeholder="my_custom_runner" disabled={!canEditKey} />
        </Form.Item>

        <div className={styles.switchRow}>
          <span>{t("acp.enabled")}</span>
          <Form.Item name="enabled" valuePropName="checked" noStyle>
            <Switch aria-label={t("acp.enabled")} />
          </Form.Item>
        </div>

        <Form.Item
          name="command"
          label={t("acp.command")}
          rules={[{ required: true, message: t("acp.commandRequired") }]}
        >
          <Input placeholder="qwen" />
        </Form.Item>

        <Form.Item
          name="argsText"
          label={t("acp.args")}
          tooltip={t("acp.argsHelp")}
        >
          <Input.TextArea autoSize={{ minRows: 2, maxRows: 6 }} />
        </Form.Item>

        <div className={styles.formTopActions}>
          <Button
            type="text"
            size="small"
            icon={<LinkOutlined size="1em" />}
            onClick={() => openExternalLink(getACPDocsUrl(i18n.language))}
            title={t("acp.docsHelp")}
            className={styles.docs}
            style={{ color: "var(--app-accent)" }}
          >
            {t("acp.docs")}
          </Button>
        </div>

        <div className={styles.switchRow}>
          <span>{t("acp.trusted")}</span>
          <Form.Item name="trusted" valuePropName="checked" noStyle>
            <Switch aria-label={t("acp.trusted")} />
          </Form.Item>
        </div>
        <p className={styles.trustHint}>{t("acp.trustedHelp")}</p>

        <Collapse
          ghost
          className={styles.advanced}
          expandIcon={({ isActive }) => (
            <ChevronRight
              size={16}
              style={{ transform: isActive ? "rotate(90deg)" : undefined }}
            />
          )}
          items={[
            {
              key: "advanced",
              label: t("common.advancedSettings"),
              forceRender: true,
              children: (
                <>
                  <Form.Item
                    name="envText"
                    label={t("acp.env")}
                    tooltip={t("acp.envHelp")}
                    rules={[
                      {
                        validator: async (_, value) => {
                          const invalidLine = findInvalidEnvLine(value);
                          if (invalidLine) {
                            throw new Error(
                              t("acp.envInvalidLine", { line: invalidLine }),
                            );
                          }
                        },
                      },
                    ]}
                  >
                    <Input.TextArea autoSize={{ minRows: 2, maxRows: 6 }} />
                  </Form.Item>

                  <Form.Item
                    name="tool_parse_mode"
                    label={t("acp.toolParseMode")}
                    rules={[
                      {
                        required: true,
                        message: t("acp.toolParseModeRequired"),
                      },
                    ]}
                  >
                    <Select
                      options={TOOL_PARSE_MODE_OPTIONS.map((option) => ({
                        ...option,
                        label: t(`acp.toolParseModes.${option.value}`),
                      }))}
                    />
                  </Form.Item>

                  <Form.Item
                    name="stdio_buffer_limit_bytes"
                    label={t("acp.stdioBufferLimit")}
                    tooltip={t("acp.stdioBufferLimitHelp")}
                    rules={[
                      {
                        required: true,
                        message: t("acp.stdioBufferLimitRequired"),
                      },
                      {
                        type: "number",
                        min: 1,
                        message: t("acp.stdioBufferLimitMin"),
                      },
                    ]}
                  >
                    <InputNumber
                      style={{ width: "100%" }}
                      min={1}
                      step={1024}
                      placeholder={String(ACP_DEFAULT_STDIO_BUFFER_LIMIT_BYTES)}
                    />
                  </Form.Item>
                </>
              ),
            },
          ]}
        />
      </Form>
    </Drawer>
  );
}
