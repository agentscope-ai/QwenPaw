import { useEffect, useState } from "react";
import { Button, Modal, Select, Tooltip } from "@agentscope-ai/design";
import { CheckOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import type { PoolSkillSpec, SkillSpec } from "../../../../api/types";
import { isSkillBuiltin } from "@/utils/skill";
import { useSkillFilter } from "../useSkillFilter";
import { SkillFilterDropdown } from "./SkillFilterDropdown";
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
  const [filterOpen, setFilterOpen] = useState(false);
  const { searchTags, setSearchTags, allTags, filteredSkills } =
    useSkillFilter(poolSkills);

  useEffect(() => {
    if (mode !== null) {
      setWorkspaceSkillNames([]);
      setPoolSkillNames([]);
      setSearchTags([]);
    }
  }, [mode, setSearchTags]);

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
  const items = isUpload ? skills : filteredSkills;
  const hasSelection = selectedNames.length > 0;
  const builtinNames = items
    .filter((item) => isSkillBuiltin(item.source))
    .map((item) => item.name);

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
              type="primary"
              onClick={() => setSelectedNames(items.map((s) => s.name))}
              className={styles.bulkActionButton}
            >
              {t("skills.selectAll")}
            </Button>
            {!isUpload && (
              <Button
                size="small"
                onClick={() => setSelectedNames(builtinNames)}
                disabled={builtinNames.length === 0}
                className={styles.bulkActionButton}
              >
                {t("agent.selectBuiltin")}
              </Button>
            )}
            <Button
              size="small"
              onClick={() => setSelectedNames([])}
              className={styles.bulkActionButton}
            >
              {t("skills.clearSelection")}
            </Button>
          </div>
        </div>

        {!isUpload && (
          <Select
            mode="multiple"
            className={styles.tagSelect}
            placeholder={t("skills.filterByTag")}
            value={searchTags}
            onChange={setSearchTags}
            open={filterOpen}
            onOpenChange={setFilterOpen}
            allowClear
            maxTagCount="responsive"
            notFoundContent={<></>}
            popupRender={() =>
              allTags.length > 0 ? (
                <SkillFilterDropdown
                  allTags={allTags}
                  searchTags={searchTags}
                  setSearchTags={setSearchTags}
                  styles={styles}
                />
              ) : (
                <div className={styles.tagSelectEmpty}>
                  {t("skills.noTags")}
                </div>
              )
            }
          />
        )}

        <div className={`${styles.pickerGrid} ${styles.compactPickerGrid}`}>
          {items.map((skill) => {
            const selected = selectedNames.includes(skill.name);
            return (
              <div
                key={skill.name}
                className={`${styles.pickerCard} ${styles.compactPickerCard} ${
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
                <Tooltip title={skill.name}>
                  <div
                    className={`${styles.pickerCardTitle} ${styles.compactPickerTitle}`}
                  >
                    {skill.name}
                  </div>
                </Tooltip>
              </div>
            );
          })}
        </div>
      </div>
    </Modal>
  );
}
