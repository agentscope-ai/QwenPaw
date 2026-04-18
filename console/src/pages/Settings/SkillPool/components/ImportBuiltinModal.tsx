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
  defaultSelectedNames?: string[];
  onCancel: () => void;
  onConfirm: (selectedNames: string[]) => Promise<void>;
}

export function ImportBuiltinModal({
  open,
  loading,
  sources,
  notice,
  defaultSelectedNames,
  onCancel,
  onConfirm,
}: ImportBuiltinModalProps) {
  const { t } = useTranslation();
  const [selectedNames, setSelectedNames] = useState<string[]>([]);
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
    const nextSelected = (defaultSelectedNames || []).filter((name) =>
      availableNames.has(name),
    );
    setSelectedNames(nextSelected);
  }, [availableNames, defaultSelectedNames, open]);

  const handleCancel = () => {
    if (loading) return;
    setSelectedNames([]);
    onCancel();
  };

  const handleConfirm = async () => {
    await onConfirm(selectedNames);
  };

  return (
    <Modal
      open={open}
      onCancel={handleCancel}
      onOk={handleConfirm}
      title={t("skillPool.importBuiltin")}
      okButtonProps={{
        disabled: selectedNames.length === 0,
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
        <div className={skillStyles.bulkActions}>
          <Button
            size="small"
            type="primary"
            onClick={() => setSelectedNames(sources.map((item) => item.name))}
          >
            {t("agent.selectAll")}
          </Button>
          <Button size="small" onClick={() => setSelectedNames([])}>
            {t("skills.clearSelection")}
          </Button>
        </div>
        <div className={skillStyles.pickerGrid}>
          {sources.map((item) => {
            const selected = selectedNames.includes(item.name);
            return (
              <div
                key={item.name}
                className={`${skillStyles.pickerCard} ${
                  selected ? skillStyles.pickerCardSelected : ""
                }`}
                onClick={() =>
                  setSelectedNames(
                    selected
                      ? selectedNames.filter((name) => name !== item.name)
                      : [...selectedNames, item.name],
                  )
                }
              >
                {selected && (
                  <span className={skillStyles.pickerCheck}>
                    <CheckOutlined />
                  </span>
                )}
                <Tooltip title={item.name}>
                  <div className={skillStyles.pickerCardTitle}>{item.name}</div>
                </Tooltip>
                <div className={skillStyles.pickerCardMeta}>
                  {t("skillPool.sourceVersion")}: {item.version_text || "-"}
                </div>
                <div className={skillStyles.pickerCardMeta}>
                  {t("skillPool.currentVersion")}:{" "}
                  {item.current_version_text || "-"}
                </div>
                <div className={skillStyles.pickerCardMeta}>
                  {t(
                    `skillPool.importStatus${
                      item.status === "current"
                        ? "Current"
                        : item.status === "conflict"
                        ? "Conflict"
                        : "Missing"
                    }`,
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </Modal>
  );
}
