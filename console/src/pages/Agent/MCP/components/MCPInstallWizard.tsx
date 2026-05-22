import { useMemo, useState, useEffect } from "react";
import { Button, Input } from "@agentscope-ai/design";
import { ExportOutlined, ArrowLeftOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import type { MCPClientInfo } from "../../../../api/types";
import type { MCPMarketTemplate } from "../market/mcpTemplates";
import { MCPTemplateIcon } from "../market/templateIcons";
import {
  buildClientPayload,
  buildClientUpdatePayload,
  extractFieldValuesFromClient,
  isClientKeyTaken,
  validateTemplateFields,
  type MCPClientCreatePayload,
  type MCPClientUpdatePayload,
} from "../market/installTemplate";
import { getMcpClientKeyErrorCode } from "../utils/mcpClientKey";
import parentStyles from "../index.module.less";
import styles from "./MCPMarketplaceModal.module.less";

interface MCPInstallWizardProps {
  template: MCPMarketTemplate;
  existingKeys: string[];
  installing?: boolean;
  saving?: boolean;
  /** When set, wizard runs in edit mode for an installed market client. */
  editClient?: MCPClientInfo;
  marketUserNote?: string;
  onBack: () => void;
  onInstall?: (
    clientKey: string,
    payload: MCPClientCreatePayload,
  ) => Promise<boolean>;
  onSave?: (updates: MCPClientUpdatePayload) => Promise<boolean>;
}

export function MCPInstallWizard({
  template,
  existingKeys,
  installing = false,
  saving = false,
  editClient,
  marketUserNote = "",
  onBack,
  onInstall,
  onSave,
}: MCPInstallWizardProps) {
  const { t } = useTranslation();
  const isEdit = !!editClient;
  const busy = installing || saving;

  const [clientKey, setClientKey] = useState(
    () => editClient?.key ?? template.id,
  );
  const [displayName, setDisplayName] = useState(
    () => editClient?.name?.trim() || "",
  );
  const [fieldValues, setFieldValues] = useState<Record<string, string>>(() => {
    if (editClient) {
      return extractFieldValuesFromClient(template, editClient);
    }
    const initial: Record<string, string> = {};
    if (template.url) initial.url = template.url;
    return initial;
  });

  useEffect(() => {
    if (isEdit && editClient) {
      setClientKey(editClient.key);
      setDisplayName(editClient.name?.trim() || "");
      setFieldValues(extractFieldValuesFromClient(template, editClient));
      return;
    }
    setClientKey(template.id);
    setDisplayName(t(template.nameKey));
    const initial: Record<string, string> = {};
    if (template.url) initial.url = template.url;
    setFieldValues(initial);
  }, [template, editClient, isEdit, t]);

  const keysForConflict = useMemo(
    () =>
      isEdit && editClient
        ? existingKeys.filter((k) => k !== editClient.key)
        : existingKeys,
    [existingKeys, isEdit, editClient],
  );

  const keyConflict = useMemo(
    () => !isEdit && isClientKeyTaken(clientKey, keysForConflict),
    [clientKey, keysForConflict, isEdit],
  );

  const keyFormatError = useMemo(
    () => (!isEdit ? getMcpClientKeyErrorCode(clientKey) : null),
    [clientKey, isEdit],
  );

  const fieldValidation = useMemo(
    () => validateTemplateFields(template, fieldValues),
    [template, fieldValues],
  );

  const hasSecretFields = template.fields.some((f) => f.type === "secret");

  const canSubmit =
    clientKey.trim().length > 0 &&
    displayName.trim().length > 0 &&
    (isEdit || (!keyConflict && !keyFormatError)) &&
    fieldValidation.valid &&
    !busy;

  const handleSubmit = async () => {
    if (!canSubmit) return;
    const key = clientKey.trim();
    const name = displayName.trim();
    const note = marketUserNote?.trim() || undefined;

    if (isEdit && onSave) {
      const updates = buildClientUpdatePayload(
        template,
        fieldValues,
        key,
        name,
        note,
      );
      await onSave(updates);
      return;
    }

    if (!onInstall) return;
    const payload = buildClientPayload(template, fieldValues, key, name, note);
    await onInstall(key, payload);
  };

  return (
    <div className={styles.wizard}>
      <button
        type="button"
        className={styles.wizardBack}
        onClick={onBack}
        disabled={busy}
      >
        <ArrowLeftOutlined />
        {isEdit ? t("common.cancel") : t("mcp.wizard.back")}
      </button>

      <div className={styles.wizardHeader}>
        <MCPTemplateIcon iconId={template.iconId} size="sm" />
        <div>
          <h3 className={styles.wizardTitle}>{t(template.nameKey)}</h3>
          <p className={styles.wizardDesc}>{t(template.descriptionKey)}</p>
        </div>
        {template.docsUrl && (
          <a
            href={template.docsUrl}
            target="_blank"
            rel="noopener noreferrer"
            className={styles.docsLink}
            onClick={(e) => e.stopPropagation()}
          >
            <ExportOutlined />
            {t("mcp.wizard.docs")}
          </a>
        )}
      </div>

      {isEdit && hasSecretFields && (
        <div className={parentStyles.maskedFieldHint}>
          {t("mcp.maskedFieldHint")}
        </div>
      )}

      <div className={styles.wizardField}>
        <label className={styles.fieldLabel}>
          {t("mcp.form.name")}
          <span className={styles.required}>*</span>
        </label>
        <Input
          value={displayName}
          onChange={(e) => setDisplayName(e.target.value)}
          placeholder={t("mcp.form.namePlaceholder")}
          disabled={busy}
        />
      </div>

      <div className={styles.wizardField}>
        <label className={styles.fieldLabel}>
          {t("mcp.form.key")}
          <span className={styles.required}>*</span>
        </label>
        <Input
          value={clientKey}
          onChange={(e) => setClientKey(e.target.value)}
          placeholder={t("mcp.form.keyPlaceholder")}
          disabled={busy || isEdit}
        />
        {!isEdit && (
          <>
            <span className={styles.fieldHint}>{t("mcp.wizard.keyHint")}</span>
            {keyFormatError && (
              <span className={styles.fieldError}>
                {t(`mcp.keyValidation.${keyFormatError}`)}
              </span>
            )}
            {keyConflict && (
              <span className={styles.fieldError}>
                {t("mcp.wizard.keyConflict")}
              </span>
            )}
          </>
        )}
      </div>

      {template.fields.map((field) => (
        <div key={field.key} className={styles.wizardField}>
          <label className={styles.fieldLabel}>
            {t(field.labelKey)}
            {field.required && <span className={styles.required}>*</span>}
          </label>
          {field.type === "secret" ? (
            <Input.Password
              value={fieldValues[field.key] ?? ""}
              onChange={(e) =>
                setFieldValues((prev) => ({
                  ...prev,
                  [field.key]: e.target.value,
                }))
              }
              placeholder={
                field.placeholderKey ? t(field.placeholderKey) : undefined
              }
              disabled={busy}
            />
          ) : field.key === "allowed_directories" ? (
            <Input.TextArea
              value={fieldValues[field.key] ?? ""}
              onChange={(e) =>
                setFieldValues((prev) => ({
                  ...prev,
                  [field.key]: e.target.value,
                }))
              }
              placeholder={
                field.placeholderKey ? t(field.placeholderKey) : undefined
              }
              autoSize={{ minRows: 2, maxRows: 4 }}
              disabled={busy}
            />
          ) : (
            <Input
              value={fieldValues[field.key] ?? ""}
              onChange={(e) =>
                setFieldValues((prev) => ({
                  ...prev,
                  [field.key]: e.target.value,
                }))
              }
              placeholder={
                field.placeholderKey ? t(field.placeholderKey) : undefined
              }
              disabled={busy}
            />
          )}
        </div>
      ))}

      {template.fields.length === 0 && !isEdit && (
        <p className={styles.wizardNoFields}>{t("mcp.wizard.noFields")}</p>
      )}

      <div className={styles.wizardFooter}>
        <Button onClick={onBack} disabled={busy}>
          {t("common.cancel")}
        </Button>
        <Button
          type="primary"
          onClick={handleSubmit}
          loading={busy}
          disabled={!canSubmit}
        >
          {isEdit ? t("common.save") : t("mcp.wizard.install")}
        </Button>
      </div>
    </div>
  );
}
