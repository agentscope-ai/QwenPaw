import { useEffect, useMemo, useState } from "react";
import { Button, Modal, Tooltip } from "@agentscope-ai/design";
import { CheckOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import type {
  BuiltinImportSpec,
  BuiltinUpdateNotice,
} from "../../../../api/types";
import skillStyles from "../../../Agent/Skills/index.module.less";
import { getBuiltinNoticeLines } from "../builtinNotice";
import styles from "../index.module.less";

interface ImportBuiltinModalProps {
  open: boolean;
  loading: boolean;
  sources: BuiltinImportSpec[];
  notice: BuiltinUpdateNotice | null;
  defaultLanguage: "en" | "zh";
  defaultSelectedNames?: string[];
  onCancel: () => void;
  onConfirm: (
    selections: Array<{ skill_name: string; language: "en" | "zh" }>,
  ) => Promise<void>;
}

export function ImportBuiltinModal({
  open,
  loading,
  sources,
  notice,
  defaultLanguage,
  defaultSelectedNames,
  onCancel,
  onConfirm,
}: ImportBuiltinModalProps) {
  const { t } = useTranslation();
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [language, setLanguage] = useState<"en" | "zh">(defaultLanguage);
  const availableNames = useMemo(
    () => new Set(sources.map((item) => item.name)),
    [sources],
  );
  const noticeLines = useMemo(
    () => getBuiltinNoticeLines(notice, t),
    [notice, t],
  );

  useEffect(() => {
    if (!open) return;
    setLanguage(defaultLanguage);
    setSelected(
      new Set(
        (defaultSelectedNames || []).filter((name) => availableNames.has(name)),
      ),
    );
  }, [availableNames, defaultLanguage, defaultSelectedNames, open]);

  const toggleSelection = (name: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  };

  const handleCancel = () => {
    if (loading) return;
    setSelected(new Set());
    onCancel();
  };

  const handleConfirm = async () => {
    await onConfirm(
      Array.from(selected).map((name) => ({ skill_name: name, language })),
    );
  };

  const getImportStatusLabel = (status?: string) => {
    switch (status) {
      case "current":
        return t("skillPool.importStatusCurrent");
      case "outdated":
        return t("skillPool.importStatusOutdated");
      case "conflict":
        return t("skillPool.importStatusConflict");
      default:
        return t("skillPool.importStatusMissing");
    }
  };

  return (
    <Modal
      open={open}
      onCancel={handleCancel}
      onOk={handleConfirm}
      title={t("skillPool.importBuiltin")}
      okButtonProps={{
        disabled: selected.size === 0,
        loading,
      }}
      width={720}
    >
      <div style={{ display: "grid", gap: 12 }}>
        {notice?.has_updates ? (
          <div className={styles.builtinNoticeSummary}>
            <div className={styles.builtinNoticeTitle}>
              {t("skillPool.builtinNoticeSummary", {
                count: notice.total_changes,
              })}
            </div>
            <div className={styles.builtinNoticeList}>
              {noticeLines.map((line) => (
                <div key={line}>{line}</div>
              ))}
            </div>
          </div>
        ) : null}
        <div className={skillStyles.pickerLabel}>
          {t("skillPool.importBuiltinHint")}
        </div>
        <div className={styles.importToolbar}>
          <Button
            size="small"
            type="primary"
            onClick={() =>
              setSelected(new Set(sources.map((item) => item.name)))
            }
          >
            {t("agent.selectAll")}
          </Button>
          <Button size="small" onClick={() => setSelected(new Set())}>
            {t("skills.clearSelection")}
          </Button>
          <span className={styles.importToolbarDivider} />
          <Button
            size="small"
            type={language === "zh" ? "primary" : "default"}
            onClick={() => setLanguage("zh")}
          >
            中文
          </Button>
          <Button
            size="small"
            type={language === "en" ? "primary" : "default"}
            onClick={() => setLanguage("en")}
          >
            English
          </Button>
        </div>
        <div className={skillStyles.pickerGrid}>
          {sources.map((item) => {
            const isSelected = selected.has(item.name);
            const langSpec = item.languages?.[language];
            const status = langSpec?.status || item.status;
            return (
              <div
                key={item.name}
                className={`${skillStyles.pickerCard} ${
                  isSelected ? skillStyles.pickerCardSelected : ""
                }`}
                onClick={() => toggleSelection(item.name)}
              >
                {isSelected && (
                  <span className={skillStyles.pickerCheck}>
                    <CheckOutlined />
                  </span>
                )}
                <Tooltip title={item.name}>
                  <div className={skillStyles.pickerCardTitle}>{item.name}</div>
                </Tooltip>
                <div className={skillStyles.pickerCardMeta}>
                  {t("skillPool.sourceVersion")}:{" "}
                  {langSpec?.version_text || item.version_text || "-"}
                </div>
                <div className={skillStyles.pickerCardMeta}>
                  {t("skillPool.currentVersion")}:{" "}
                  {item.current_version_text || "-"}
                </div>
                <div className={skillStyles.pickerCardMeta}>
                  {getImportStatusLabel(status)}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </Modal>
  );
}
