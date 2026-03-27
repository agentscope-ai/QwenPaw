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

  return (
    <Modal
      open={mode !== null}
      onCancel={handleCancel}
      onOk={handleOk}
      title={
        mode === "upload"
          ? t("skills.uploadToPool")
          : t("skills.downloadFromPool")
      }
    >
      <div style={{ display: "grid", gap: 12 }}>
        {mode === "upload" ? (
          <>
            <div className={styles.pickerLabel}>
              {t("skills.selectWorkspaceSkill")}
            </div>
            <div className={styles.bulkActions}>
              <Button
                size="small"
                onClick={() =>
                  setWorkspaceSkillNames(skills.map((s) => s.name))
                }
              >
                {t("skills.selectAll")}
              </Button>
              <Button size="small" onClick={() => setWorkspaceSkillNames([])}>
                {t("skills.clearSelection")}
              </Button>
            </div>
            <div className={`${styles.pickerGrid} ${styles.compactPickerGrid}`}>
              {skills.map((skill) => {
                const selected = workspaceSkillNames.includes(skill.name);
                return (
                  <div
                    key={skill.name}
                    className={`${styles.pickerCard} ${
                      styles.compactPickerCard
                    } ${selected ? styles.pickerCardSelected : ""}`}
                    onClick={() =>
                      setWorkspaceSkillNames(
                        selected
                          ? workspaceSkillNames.filter((n) => n !== skill.name)
                          : [...workspaceSkillNames, skill.name],
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
          </>
        ) : (
          <>
            <div className={styles.pickerLabel}>
              {t("skills.selectPoolItem")}
            </div>
            <div className={styles.bulkActions}>
              <Button
                size="small"
                onClick={() => setPoolSkillNames(poolSkills.map((s) => s.name))}
              >
                {t("skills.selectAll")}
              </Button>
              <Button size="small" onClick={() => setPoolSkillNames([])}>
                {t("skills.clearSelection")}
              </Button>
            </div>
            <div className={`${styles.pickerGrid} ${styles.compactPickerGrid}`}>
              {poolSkills.map((skill) => {
                const selected = poolSkillNames.includes(skill.name);
                return (
                  <div
                    key={skill.name}
                    className={`${styles.pickerCard} ${
                      styles.compactPickerCard
                    } ${selected ? styles.pickerCardSelected : ""}`}
                    onClick={() =>
                      setPoolSkillNames(
                        selected
                          ? poolSkillNames.filter((n) => n !== skill.name)
                          : [...poolSkillNames, skill.name],
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
          </>
        )}
      </div>
    </Modal>
  );
}
