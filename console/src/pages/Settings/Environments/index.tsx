import { DeleteAction } from "@/components/interaction/DeleteAction";
import { useMemo, useState } from "react";
import { Button, Input, Modal } from "@agentscope-ai/design";
import InlineHelp from "@/components/InlineHelp";
import {
  Eye,
  EyeOff,
  LockKeyhole,
  Pencil,
  Plus,
  RotateCcw,
  Search,
  Zap,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import type { EnvSpec, EnvVar } from "../../../api/types";
import api from "../../../api";
import { PageHeader } from "@/components/PageHeader";
import { useAppMessage } from "../../../hooks/useAppMessage";
import { useEnvVars } from "./useEnvVars";
import styles from "./index.module.less";
import { SettingsDrawer } from "@/components/interaction/SettingsDrawer";
import { useAutoSave } from "@/hooks/useAutoSave";

type EditorState = {
  key: string;
  value: string;
  isNew: boolean;
} | null;

function SourceBadge({ source }: { source: EnvSpec["source"] }) {
  const { t } = useTranslation();
  return (
    <span className={`${styles.badge} ${styles[source]}`}>
      {t(`environments.source.${source}`)}
    </span>
  );
}

function ValueText({
  value,
  secret = false,
}: {
  value: string;
  secret?: boolean;
}) {
  const { t } = useTranslation();
  const [visible, setVisible] = useState(false);
  return (
    <div className={styles.valueText}>
      <code>
        {value === ""
          ? t("environments.emptyValue")
          : secret && !visible
          ? "••••••••"
          : value}
      </code>
      {secret && value !== "" && (
        <button
          type="button"
          className={styles.iconButton}
          onClick={() => setVisible((current) => !current)}
          aria-label={
            visible ? t("environments.hideValue") : t("environments.showValue")
          }
        >
          {visible ? <EyeOff size={16} /> : <Eye size={16} />}
        </button>
      )}
    </div>
  );
}

function EnvironmentsPage() {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const { envVars, catalog, loading, error, fetchAll } = useEnvVars();
  const [query, setQuery] = useState("");
  const [editor, setEditor] = useState<EditorState>(null);
  const [saving, setSaving] = useState(false);
  const [revealed, setRevealed] = useState(false);
  const [editorOpen, setEditorOpen] = useState(false);
  const openEditor = (next: EditorState) => {
    setRevealed(false);
    setEditor(next);
    setEditorOpen(true);
  };

  const configured = useMemo(
    () => new Map(envVars.map((item) => [item.key, item.value])),
    [envVars],
  );
  const catalogKeys = useMemo(
    () => new Set(catalog.map((item) => item.key)),
    [catalog],
  );
  const describeSpec = (item: EnvSpec) =>
    t(item.description_key, {
      defaultValue: t(`environments.mutabilityDescription.${item.mutability}`),
    });
  const normalizedQuery = query.trim().toLowerCase();
  const visibleCatalog = catalog.filter(
    (item) =>
      !normalizedQuery ||
      item.key.toLowerCase().includes(normalizedQuery) ||
      describeSpec(item).toLowerCase().includes(normalizedQuery),
  );
  const editableCatalog = visibleCatalog.filter((item) => item.editable);
  const readonlyCatalog = visibleCatalog.filter((item) => !item.editable);
  const customVariables = envVars.filter(
    (item) =>
      !catalogKeys.has(item.key) &&
      (!normalizedQuery || item.key.toLowerCase().includes(normalizedQuery)),
  );

  const saveEditor = async (close = true) => {
    if (!editor) return false;
    const key = editor.key.trim();
    if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(key)) {
      message.error(t("environments.invalidKeyFormat"));
      return false;
    }
    const keyIdentity = key.toUpperCase();
    const duplicate =
      editor.isNew &&
      (envVars.some((item) => item.key.toUpperCase() === keyIdentity) ||
        catalog.some((item) => item.key.toUpperCase() === keyIdentity));
    if (duplicate) {
      message.error(t("environments.duplicateKey", { name: key }));
      return false;
    }
    setSaving(true);
    try {
      await api.patchEnvs({ [key]: editor.value });
      if (close) {
        message.success(t("environments.applied"));
        setEditorOpen(false);
        await fetchAll();
      }
      return true;
    } catch (saveError) {
      message.error(
        saveError instanceof Error
          ? saveError.message
          : t("environments.saveFailed"),
      );
      return false;
    } finally {
      setSaving(false);
    }
  };
  const { schedule, flush } = useAutoSave(() => saveEditor(false));
  const closeEditor = async () => {
    if (!(await flush())) return;
    setEditorOpen(false);
    if (!editor?.isNew) await fetchAll();
  };

  const executeRemove = async (key: string, reset = false) => {
    try {
      if (reset) {
        await api.resetEnv(key);
      } else {
        await api.deleteEnv(key);
      }
      message.success(
        reset
          ? t("environments.resetSuccess")
          : t("environments.deleteSuccess", { name: key }),
      );
      await fetchAll();
    } catch (removeError) {
      message.error(
        removeError instanceof Error
          ? removeError.message
          : t("environments.deleteFailed"),
      );
      throw removeError;
    }
  };
  const removeVariable = (key: string) => {
    Modal.confirm({
      title: t("environments.resetVariable"),
      content: t("environments.deleteConfirm", { name: key }),
      okText: t("common.reset"),
      cancelText: t("common.cancel"),
      onOk: () => executeRemove(key, true),
    });
  };

  const renderKnownRows = (items: EnvSpec[]) =>
    items.map((item) => {
      const value = configured.get(item.key) ?? item.effective_value;
      const readonlyReason = item.readonly_reason_code
        ? t(`environments.readonlyReason.${item.readonly_reason_code}`)
        : "";
      return (
        <div className={styles.row} key={item.key}>
          <div className={styles.identity}>
            <div className={styles.variableName}>
              <code>{item.key}</code>
              <InlineHelp>{describeSpec(item)}</InlineHelp>
            </div>
          </div>
          <ValueText value={value} />
          <SourceBadge source={item.source} />
          <div className={styles.actions}>
            {item.editable ? (
              <>
                <button
                  type="button"
                  className={styles.iconButton}
                  onClick={() =>
                    openEditor({ key: item.key, value, isNew: false })
                  }
                  aria-label={t("common.edit")}
                >
                  <Pencil size={16} />
                </button>
                {item.configured && (
                  <button
                    type="button"
                    className={styles.iconButton}
                    onClick={() => removeVariable(item.key)}
                    aria-label={t("common.reset")}
                  >
                    <RotateCcw size={16} />
                  </button>
                )}
              </>
            ) : (
              <span className={styles.locked} title={readonlyReason}>
                <LockKeyhole size={15} /> {t("environments.startupOnly")}
              </span>
            )}
          </div>
        </div>
      );
    });

  return (
    <div className={styles.page}>
      <PageHeader
        parent={t("environments.parent")}
        current={t("environments.environments")}
        className={styles.pageHeader}
        extra={
          <Button
            type="primary"
            icon={<Plus size={16} />}
            onClick={() => openEditor({ key: "", value: "", isNew: true })}
          >
            {t("environments.addVariable")}
          </Button>
        }
      />
      <main className={styles.content}>
        <section className={styles.panel}>
          <div className={styles.filters}>
            <div className={styles.searchBox}>
              <Search size={17} />
              <Input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder={t("environments.searchPlaceholder")}
                aria-label={t("environments.searchPlaceholder")}
                variant="borderless"
              />
            </div>
          </div>

          {loading ? (
            <div className={styles.state}>{t("environments.loading")}</div>
          ) : error ? (
            <div className={styles.state}>
              <span>{error}</span>
              <Button size="small" onClick={fetchAll}>
                {t("environments.retry")}
              </Button>
            </div>
          ) : (
            <>
              <div className={styles.sectionHeading}>
                <h2>{t("environments.customSettings")}</h2>
                <span>{customVariables.length}</span>
              </div>
              <div className={styles.table}>
                {customVariables.length === 0 ? (
                  <div className={styles.empty}>
                    {t("environments.noCustomVariables")}
                  </div>
                ) : (
                  customVariables.map((item: EnvVar) => (
                    <div className={styles.row} key={item.key}>
                      <div className={styles.identity}>
                        <code>{item.key}</code>
                      </div>
                      <ValueText value={item.value} secret />
                      <span className={`${styles.badge} ${styles.user}`}>
                        {t("environments.source.user")}
                      </span>
                      <div className={styles.actions}>
                        <button
                          type="button"
                          className={styles.iconButton}
                          onClick={() =>
                            openEditor({
                              key: item.key,
                              value: item.value,
                              isNew: false,
                            })
                          }
                          aria-label={t("common.edit")}
                        >
                          <Pencil size={16} />
                        </button>
                        <DeleteAction
                          label={t("environments.deleteConfirm", {
                            name: item.key,
                          })}
                          onConfirm={() => executeRemove(item.key)}
                        />
                      </div>
                    </div>
                  ))
                )}
              </div>

              <div className={styles.sectionHeading}>
                <h2>{t("environments.liveSettings")}</h2>
                <span>{editableCatalog.length}</span>
              </div>
              <div className={`${styles.table} ${styles.editableTable}`}>
                {editableCatalog.length === 0 ? (
                  <div className={styles.empty}>
                    {t("environments.noLiveVariables")}
                  </div>
                ) : (
                  renderKnownRows(editableCatalog)
                )}
              </div>

              <div className={styles.sectionHeading}>
                <h2>{t("environments.readonlySettings")}</h2>
                <span>{readonlyCatalog.length}</span>
              </div>
              <div className={`${styles.table} ${styles.readonlyTable}`}>
                {readonlyCatalog.length === 0 ? (
                  <div className={styles.empty}>
                    {t("environments.noReadonlyVariables")}
                  </div>
                ) : (
                  renderKnownRows(readonlyCatalog)
                )}
              </div>
            </>
          )}
        </section>
      </main>

      <SettingsDrawer
        tall={false}
        width={560}
        open={editorOpen}
        title={
          editor?.isNew
            ? t("environments.addVariable")
            : t("environments.editVariable")
        }
        onClose={() => void closeEditor()}
        footer={
          editor?.isNew ? (
            <div className={styles.editorActions}>
              <Button onClick={() => void closeEditor()}>
                {t("common.cancel")}
              </Button>
              <Button
                type="primary"
                loading={saving}
                onClick={() => void saveEditor()}
              >
                {t("common.create")}
              </Button>
            </div>
          ) : undefined
        }
      >
        <div className={styles.editor}>
          <label>
            <span>{t("environments.key")}</span>
            <Input
              autoComplete="off"
              name="environment-variable-name"
              value={editor?.key ?? ""}
              disabled={!editor?.isNew}
              onChange={(event) =>
                setEditor(
                  (current) =>
                    current && { ...current, key: event.target.value },
                )
              }
              placeholder="VARIABLE_NAME"
            />
          </label>
          <label>
            <span>{t("environments.value")}</span>
            <Input
              value={editor?.value ?? ""}
              type={
                !revealed && (!editor || !catalogKeys.has(editor.key))
                  ? "password"
                  : "text"
              }
              autoComplete="new-password"
              name="environment-variable-value"
              suffix={
                editor && !catalogKeys.has(editor.key) ? (
                  <button
                    type="button"
                    className={styles.revealButton}
                    aria-label={t(
                      revealed
                        ? "environments.hideValue"
                        : "environments.showValue",
                    )}
                    onClick={() => setRevealed((value) => !value)}
                  >
                    {revealed ? <EyeOff size={16} /> : <Eye size={16} />}
                  </button>
                ) : undefined
              }
              onChange={(event) => {
                setEditor(
                  (current) =>
                    current && { ...current, value: event.target.value },
                );
                if (editor && !editor.isNew) schedule();
              }}
              placeholder={t("environments.valuePlaceholder")}
            />
          </label>
          <p>
            <Zap size={14} /> {t("environments.applyHint")}
          </p>
        </div>
      </SettingsDrawer>
    </div>
  );
}

export default EnvironmentsPage;
