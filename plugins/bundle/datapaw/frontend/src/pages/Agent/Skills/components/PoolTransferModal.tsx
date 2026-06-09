import { useEffect, useState } from "react";
import { Button, Modal } from "@agentscope-ai/design";
import { CheckOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import type { PoolSkillSpec, SkillSpec } from "../../../../api/types";
import styles from "../index.module.less";

interface PoolTransferModalProps {
  mode: "upload" | "download" | null;
  skills: SkillSpec[];
  poolSkills: PoolSkillSpec[];
  onCancel: () => void;
  onUpload: (skillNames: string[]) => Promise<void>;
  onDownload: (poolSkillNames: string[]) => Promise<void>;
}

export function PoolTransferModal({
  mode,
  skills,
  poolSkills,
  onCancel,
  onUpload,
  onDownload,
}: PoolTransferModalProps) {
  const { t } = useTranslation();
  const [workspaceSkillNames, setWorkspaceSkillNames] = useState<string[]>([]);
  const [poolSkillNames, setPoolSkillNames] = useState<string[]>([]);

  useEffect(() => {
    if (mode !== null) {
      setWorkspaceSkillNames([]);
      setPoolSkillNames([]);
    }
  }, [mode]);

  const handleCancel = () => {
    onCancel();
  };

  const handleOk = async () => {
    if (mode === "upload") {
      await onUpload(workspaceSkillNames);
    } else {
      await onDownload(poolSkillNames);
    }
  };

  const isUpload = mode === "upload";
  const selectedNames = isUpload ? workspaceSkillNames : poolSkillNames;
  const setSelectedNames = isUpload
    ? setWorkspaceSkillNames
    : setPoolSkillNames;
  const items = isUpload ? skills : poolSkills;
  const hasSelection = selectedNames.length > 0;

  return (
    <Modal
      open={mode !== null}
      onCancel={handleCancel}
      title={isUpload ? t("skills.uploadToPool") : t("skills.downloadFromPool")}
      footer={
        <div className={styles.modalFooter}>
          <Button onClick={handleCancel} className={styles.modalCancelButton}>
            {t("common.cancel")}
          </Button>
          <Button
            type="primary"
            onClick={handleOk}
            disabled={!hasSelection}
            className={styles.modalOkButton}
          >
            {t("common.confirm")}
          </Button>
        </div>
      }
      width={600}
      className={styles.poolTransferModal}
    >
      <div className={styles.pickerSection}>
        <div className={styles.pickerHeader}>
          <div className={styles.pickerLabel}>
            {isUpload
              ? t("skills.selectWorkspaceSkill")
              : t("skills.selectPoolItem")}
          </div>
          <div className={styles.bulkActions}>
            <Button
              size="small"
              onClick={() => setSelectedNames([])}
              className={styles.bulkActionButton}
            >
              {t("skills.clearSelection")}
            </Button>
            <Button
              size="small"
              type="primary"
              onClick={() => setSelectedNames(items.map((s) => s.name))}
              className={styles.bulkActionButton}
            >
              {t("skills.selectAll")}
            </Button>
          </div>
        </div>

        <div className={`${styles.pickerGrid} ${styles.compactPickerGrid}`}>
          {items.map((skill) => {
            const selected = selectedNames.includes(skill.name);
            return (
              <div
                key={skill.name}
                className={`${styles.pickerCard} ${
                  selected ? styles.pickerCardSelected : ""
                }`}
                onClick={() =>
                  setSelectedNames(
                    selected
                      ? selectedNames.filter((n) => n !== skill.name)
                      : [...selectedNames, skill.name],
                  )
                }
              >
                {selected && (
                  <span
                    className={`${styles.pickerCheck} ${styles.compactPickerCheck}`}
                  >
                    <CheckOutlined />
                  </span>
                )}
                <div
                  className={`${styles.pickerCardTitle} ${styles.compactPickerTitle}`}
                >
                  {skill.name}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </Modal>
  );
}
