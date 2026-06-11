import { useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { Check } from "lucide-react";
import { useTranslation } from "react-i18next";
import type {
  PoolSkillSpec,
  WorkspaceSkillSummary,
} from "../../../../api/types";
import { getAgentDisplayName } from "../../../../utils/agentDisplayName";
import { useSkillFilter } from "../../../Agent/Skills/useSkillFilter";
import { SkillFilterDropdown } from "../../../Agent/Skills/components/SkillFilterDropdown";
import styles from "../../../Agent/Skills/index.module.less";

interface BroadcastModalProps {
  open: boolean;
  skills: PoolSkillSpec[];
  workspaces: WorkspaceSkillSummary[];
  initialSkillNames: string[];
  onCancel: () => void;
  onConfirm: (skillNames: string[], workspaceIds: string[]) => Promise<void>;
}

export function BroadcastModal({
  open,
  skills,
  workspaces,
  initialSkillNames,
  onCancel,
  onConfirm,
}: BroadcastModalProps) {
  const { t } = useTranslation();
  const [selectedSkillNames, setSelectedSkillNames] =
    useState<string[]>(initialSkillNames);
  const [selectedWorkspaceIds, setSelectedWorkspaceIds] = useState<string[]>(
    [],
  );
  const [filterOpen, setFilterOpen] = useState(false);
  const { searchTags, setSearchTags, allTags, filteredSkills } =
    useSkillFilter(skills);

  const builtinSkillNames = useMemo(
    () => skills.filter((s) => s.source === "builtin").map((s) => s.name),
    [skills],
  );

  useEffect(() => {
    if (open) {
      setSelectedSkillNames(initialSkillNames);
      setSelectedWorkspaceIds([]);
      setSearchTags([]);
    }
  }, [open, initialSkillNames, setSearchTags]);

  const handleCancel = () => {
    setSelectedSkillNames([]);
    setSelectedWorkspaceIds([]);
    onCancel();
  };

  const canConfirm =
    selectedSkillNames.length > 0 && selectedWorkspaceIds.length > 0;

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        if (!v) handleCancel();
      }}
    >
      <DialogContent className="max-w-[640px] max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t("skillPool.broadcast")}</DialogTitle>
        </DialogHeader>

        <div className="flex flex-col gap-3">
          <div className={styles.pickerSection}>
            <div className={styles.pickerHeader}>
              <div className={styles.pickerLabel}>
                {t("skills.selectPoolItem")}
              </div>
              <div className={styles.bulkActions}>
                <Button
                  size="sm"
                  onClick={() =>
                    setSelectedSkillNames(filteredSkills.map((s) => s.name))
                  }
                >
                  {t("agent.selectAll")}
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => setSelectedSkillNames(builtinSkillNames)}
                >
                  {t("agent.selectBuiltin")}
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => setSelectedSkillNames([])}
                >
                  {t("skills.clearSelection")}
                </Button>
              </div>
            </div>
          </div>

          {allTags.length > 0 && (
            <div className="relative">
              <button
                className={`${styles.tagSelect} border rounded-md px-2 py-1 text-sm w-full text-left`}
                onClick={() => setFilterOpen((v) => !v)}
              >
                {searchTags.length > 0
                  ? searchTags.join(", ")
                  : t("skills.filterByTag")}
              </button>
              {filterOpen && (
                <div className="absolute z-50 bg-popover border rounded-md shadow-md mt-1 w-full">
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
            {filteredSkills.map((skill) => {
              const selected = selectedSkillNames.includes(skill.name);
              return (
                <div
                  key={skill.name}
                  className={`${styles.pickerCard} ${
                    styles.compactPickerCard
                  } ${selected ? styles.pickerCardSelected : ""}`}
                  onClick={() =>
                    setSelectedSkillNames(
                      selected
                        ? selectedSkillNames.filter((n) => n !== skill.name)
                        : [...selectedSkillNames, skill.name],
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
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <div
                        className={`${styles.pickerCardTitle} ${styles.compactPickerTitle}`}
                      >
                        {skill.name}
                      </div>
                    </TooltipTrigger>
                    <TooltipContent>{skill.name}</TooltipContent>
                  </Tooltip>
                </div>
              );
            })}
          </div>

          <div className={styles.pickerSection}>
            <div className={styles.pickerHeader}>
              <div className={styles.pickerLabel}>
                {t("skillPool.selectWorkspaces")}
              </div>
              <div className={styles.bulkActions}>
                <Button
                  size="sm"
                  onClick={() =>
                    setSelectedWorkspaceIds(workspaces.map((ws) => ws.agent_id))
                  }
                >
                  {t("skillPool.allWorkspaces")}
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => setSelectedWorkspaceIds([])}
                >
                  {t("skills.clearSelection")}
                </Button>
              </div>
            </div>
          </div>

          <div className={`${styles.pickerGrid} ${styles.compactPickerGrid}`}>
            {workspaces.map((workspace) => {
              const selected = selectedWorkspaceIds.includes(
                workspace.agent_id,
              );
              return (
                <div
                  key={workspace.agent_id}
                  className={`${styles.pickerCard} ${
                    styles.compactPickerCard
                  } ${selected ? styles.pickerCardSelected : ""}`}
                  onClick={() =>
                    setSelectedWorkspaceIds(
                      selected
                        ? selectedWorkspaceIds.filter(
                            (id) => id !== workspace.agent_id,
                          )
                        : [...selectedWorkspaceIds, workspace.agent_id],
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
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <div
                        className={`${styles.pickerCardTitle} ${styles.compactPickerTitle}`}
                      >
                        {getAgentDisplayName(
                          {
                            id: workspace.agent_id,
                            name: workspace.agent_name ?? "",
                          },
                          t,
                        )}
                      </div>
                    </TooltipTrigger>
                    <TooltipContent>{`ID: ${workspace.agent_id}`}</TooltipContent>
                  </Tooltip>
                </div>
              );
            })}
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={handleCancel}>
            {t("common.cancel")}
          </Button>
          <Button
            disabled={!canConfirm}
            onClick={() =>
              void onConfirm(selectedSkillNames, selectedWorkspaceIds)
            }
          >
            {t("common.confirm")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
