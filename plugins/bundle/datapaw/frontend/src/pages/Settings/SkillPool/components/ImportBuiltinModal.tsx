import { useState } from "react";
import { Button, Modal } from "@agentscope-ai/design";
import { CheckOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import type { BuiltinImportSpec } from "../../../../api/types";
import styles from "../../../Agent/Skills/index.module.less";

interface ImportBuiltinModalProps {
  open: boolean;
  loading: boolean;
  sources: BuiltinImportSpec[];
  onCancel: () => void;
  onConfirm: (selectedNames: string[]) => Promise<void>;
}

export function ImportBuiltinModal({
  open,
  loading,
  sources,
  onCancel,
  onConfirm,
}: ImportBuiltinModalProps) {
  const { t } = useTranslation();
  const [selectedNames, setSelectedNames] = useState<string[]>([]);

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
        <div className={styles.pickerLabel}>
          {t("skillPool.importBuiltinHint")}
        </div>
        <div className={styles.bulkActions}>
          <Button
            size="small"
            onClick={() => setSelectedNames(sources.map((item) => item.name))}
          >
            {t("agent.selectAll")}
          </Button>
          <Button size="small" onClick={() => setSelectedNames([])}>
            {t("skills.clearSelection")}
          </Button>
        </div>
        <div className={styles.pickerGrid}>
          {sources.map((item) => {
            const selected = selectedNames.includes(item.name);
            return (
              <div
                key={item.name}
                className={`${styles.pickerCard} ${
                  selected ? styles.pickerCardSelected : ""
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
                  <span className={styles.pickerCheck}>
                    <CheckOutlined />
                  </span>
                )}
                <div className={styles.pickerCardTitle}>{item.name}</div>
                <div className={styles.pickerCardMeta}>
                  {t("skillPool.sourceVersion")}: {item.version_text || "-"}
                </div>
                <div className={styles.pickerCardMeta}>
                  {t("skillPool.currentVersion")}:{" "}
                  {item.current_version_text || "-"}
                </div>
                <div className={styles.pickerCardMeta}>
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
