import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Check } from "lucide-react";
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
    <Dialog open={mode !== null} onOpenChange={(o) => !o && handleCancel()}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>
            {isUpload ? t("skills.uploadToPool") : t("skills.downloadFromPool")}
          </DialogTitle>
          <DialogDescription className="sr-only">
            {isUpload ? t("skills.uploadToPool") : t("skills.downloadFromPool")}
          </DialogDescription>
        </DialogHeader>

        <div className={styles.pickerSection}>
          <div className={styles.pickerHeader}>
            <div className={styles.pickerLabel}>
              {isUpload
                ? t("skills.selectWorkspaceSkill")
                : t("skills.selectPoolItem")}
            </div>
            <div className={styles.bulkActions}>
              <Button
                size="sm"
                onClick={() => setSelectedNames(items.map((s) => s.name))}
                className={styles.bulkActionButton}
              >
                {t("skills.selectAll")}
              </Button>
              {!isUpload && (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => setSelectedNames(builtinNames)}
                  disabled={builtinNames.length === 0}
                  className={styles.bulkActionButton}
                >
                  {t("agent.selectBuiltin")}
                </Button>
              )}
              <Button
                size="sm"
                variant="outline"
                onClick={() => setSelectedNames([])}
                className={styles.bulkActionButton}
              >
                {t("skills.clearSelection")}
              </Button>
            </div>
          </div>

          {!isUpload && (
            <div className="relative">
              <div
                className={`${styles.tagSelect} flex flex-wrap gap-1 p-2 border rounded cursor-pointer`}
                onClick={() => setFilterOpen((o) => !o)}
              >
                {searchTags.length === 0 ? (
                  <span className="text-xs text-muted-foreground">
                    {t("skills.filterByTag")}
                  </span>
                ) : (
                  searchTags.map((tag) => (
                    <span
                      key={tag}
                      className="rounded bg-primary/10 px-1.5 py-0.5 text-xs text-primary"
                    >
                      {tag}
                    </span>
                  ))
                )}
              </div>
              {filterOpen && allTags.length > 0 && (
                <div className="absolute z-50 w-full rounded border bg-popover shadow-md mt-1">
                  <SkillFilterDropdown
                    allTags={allTags}
                    searchTags={searchTags}
                    setSearchTags={setSearchTags}
                    styles={styles}
                  />
                </div>
              )}
            </div>
          )}

          <div className={`${styles.pickerGrid} ${styles.compactPickerGrid}`}>
            {items.map((skill) => {
              const selected = selectedNames.includes(skill.name);
              return (
                <div
                  key={skill.name}
                  className={`${styles.pickerCard} ${
                    styles.compactPickerCard
                  } ${selected ? styles.pickerCardSelected : ""}`}
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
                      <Check size={12} />
                    </span>
                  )}
                  <div
                    className={`${styles.pickerCardTitle} ${styles.compactPickerTitle}`}
                    title={skill.name}
                  >
                    {skill.name}
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        <DialogFooter>
          <Button
            variant="outline"
            onClick={handleCancel}
            className={styles.modalCancelButton}
          >
            {t("common.cancel")}
          </Button>
          <Button
            onClick={handleOk}
            disabled={!hasSelection}
            className={styles.modalOkButton}
          >
            {t("common.confirm")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
